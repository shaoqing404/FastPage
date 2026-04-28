import { apiClient } from '../../lib/api/client';

export interface FastSearchRequest {
  document_id: string;
  version_id: string;
  query: string;
  node_top_k?: number;
  include_snippets?: boolean;
  allow_runtime_pdf_fallback?: boolean;
}

export interface FastSearchNode {
  node_id: string;
  title: string | null;
  page_start: number | null;
  page_end: number | null;
  score: number;
  source: string;
  snippet: string | null;
  summary: string | null;
}

export interface FastSearchResponse {
  mode: string;
  node_top_k: number;
  latency_ms: number;
  server_total_latency_ms?: number | null;
  corpus_load_latency_ms?: number | null;
  content_enrich_latency_ms?: number | null;
  dense_search_latency_ms?: number | null;
  node_score_latency_ms?: number | null;
  legacy_node_shadow_latency_ms?: number | null;
  nodes: FastSearchNode[];
  boundary_flags: string[];
  fallback_recommendation: string | null;
  active_backend?: string | null;
  fallback_reason?: string | null;
  requested_dense_source?: string | null;
  dense_source?: string | null;
  query_embedding_computed?: boolean;
  query_embedding_dimensions?: number | null;
  artifact_count?: number | null;
  artifact_exact_scan_executed?: boolean;
  es_executed?: boolean;
  section_text_participated?: boolean;
  section_text_node_count?: number;
  section_text_source?: string | null;
  section_text_degraded_reason?: string | null;
  runtime_pdf_fallback_allowed?: boolean;
}

export const searchApi = {
  fastSearch: async (payload: FastSearchRequest): Promise<FastSearchResponse> => {
    const { data } = await apiClient.post<FastSearchResponse>('/search/fast', payload);
    return data;
  },
};
