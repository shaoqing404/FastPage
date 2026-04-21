import axios from 'axios';

import type {
  ApiErrorDetails,
  ApiErrorEnvelope,
  ApiErrorPayload,
  AuthTokenResponse,
  TenantMembership,
  User,
  ValidationErrorDetail,
  Workspace,
  WorkspaceListItem,
  WorkspaceInviteAcceptResponse,
  WorkspaceMembership,
} from '../../types';

const BASENAME = (import.meta.env.BASE_URL || '/').replace(/\/$/, '') || '/';
const browserOriginApiBase =
  typeof window !== 'undefined'
    ? `${window.location.protocol}//${window.location.hostname}:22223/api/v1`
    : 'http://localhost:22223/api/v1';

const isLoopbackHostname = (hostname: string) => hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '::1';

const resolveConfiguredApiBase = () => {
  const configured = import.meta.env.VITE_API_BASE_URL?.trim();
  if (!configured) return browserOriginApiBase;
  if (typeof window === 'undefined') return configured;

  try {
    const configuredUrl = new URL(configured);
    const browserHostname = window.location.hostname;

    // If the frontend is opened through a LAN/IP hostname but the build-time
    // API target still points to localhost, prefer the current browser host.
    if (!isLoopbackHostname(browserHostname) && isLoopbackHostname(configuredUrl.hostname)) {
      return browserOriginApiBase;
    }
  } catch {
    // Keep explicit non-URL values untouched and let requests fail loudly.
  }

  return configured;
};

export const API_BASE_URL = resolveConfiguredApiBase();

const REQUEST_ID_HEADER = 'x-request-id';
const SESSION_EVENT = 'pageindex:session-changed';
const STORAGE_KEYS = {
  token: 'token',
  user: 'user',
  workspace: 'workspace',
  memberships: 'memberships',
  tenantMembership: 'tenant_membership',
  workspaceMembership: 'workspace_membership',
} as const;

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null;

const normalizeHeaderValue = (value: unknown): string | null => {
  if (typeof value === 'string' && value.trim()) return value;
  if (Array.isArray(value)) {
    const first = value.find((item): item is string => typeof item === 'string' && item.trim().length > 0);
    return first ?? null;
  }
  return null;
};

const statusToErrorCode = (status: number | null | undefined) => {
  switch (status) {
    case 400:
      return 'VALIDATION_ERROR';
    case 401:
    case 403:
      return 'AUTH_TOKEN_INVALID';
    case 404:
      return 'RESOURCE_NOT_FOUND';
    case 409:
      return 'CONFLICT_STATE';
    case 413:
      return 'UPLOAD_TOO_LARGE';
    case 422:
      return 'VALIDATION_ERROR';
    case 502:
      return 'PROVIDER_PROBE_FAILED';
    default:
      return 'INTERNAL_ERROR';
  }
};

const formatValidationMessage = (detail: unknown) => {
  if (!Array.isArray(detail)) return null;
  const messages = detail
    .map((item) => {
      if (typeof item === 'string') return item;
      if (!isRecord(item)) return null;
      const validationItem = item as ValidationErrorDetail;
      const location = Array.isArray(validationItem.loc) ? validationItem.loc.join('.') : null;
      const message = typeof validationItem.msg === 'string' ? validationItem.msg : null;
      if (location && message) return `${location}: ${message}`;
      return message;
    })
    .filter((value): value is string => Boolean(value));
  return messages.length > 0 ? messages.join('; ') : null;
};

const formatLegacyDetailMessage = (detail: unknown) => {
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail)) return formatValidationMessage(detail);
  if (isRecord(detail) && typeof detail.message === 'string' && detail.message.trim()) return detail.message;
  return null;
};

const isApiErrorPayload = (value: unknown): value is ApiErrorPayload =>
  isRecord(value) &&
  typeof value.code === 'string' &&
  typeof value.message === 'string' &&
  'request_id' in value;

const isApiErrorEnvelope = (value: unknown): value is ApiErrorEnvelope =>
  isRecord(value) && 'error' in value && isApiErrorPayload(value.error);

const createApiErrorPayload = (
  data: unknown,
  status: number | null,
  requestId: string | null,
  fallbackMessage: string,
): ApiErrorPayload => {
  if (isApiErrorEnvelope(data)) {
    return {
      ...data.error,
      request_id: data.error.request_id ?? requestId,
    };
  }

  if (isRecord(data) && 'detail' in data) {
    const details = data.detail;
    return {
      code: statusToErrorCode(status),
      message: formatLegacyDetailMessage(details) ?? fallbackMessage,
      request_id: requestId,
      ...(details !== undefined && (Array.isArray(details) || isRecord(details)) ? { details: details as ApiErrorDetails } : {}),
    };
  }

  if (typeof data === 'string' && data.trim()) {
    return {
      code: statusToErrorCode(status),
      message: data,
      request_id: requestId,
    };
  }

  return {
    code: statusToErrorCode(status),
    message: fallbackMessage,
    request_id: requestId,
  };
};

