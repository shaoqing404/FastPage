import { apiClient } from '../../lib/api/client';
import type { ApiKey, ApiKeyCreateResponse, User } from '../../types';

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface LoginCredentials {
  username: string;
  password: string;
}

export const authApi = {
  login: async (credentials: LoginCredentials): Promise<LoginResponse> => {
    const { data } = await apiClient.post<LoginResponse>('/auth/login', credentials);
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
