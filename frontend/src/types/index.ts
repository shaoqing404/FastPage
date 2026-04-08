export type ParseStatus = 'uploaded' | 'queued' | 'parsing' | 'index_ready' | 'failed';
export type RunStatus = 'accepted' | 'retrieving' | 'answering' | 'completed' | 'failed';

export interface User {
  id: string;
  tenant_id: string;
  username: string;
}

export interface ApiKey {
  id: string;
  tenant_id: string;
  name: string;
  key_prefix: string;
  status: string;
  created_by: string;
  last_used_at: string | null;
  revoked_at: string | null;
  created_at: string;
}

export interface ApiKeyCreateResponse extends ApiKey {
  api_key: string;
}

export interface ModelProvider {
  id: string;
  tenant_id: string;
  provider_type: string;
  name: string;
  base_url: string;
  default_model: string;
  supported_models: string[];
  extra_headers: Record<string, unknown>;
  enabled: boolean;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface Document {
  id: string;
  tenant_id: string;
  owner_user_id: string;
  display_name: string;
  source_filename: string;
  active_version_id: string | null;
  status: ParseStatus;
  created_at: string;
  updated_at: string;
}

export interface DocumentVersion {
  id: string;
  document_id: string;
  version_no: number;
  parse_status: ParseStatus;
  storage_path: string;
  file_hash: string;
  parsed_structure_path: string | null;
  parse_error: string | null;
  created_at: string;
}

export interface ParseJob {
  id: string;
  tenant_id: string;
  document_id: string;
  version_id: string;
  model: string;
  status: ParseStatus;
  current_step: string;
  progress_percent: number;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  error_message: string | null;
  created_at: string;
}

export interface ChatSkill {
  id: string;
  tenant_id: string;
  owner_user_id: string;
  name: string;
  description?: string | null;
  system_prompt: string;
  document_scope_type?: string;
  provider_id?: string | null;
  model: string;
  request_config: Record<string, unknown>;
  conversation_config: Record<string, unknown>;
  retrieval_config: Record<string, unknown>;
  generation_config: Record<string, unknown>;
  is_active?: boolean;
  created_at: string;
  updated_at: string;
  document_ids: string[];
}

export interface ChatSelectedSection {
  node_id?: string | null;
  title?: string | null;
  start_index?: number | null;
  end_index?: number | null;
}

export interface ChatRun {
  id: string;
  tenant_id: string;
  user_id: string;
  session_id: string | null;
  document_id: string | null;
  skill_id: string | null;
  provider_id: string | null;
  model: string;
  question: string;
  answer: string | null;
  answer_text: string | null;
  answer_with_marker: string | null;
  status: RunStatus;
  execution_context: {
    provider?: {
      id?: string | null;
      name?: string | null;
      type?: string | null;
    };
    model?: {
      resolved_model?: string | null;
    };
    conversation?: {
      query_rewrite_with_history?: boolean;
      include_history?: boolean;
      include_assistant_messages?: boolean;
      history_turn_limit?: number;
      history_token_budget?: number;
      history_used?: boolean;
      history_messages_used?: number;
      history_turns_used?: number;
      history_token_estimate?: number;
    };
    retrieval?: {
      query?: string;
      rewritten_query?: string | null;
      rewrite_applied?: boolean;
      top_k?: number;
      selection_mode?: string;
      max_context_pages?: number | null;
      max_context_tokens?: number | null;
    };
    generation?: {
      temperature?: number | null;
    };
  };
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  metrics: {
    retrieve_ms?: number;
    answer_ms?: number;
    total_ms?: number;
    ttft_ms?: number;
    input_tokens?: number;
    output_tokens?: number;
    total_tokens?: number;
    manual_count?: number;
    selected_section_count?: number;
    successful_llm_calls?: number;
  };
  selected_sections: ChatSelectedSection[];
  citations: Array<{
    node_id?: string | null;
    title?: string | null;
    page_start?: number | null;
    page_end?: number | null;
    snippet_id?: string | null;
  }>;
}

export interface ChatSession {
  id: string;
  tenant_id: string;
  user_id: string;
  skill_id: string | null;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ChatMessage {
  id: string;
  session_id: string;
  tenant_id: string;
  user_id: string;
  run_id: string | null;
  role: 'user' | 'assistant';
  content: string;
  sequence_no: number;
  created_at: string;
}

export interface MetricsOverview {
  documents: number;
  parse_jobs: number;
  chat_runs: number;
}