export class ApiClientError extends Error {
  readonly code: string;
  readonly requestId: string | null;
  readonly request_id: string | null;
  readonly details?: ApiErrorDetails;
  readonly status: number | null;

  constructor(payload: ApiErrorPayload, options: { status?: number | null } = {}) {
    super(payload.message);
    this.name = 'ApiClientError';
    this.code = payload.code;
    this.requestId = payload.request_id;
    this.request_id = payload.request_id;
    this.details = payload.details;
    this.status = options.status ?? null;
  }
}

export const isApiClientError = (error: unknown): error is ApiClientError => error instanceof ApiClientError;

const parseStoredJson = <T>(key: string): T | null => {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
};

export const resolveStoredUser = (): Partial<User> | null => {
  const parsed = parseStoredJson<unknown>(STORAGE_KEYS.user);
  return isRecord(parsed) ? (parsed as Partial<User>) : null;
};

export const resolveStoredWorkspace = (): Partial<Workspace> | null => {
  const parsed = parseStoredJson<unknown>(STORAGE_KEYS.workspace);
  return isRecord(parsed) ? (parsed as Partial<Workspace>) : null;
};

export const resolveStoredTenantMembership = (): Partial<TenantMembership> | null => {
  const parsed = parseStoredJson<unknown>(STORAGE_KEYS.tenantMembership);
  return isRecord(parsed) ? (parsed as Partial<TenantMembership>) : null;
};

export const resolveStoredWorkspaceMembership = (): Partial<WorkspaceMembership> | null => {
  const parsed = parseStoredJson<unknown>(STORAGE_KEYS.workspaceMembership);
  return isRecord(parsed) ? (parsed as Partial<WorkspaceMembership>) : null;
};

export const resolveStoredMemberships = (): TenantMembership[] => {
  const parsed = parseStoredJson<unknown>(STORAGE_KEYS.memberships);
  if (!Array.isArray(parsed)) return [];
  return parsed.filter((item): item is TenantMembership => isRecord(item) && typeof item.id === 'string') as TenantMembership[];
};

export const resolveActiveWorkspaceId = () => {
  const workspace = resolveStoredWorkspace();
  if (typeof workspace?.id === 'string' && workspace.id.trim().length > 0) {
    return workspace.id;
  }
  const user = resolveStoredUser();
  if (typeof user?.workspace_id === 'string' && user.workspace_id.trim().length > 0) {
    return user.workspace_id;
  }
  throw new Error('No active workspace found in local session');
};

export const resolveAppPath = (path: string) => {
  const basePath = BASENAME === '/' ? '' : BASENAME;
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  return `${basePath}${normalizedPath}`;
};

