import { apiClient } from '../../lib/api/client';
import type { ApiKey, ApiKeyCreateResponse, AuthTokenResponse, ChangePasswordRequest } from '../../types';

export interface LoginCredentials {
  username: string;
  password: string;
}

export interface ContextSwitchRequest {
  workspace_id: string;
}

export const authApi = {
  login: async (credentials: LoginCredentials): Promise<AuthTokenResponse> => {
    const { data } = await apiClient.post<AuthTokenResponse>('/auth/login', credentials);
    return data;
  },
  changePassword: async (payload: ChangePasswordRequest): Promise<AuthTokenResponse> => {
    const { data } = await apiClient.post<AuthTokenResponse>('/auth/change-password', payload);
    return data;
  },
  getContext: async (): Promise<AuthTokenResponse> => {
    const { data } = await apiClient.get<AuthTokenResponse>('/auth/context');
    return data;
  },
  switchContext: async (payload: ContextSwitchRequest): Promise<AuthTokenResponse> => {
    const { data } = await apiClient.post<AuthTokenResponse>('/auth/context/switch', payload);
    return data;
  },
  logout: async () => {
    await apiClient.post('/auth/logout');
  },
  listApiKeys: async (): Promise<ApiKey[]> => {
    const { data } = await apiClient.get<ApiKey[]>('/auth/apikeys');
    return data;
  },
  createApiKey: async (payload: { name: string }): Promise<ApiKeyCreateResponse> => {
    const { data } = await apiClient.post<ApiKeyCreateResponse>('/auth/apikeys', payload);
    return data;
  },
  revokeApiKey: async (id: string): Promise<void> => {
    await apiClient.delete(`/auth/apikeys/${id}`);
  },
};
