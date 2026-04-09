import axios from 'axios';

import type { ApiErrorDetails, ApiErrorEnvelope, ApiErrorPayload, User, ValidationErrorDetail } from '../../types';

const BASENAME = (import.meta.env.BASE_URL || '/').replace(/\/$/, '') || '/';
const browserOriginApiBase =
  typeof window !== 'undefined'
    ? `${window.location.protocol}//${window.location.hostname}:22223/api/v1`
    : 'http://localhost:22223/api/v1';
const inferredApiBase =
  BASENAME === '/'
    ? browserOriginApiBase
    : `${BASENAME.replace(/\/web$/, '')}/api/v1`;
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || inferredApiBase;

const REQUEST_ID_HEADER = 'x-request-id';

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

export const resolveStoredUser = (): Partial<User> | null => {
  try {
    const raw = localStorage.getItem('user');
    if (!raw) return null;
    const parsed = JSON.parse(raw) as unknown;
    return isRecord(parsed) ? (parsed as Partial<User>) : null;
  } catch {
    return null;
  }
};

export const resolveActiveWorkspaceId = () => {
  const user = resolveStoredUser();
  if (typeof user?.workspace_id === 'string' && user.workspace_id.trim().length > 0) {
    return user.workspace_id;
  }
  throw new Error('No active workspace found in local session');
};

export const resolveApiUrl = (path: string) => {
  const baseUrl = API_BASE_URL.endsWith('/') ? API_BASE_URL : `${API_BASE_URL}/`;
  return new URL(path.replace(/^\//, ''), baseUrl).toString();
};

const clearStoredAuth = () => {
  localStorage.removeItem('token');
  localStorage.removeItem('user');
};

export const redirectToLogin = () => {
  clearStoredAuth();
  if (typeof window === 'undefined') return;
  const loginPath = `${BASENAME === '/' ? '' : BASENAME}/login`;
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