export const resolveApiUrl = (path: string) => {
  const baseUrl = API_BASE_URL.endsWith('/') ? API_BASE_URL : `${API_BASE_URL}/`;
  return new URL(path.replace(/^\//, ''), baseUrl).toString();
};

const dispatchSessionChange = () => {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new Event(SESSION_EVENT));
};

const writeStoredJson = (key: string, value: unknown) => {
  localStorage.setItem(key, JSON.stringify(value));
};

const mergeMemberships = (memberships: TenantMembership[], nextMembership: TenantMembership) => {
  const merged = memberships.filter((membership) => membership.id !== nextMembership.id && membership.tenant_id !== nextMembership.tenant_id);
  return [...merged, nextMembership];
};

export const storeAuthTokenResponse = (response: AuthTokenResponse) => {
  localStorage.setItem(STORAGE_KEYS.token, response.access_token);
  writeStoredJson(STORAGE_KEYS.user, response.user);
  writeStoredJson(STORAGE_KEYS.workspace, response.workspace);
  writeStoredJson(STORAGE_KEYS.memberships, response.memberships);
  writeStoredJson(STORAGE_KEYS.tenantMembership, response.tenant_membership);
  writeStoredJson(STORAGE_KEYS.workspaceMembership, response.workspace_membership);
  dispatchSessionChange();
};

export const storeInviteAcceptResponse = (response: WorkspaceInviteAcceptResponse) => {
  const currentUser = resolveStoredUser() || {};
  const nextUser: Partial<User> = {
    ...currentUser,
    tenant_id: response.tenant_membership.tenant_id,
    workspace_id: response.workspace.id,
    membership_role: response.workspace_membership.role,
    tenant_membership_role: response.tenant_membership.role,
    tenant_membership_status: response.tenant_membership.status,
    workspace_membership_role: response.workspace_membership.role,
    workspace_membership_status: response.workspace_membership.status,
  };

  localStorage.setItem(STORAGE_KEYS.token, response.access_token);
  writeStoredJson(STORAGE_KEYS.user, nextUser);
  writeStoredJson(STORAGE_KEYS.workspace, response.workspace);
  writeStoredJson(STORAGE_KEYS.memberships, mergeMemberships(resolveStoredMemberships(), response.tenant_membership));
  writeStoredJson(STORAGE_KEYS.tenantMembership, response.tenant_membership);
  writeStoredJson(STORAGE_KEYS.workspaceMembership, response.workspace_membership);
  dispatchSessionChange();
};

export const storeClaimResponse = (response: WorkspaceInviteAcceptResponse) => {
  const nextUser: Partial<User> = response.user ? {
    ...response.user,
    tenant_id: response.tenant_membership.tenant_id,
    workspace_id: response.workspace.id,
    membership_role: response.workspace_membership.role,
    tenant_membership_role: response.tenant_membership.role,
    tenant_membership_status: response.tenant_membership.status,
    workspace_membership_role: response.workspace_membership.role,
    workspace_membership_status: response.workspace_membership.status,
  } : {
    tenant_id: response.tenant_membership.tenant_id,
    workspace_id: response.workspace.id,
    membership_role: response.workspace_membership.role,
    tenant_membership_role: response.tenant_membership.role,
    tenant_membership_status: response.tenant_membership.status,
    workspace_membership_role: response.workspace_membership.role,
    workspace_membership_status: response.workspace_membership.status,
  };

  localStorage.setItem(STORAGE_KEYS.token, response.access_token);
  writeStoredJson(STORAGE_KEYS.user, nextUser);
  writeStoredJson(STORAGE_KEYS.workspace, response.workspace);
  writeStoredJson(STORAGE_KEYS.memberships, [response.tenant_membership]);
  writeStoredJson(STORAGE_KEYS.tenantMembership, response.tenant_membership);
  writeStoredJson(STORAGE_KEYS.workspaceMembership, response.workspace_membership);
  dispatchSessionChange();
};

export const updateStoredWorkspace = (workspace: Workspace | Partial<Workspace> | WorkspaceListItem) => {
  const currentWorkspace = resolveStoredWorkspace() || {};
  writeStoredJson(STORAGE_KEYS.workspace, {
    ...currentWorkspace,
    ...workspace,
  });
  dispatchSessionChange();
};

export const clearStoredAuth = () => {
  Object.values(STORAGE_KEYS).forEach((key) => localStorage.removeItem(key));
  dispatchSessionChange();
};

export const subscribeToSessionChanges = (callback: () => void) => {
  if (typeof window === 'undefined') {
    return () => undefined;
  }

  const handler = () => callback();
  window.addEventListener(SESSION_EVENT, handler);
  window.addEventListener('storage', handler);
  return () => {
    window.removeEventListener(SESSION_EVENT, handler);
    window.removeEventListener('storage', handler);
  };
};

export const redirectToLogin = () => {
  clearStoredAuth();
  if (typeof window === 'undefined') return;
  const loginPath = resolveAppPath('/login');
  if (window.location.pathname !== loginPath) {
    window.location.href = loginPath;
  }
};

export const parseApiErrorResponse = async (response: Response) => {
  const contentType = response.headers.get('content-type') || '';
  const requestId = response.headers.get('X-Request-ID') || response.headers.get('x-request-id');
  let body: unknown = null;

  if (contentType.includes('application/json')) {
    try {
      body = await response.json();
    } catch {
      body = null;
    }
  } else {
    const text = await response.text();
    body = text.trim() ? text : null;
  }

  const apiError = new ApiClientError(
    createApiErrorPayload(body, response.status, requestId, `Request failed with status ${response.status}`),
    { status: response.status },
  );

  if (response.status === 401) {
    redirectToLogin();
  }

  return apiError;
};

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (!axios.isAxiosError(error)) {
      return Promise.reject(error);
    }

    const status = error.response?.status ?? null;
    const requestId = normalizeHeaderValue(error.response?.headers?.[REQUEST_ID_HEADER]);
    const fallbackMessage = error.message || (status ? `Request failed with status ${status}` : 'Network request failed');
    const apiError = new ApiClientError(
      createApiErrorPayload(error.response?.data, status, requestId, fallbackMessage),
      { status },
    );

    if (status === 401) {
      redirectToLogin();
    }

    return Promise.reject(apiError);
  }
);
