import { apiClient } from '../../lib/api/client';
import type { ModelProvider, ModelProviderEndpoint, ProbeRuntimeResult } from '../../types';

export interface ProviderEndpointPayload {
  capability: 'chat' | 'embedding' | 'rerank';
  adapter: 'openai_chat' | 'openai_embedding' | 'generic_rerank' | 'dashscope_rerank';
  base_url: string;
  model: string;
  api_key?: string | null;
  extra_headers?: Record<string, unknown>;
  config?: Record<string, unknown>;
  enabled?: boolean;
  is_default?: boolean;
}

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
  scope?: 'tenant' | 'workspace';
  share_mode?: 'none' | 'all' | 'selected';
  shared_workspace_ids?: string[];
  endpoints?: ProviderEndpointPayload[];
}

export interface ProbeRuntimeRequest {
  capability?: 'chat' | 'embedding' | 'rerank';
  endpoint_id?: string;
}

export interface ProbeRuntimeDraftRequest {
  provider_type: string;
  base_url: string;
  api_key: string;
  endpoints: ProviderEndpointPayload[];
  capability?: 'chat' | 'embedding' | 'rerank';
  endpoint_id?: string;
}

export const providersApi = {
  list: async (scope: 'tenant' | 'workspace' | 'all' = 'all'): Promise<ModelProvider[]> => {
    const { data } = await apiClient.get<ModelProvider[]>('/model-providers', { params: { scope } });
    return data;
  },
  listCatalog: async (): Promise<ModelProvider[]> => {
    const { data } = await apiClient.get<ModelProvider[]>('/model-providers/catalog');
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
  probeRuntime: async (providerId: string, payload?: ProbeRuntimeRequest): Promise<ProbeRuntimeResult[]> => {
    const { data } = await apiClient.post<ProbeRuntimeResult[]>(`/model-providers/${providerId}/probe-runtime`, payload || {});
    return data;
  },
  probeRuntimeDraft: async (payload: ProbeRuntimeDraftRequest): Promise<ProbeRuntimeResult[]> => {
    const { data } = await apiClient.post<ProbeRuntimeResult[]>('/model-providers/probe-runtime', payload);
    return data;
  },
  importToWorkspace: async (id: string): Promise<ModelProvider> => {
    const { data } = await apiClient.post<{ source_provider_id: string; provider: ModelProvider }>(`/model-providers/${id}/import-to-workspace`);
    return data.provider;
  },
  delete: async (id: string): Promise<void> => {
    await apiClient.delete(`/model-providers/${id}`);
  },
};
