import { apiClient } from '../../lib/api/client';
import type { ModelProvider } from '../../types';

export interface ProviderPayload {
  provider_type: string;
  name: string;
  base_url: string;
  api_key?: string;
  default_model: string;
  supported_models?: string[];
  extra_headers?: Record<string, string>;
  enabled?: boolean;
  is_default?: boolean;
}

export const providersApi = {
  list: async (): Promise<ModelProvider[]> => {
    const { data } = await apiClient.get<ModelProvider[]>('/model-providers');
    return data;
  },
  create: async (payload: ProviderPayload): Promise<ModelProvider> => {
    const { data } = await apiClient.post<ModelProvider>('/model-providers', payload);
    return data;
  },
  update: async (id: string, payload: Partial<ProviderPayload>): Promise<ModelProvider> => {
    const { data } = await apiClient.patch<ModelProvider>(`/model-providers/${id}`, payload);
    return data;
  },
  probeModels: async (id: string): Promise<ModelProvider> => {
    const { data } = await apiClient.post<ModelProvider>(`/model-providers/${id}/probe-models`);
    return data;
  },
  delete: async (id: string): Promise<void> => {
    await apiClient.delete(`/model-providers/${id}`);
  },
};
