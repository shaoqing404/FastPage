export type ParseStatus = 'uploaded' | 'queued' | 'parsing' | 'index_ready' | 'failed';
export type StandardRunStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
export type LegacyRunStatus = 'accepted' | 'retrieving' | 'answering';
export type RunStatus = StandardRunStatus | LegacyRunStatus;
export type ApiErrorDetails = Record<string, unknown> | unknown[];

export interface ValidationErrorDetail {
  type?: string;
  loc?: Array<string | number>;
  msg?: string;
  input?: unknown;
  ctx?: Record<string, unknown>;
}

export interface ApiErrorPayload {
  code: string;
  message: string;
  request_id: string | null;
  details?: ApiErrorDetails;
}

export interface ApiErrorEnvelope {
  error: ApiErrorPayload;
}

export interface WorkspaceContext {
  tenant_id: string;
  workspace_id: string | null;
  membership_role: string | null;
}

export type WorkspaceMembershipRole = 'founder' | 'admin' | 'member' | 'guest';
export type WorkspaceMembershipStatus = 'active' | 'disabled' | 'removed';
export type WorkspaceInviteRole = 'admin' | 'member' | 'guest';
export type WorkspaceInviteStatus = 'pending' | 'accepted' | 'expired' | 'revoked';
export type ResourceVisibility = 'private' | 'workspace_read' | 'workspace_edit';

export type WorkspaceCapabilityKey =
  | 'can_view_workspace'
  | 'can_edit_workspace_metadata'
  | 'can_manage_members'
  | 'can_manage_invites'
  | 'can_transfer_founder'
  | 'can_archive_workspace'
  | 'can_manage_api_keys'
  | 'can_manage_providers'
  | 'can_manage_knowledge_bases'
  | 'can_manage_skills'
  | 'can_run_skills'
  | 'can_view_runs';

export type WorkspacePermissions = Partial<Record<WorkspaceCapabilityKey, boolean>>;

export interface Workspace {
  id: string;
  tenant_id: string;
  name: string;
  slug: string;
  status: string;
  is_default: boolean;
  default_provider_id?: string | null;
  archived_at?: string | null;
  archived_by?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface WorkspaceCreateInput {
  name: string;
  slug?: string;
}

export interface TenantMembership {
  id: string;
  tenant_id: string;
  role: string;
  status: string;
}

export interface User extends WorkspaceContext {
  id: string;
  username: string;
  email: string | null;
  can_create_workspace: boolean;
  is_platform_admin: boolean;
  must_change_password?: boolean;
  membership_role: string | null;
  tenant_membership_role: string | null;
  tenant_membership_status: string | null;
  workspace_membership_role: WorkspaceMembershipRole | null;
  workspace_membership_status: WorkspaceMembershipStatus | null;
}

export interface WorkspaceMembership {
  id: string;
  workspace_id: string;
  user_id: string;
  role: WorkspaceMembershipRole;
  status: WorkspaceMembershipStatus;
  permissions_override: WorkspacePermissions;
  permissions: WorkspacePermissions;
}

export interface WorkspaceListItem extends Workspace {
  membership_id: string;
  membership_role: WorkspaceMembershipRole;
  membership_status: WorkspaceMembershipStatus;
  permissions: WorkspacePermissions;
  permissions_override: WorkspacePermissions;
  is_current: boolean;
}

export interface WorkspaceMember {
  id: string;
  workspace_id: string;
  user_id: string;
  email: string | null;
  role: WorkspaceMembershipRole;
  status: WorkspaceMembershipStatus;
  permissions_override: WorkspacePermissions;
  created_at: string;
  updated_at: string;
}

export interface WorkspaceInvite {
  id: string;
  workspace_id: string;
  email: string;
  role: WorkspaceInviteRole;
  status: WorkspaceInviteStatus;
  permissions_override: WorkspacePermissions;
  invited_by: string;
  accepted_user_id: string | null;
  expires_at: string;
  accepted_at: string | null;
  revoked_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AuthTokenResponse {
  access_token: string;
  token_type: string;
  user: User;
  workspace: Workspace;
  tenant_membership: TenantMembership;
  workspace_membership: WorkspaceMembership;
  memberships: TenantMembership[];
}

export interface WorkspaceInviteAcceptResponse {
  invite: WorkspaceInvite;
  access_token: string;
  token_type: string;
  user?: User;
  workspace: Workspace;
  tenant_membership: TenantMembership;
  workspace_membership: WorkspaceMembership;
}

export interface InvitePreviewResponse {
  valid: boolean;
  workspace_name: string;
  role: string;
  inviter_username: string;
  email_masked: string;
}

export interface InviteClaimRequest {
  password: string;
  username?: string;
}

export interface ChangePasswordRequest {
  current_password: string;
  new_password: string;
}

export interface ResetPasswordResponse {
  temporary_password: string;
}

export interface ApiKey {
  id: string;
  tenant_id: string;
  workspace_id: string | null;
  name: string;
  key_prefix: string;
  status: string;
  created_by: string;
  last_used_at: string | null;
  revoked_at: string | null;
  created_at: string;
}

export interface ApiKeyCreateResponse {
  id: string;
  tenant_id: string;
  workspace_id: string;
  name: string;
  key_prefix: string;
  status: string;
  created_at: string;
  api_key: string;
}

export interface ModelProviderEndpoint {
  id: string;
  provider_id: string;
  capability: 'chat' | 'embedding' | 'rerank';
  adapter: 'openai_chat' | 'openai_embedding' | 'generic_rerank' | 'dashscope_rerank';
  base_url: string;
  model: string;
  extra_headers: Record<string, unknown>;
  config: Record<string, unknown>;
  enabled: boolean;
  is_default: boolean;
  health_status: 'unknown' | 'healthy' | 'unhealthy';
  last_probe_at: string | null;
  last_probe_latency_ms: number | null;
  last_probe_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProbeRuntimeResult {
  capability: string;
  adapter: string;
  model: string;
  status: string;
  latency_ms: number | null;
  error_redacted: string | null;
  dimensions: number | null;
  sample_count: number | null;
}

export interface ModelProvider {
  id: string;
  tenant_id: string;
  workspace_id?: string | null;
  provider_type: string;
  name: string;
  base_url: string;
  default_model: string;
  supported_models: string[];
  extra_headers: Record<string, unknown>;
  enabled: boolean;
  is_default: boolean;
  managed_by_system: boolean;
  scope: 'tenant' | 'workspace' | 'system';
  share_mode: 'none' | 'all' | 'selected';
  shared_workspace_ids: string[];
  available_in_current_workspace: boolean;
  bindable_in_current_workspace: boolean;
  source_provider_id?: string | null;
  source_provider_name?: string | null;
  is_workspace_default_candidate: boolean;
  capabilities: {
    chat_models: string[];
    rerank_models: string[];
    default_rerank_model: string | null;
  };
  endpoints: ModelProviderEndpoint[];
  created_at: string;
  updated_at: string;
}

export interface Document {
  id: string;
  tenant_id: string;
  workspace_id: string | null;
  owner_user_id: string;
  uploaded_via_kb_id?: string | null;
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

export interface DocumentUploadResponse {
  document_id: string;
  version_id: string;
  status: ParseStatus;
}

export interface DocumentRestoreResponse {
  document_id: string;
  active_version_id: string;
}

export interface ParseJob {
  id: string;
  tenant_id: string;
  workspace_id: string | null;
  document_id: string;
  version_id: string;
  model: string | null;
  status: ParseStatus;
  current_step: string | null;
  progress_percent: number;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  error_message: string | null;
  created_at: string;
}

export interface KnowledgeBaseRetrievalProfile extends Record<string, unknown> {
  mode?: string;
  per_document_top_k?: number;
  global_top_k?: number;
}

export interface KnowledgeBaseDocumentMembership {
  document_id: string;
  pinned_version_id: string | null;
  enabled: boolean;
  label: string | null;
  sort_order: number;
  document_display_name?: string | null;
  document_source_filename?: string | null;
  document_status?: ParseStatus | null;
}

export interface KnowledgeBaseDocumentMembershipInput {
  document_id: string;
  pinned_version_id?: string | null;
  enabled?: boolean;
  label?: string | null;
  sort_order?: number;
}

export interface KnowledgeBaseDocumentMembershipUpdate {
  pinned_version_id?: string | null;
  enabled?: boolean;
  label?: string | null;
  sort_order?: number;
}

export interface KnowledgeBase {
  id: string;
  tenant_id: string;
  workspace_id: string;
  name: string;
  description: string | null;
  status: string;
  visibility: ResourceVisibility;
  retrieval_profile: KnowledgeBaseRetrievalProfile;
  created_by: string;
  created_at: string;
  updated_at: string;
  documents: KnowledgeBaseDocumentMembership[];
}

export interface KnowledgeBaseCreateInput {
  name: string;
  description?: string | null;
  status?: string;
  visibility?: ResourceVisibility;
  retrieval_profile?: KnowledgeBaseRetrievalProfile;
  documents?: KnowledgeBaseDocumentMembershipInput[];
}

export interface KnowledgeBaseUpdateInput {
  name?: string;
  description?: string | null;
  status?: string;
  visibility?: ResourceVisibility;
  retrieval_profile?: KnowledgeBaseRetrievalProfile;
}

export type ComplianceTargetMode = 'knowledge_base';
export type ComplianceRunMode = 'single_manual' | 'multi_manual_federated' | (string & {});
export type ComplianceDefaultVerdict = 'pass' | 'fail' | 'inconclusive' | 'not_applicable';
export type ComplianceVerdict = ComplianceDefaultVerdict | (string & {});
export type ComplianceCheckStatus = 'active' | 'disabled' | (string & {});
export type ComplianceRunRawStatus =
  | 'accepted'
  | 'retrieving'
  | 'answering'
  | StandardRunStatus
  | (string & {});

export interface ComplianceTarget {
  mode: ComplianceTargetMode;
  knowledge_base_id: string;
}

export interface ComplianceVerdictPolicy {
  allowed_values: ComplianceVerdict[];
  default_on_gap: ComplianceVerdict;
}

export interface ComplianceOutputConfig {
  include_summary: boolean;
  include_answer: boolean;
  include_evidence: boolean;
  include_gaps: boolean;
  include_conflicts: boolean;
}

export interface ComplianceRetrievalConfig {
  per_document_top_k: number;
  global_top_k: number;
  selection_mode: 'outline_llm' | 'lexical_fallback' | (string & {});
  rerank_mode: 'auto' | 'off' | 'provider' | 'system' | (string & {});
  max_context_pages: number | null;
  max_context_tokens: number | null;
}

export interface ComplianceGenerationConfig {
  temperature: number | null;
}

export interface ComplianceRunInput {
  question: string;
  facts: Record<string, unknown>;
}

export interface ComplianceCitation {
  citation_id: string;
  knowledge_base_id: string;
  document_id: string;
  version_id: string;
  node_id: string | null;
  page_start: number | null;
  page_end: number | null;
  title: string | null;
  snippet_id: string;
  document_label: string | null;
  version_label: string | null;
  source_label: string;
  page_label: string | null;
}

export type ComplianceProvenance = ComplianceCitation[];

export interface ComplianceEvidence {
  evidence_id: string;
  kind: string;
  statement: string;
  citation_ids: string[];
  citation_count: number;
  provenance: ComplianceProvenance;
  source_count: number;
}

export interface ComplianceGap {
  gap_id: string;
  type: string;
  statement: string;
  severity: string;
  related_citation_ids: string[];
}

export interface ComplianceConflict {
  conflict_id: string;
  type: string;
  summary: string;
  citation_ids: string[];
  resolution_status: string;
}

export interface ComplianceResolvedManual {
  document_id: string;
  version_id: string;
  label: string | null;
  version_label: string | null;
}

export interface ComplianceExecutionContextTarget {
  requested_mode: ComplianceTargetMode | (string & {}) | null;
  resolved_mode: ComplianceRunMode | null;
  knowledge_base_id: string | null;
}

export interface ComplianceExecutionContextRetrieval {
  per_document_top_k: number | null;
  global_top_k: number | null;
  selection_mode: string | null;
  rerank_mode?: string | null;
  rerank_resolved_mode?: string | null;
  documents_considered: number | null;
  documents_with_hits: number | null;
}

export interface ComplianceExecutionContextMerge {
  strategy: string | null;
  candidate_count: number | null;
  selected_citation_count: number | null;
}

export interface ComplianceExecutionContextGeneration {
  provider_id: string | null;
  model: string | null;
  temperature: number | null;
}

export interface ComplianceRunExecutionContext extends Record<string, unknown> {
  workspace_id: string | null;
  target: ComplianceExecutionContextTarget;
  resolved_manuals: ComplianceResolvedManual[];
  retrieval: ComplianceExecutionContextRetrieval;
  merge: ComplianceExecutionContextMerge;
  generation: ComplianceExecutionContextGeneration;
}

export interface ComplianceRunMetricsError {
  code: string | null;
  message: string | null;
}

export interface ComplianceRunMetrics extends Record<string, unknown> {
  retrieve_ms: number | null;
  merge_ms: number | null;
  answer_ms: number | null;
  total_ms: number | null;
  manual_count: number | null;
  documents_considered: number | null;
  documents_with_hits: number | null;
  global_selected_section_count: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  successful_llm_calls: number | null;
  error: ComplianceRunMetricsError | null;
}

export interface ComplianceStructuredResult {
  summary: string | null;
  answer: string | null;
  verdict: ComplianceVerdict | null;
  confidence: number | null;
  citations: ComplianceCitation[];
  citations_by_id: Record<string, ComplianceCitation>;
  evidence: ComplianceEvidence[];
  gaps: ComplianceGap[];
  conflicts: ComplianceConflict[];
  evidence_count: number;
  gap_count: number;
  conflict_count: number;
  has_evidence: boolean;
  has_gaps: boolean;
  has_conflicts: boolean;
}

export interface ComplianceCheck {
  id: string;
  tenant_id: string;
  workspace_id: string;
  name: string;
  description: string | null;
  status: ComplianceCheckStatus;
  target: ComplianceTarget;
  query_template: string;
  instructions: string | null;
  verdict_policy: ComplianceVerdictPolicy;
  output_config: ComplianceOutputConfig;
  retrieval_config: ComplianceRetrievalConfig;
  generation_config: ComplianceGenerationConfig;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface ComplianceCheckCreateInput {
  name: string;
  description?: string | null;
  status?: ComplianceCheckStatus;
  target: ComplianceTarget;
  query_template: string;
  instructions?: string | null;
  verdict_policy?: Partial<ComplianceVerdictPolicy>;
  output_config?: Partial<ComplianceOutputConfig>;
  retrieval_config?: Partial<ComplianceRetrievalConfig>;
  generation_config?: Partial<ComplianceGenerationConfig>;
}

export interface ComplianceCheckUpdateInput {
  name?: string;
  description?: string | null;
  status?: ComplianceCheckStatus;
  target?: ComplianceTarget;
  query_template?: string;
  instructions?: string | null;
  verdict_policy?: Partial<ComplianceVerdictPolicy>;
  output_config?: Partial<ComplianceOutputConfig>;
  retrieval_config?: Partial<ComplianceRetrievalConfig>;
  generation_config?: Partial<ComplianceGenerationConfig>;
}

export interface ComplianceRunCreateInput {
  execution_mode?: 'async';
  input: ComplianceRunInput;
  target: ComplianceTarget;
  instructions?: string | null;
  verdict_policy?: Partial<ComplianceVerdictPolicy>;
  output_config?: Partial<ComplianceOutputConfig>;
  retrieval_config?: Partial<ComplianceRetrievalConfig>;
  generation_config?: Partial<ComplianceGenerationConfig>;
  provider_id?: string | null;
  model?: string | null;
}

export interface ComplianceRunFromCheckCreateInput {
  execution_mode?: 'async';
  input: ComplianceRunInput;
  provider_id?: string | null;
  model?: string | null;
  instructions?: string | null;
  verdict_policy?: Partial<ComplianceVerdictPolicy>;
  output_config?: Partial<ComplianceOutputConfig>;
  retrieval_config?: Partial<ComplianceRetrievalConfig>;
  generation_config?: Partial<ComplianceGenerationConfig>;
}

export interface ComplianceRunListParams {
  status?: ComplianceRunRawStatus | string;
  compliance_check_id?: string;
  mode?: ComplianceRunMode | string;
  created_after?: string | Date;
  created_before?: string | Date;
}

export interface ComplianceRunError {
  code: string | null;
  message: string | null;
  details?: Record<string, unknown> | null;
}

export interface ComplianceRun {
  id: string;
  tenant_id: string;
  workspace_id: string;
  user_id: string;
  compliance_check_id: string | null;
  target: ComplianceTarget;
  status: StandardRunStatus;
  raw_status: ComplianceRunRawStatus | null;
  mode: ComplianceRunMode;
  provider_id: string | null;
  model: string;
  input: ComplianceRunInput;
  summary: string | null;
  answer: string | null;
  verdict: ComplianceVerdict | null;
  confidence: number | null;
  citations: ComplianceCitation[];
  evidence: ComplianceEvidence[];
  gaps: ComplianceGap[];
  conflicts: ComplianceConflict[];
  execution_context: ComplianceRunExecutionContext;
  metrics: ComplianceRunMetrics;
  error: ComplianceRunError | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  result: ComplianceStructuredResult;
}

export interface ChatSkill {
  id: string;
  tenant_id: string;
  workspace_id: string | null;
  owner_user_id: string;
  name: string;
  description?: string | null;
  system_prompt: string;
  document_scope_type?: string;
  knowledge_base_id?: string | null;
  provider_id?: string | null;
  model: string;
  request_config: Record<string, unknown>;
  conversation_config: Record<string, unknown>;
  retrieval_config: Record<string, unknown>;
  generation_config: Record<string, unknown>;
  is_active?: boolean;
  visibility: ResourceVisibility;
  created_at: string;
  updated_at: string;
  document_ids: string[];
}

export interface ChatSkillMutationInput {
  name: string;
  description?: string | null;
  system_prompt: string;
  document_ids?: string[];
  knowledge_base_id?: string | null;
  provider_id?: string | null;
  model: string;
  request_config?: Record<string, unknown>;
  conversation_config?: Record<string, unknown>;
  retrieval_config?: Record<string, unknown>;
  generation_config?: Record<string, unknown>;
  document_scope_type?: string;
  visibility?: ResourceVisibility;
  is_active?: boolean;
}

export type ChatSkillCreateInput = Omit<ChatSkillMutationInput, 'is_active'>;
export type ChatSkillUpdateInput = Partial<ChatSkillMutationInput>;

export interface ChatSelectedSection extends Record<string, unknown> {
  node_id?: string | null;
  title?: string | null;
  start_index?: number | null;
  end_index?: number | null;
}

export interface ChatCitation extends Record<string, unknown> {
  knowledge_base_id?: string | null;
  document_id?: string | null;
  version_id?: string | null;
  node_id?: string | null;
  title?: string | null;
  page_start?: number | null;
  page_end?: number | null;
  snippet_id?: string | null;
}

export interface ChatRunExecutionContext extends Record<string, unknown> {
  provider?: {
    id?: string | null;
    name?: string | null;
    type?: string | null;
    scope?: string | null;
    resolution_source?: string | null;
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
    candidate_top_k?: number;
    selection_mode?: string;
    query_rewrite_strategy?: string;
    outline_selection_strategy?: string | null;
    max_context_pages?: number | null;
    max_context_tokens?: number | null;
    documents_considered?: number | null;
    documents_with_hits?: number | null;
    rerank_mode?: string | null;
    rerank_resolved_mode?: string | null;
    rerank_applied?: boolean;
    rerank_model?: string | null;
    rerank_provider_source?: string | null;
    warnings?: string[];
  };
  generation?: {
    temperature?: number | null;
  };
  target?: {
    requested_mode?: string | null;
    resolved_mode?: string | null;
    knowledge_base_id?: string | null;
  };
  resolved_manuals?: Array<{
    document_id?: string | null;
    version_id?: string | null;
    label?: string | null;
    version_label?: string | null;
  }>;
  merge?: {
    strategy?: string | null;
    candidate_count?: number | null;
    selected_citation_count?: number | null;
  };
}

export interface ChatRunMetrics extends Record<string, unknown> {
  queue_ms?: number;
  retrieve_ms?: number;
  answer_ms?: number;
  total_ms?: number;
  wall_clock_ms?: number;
  ttft_ms?: number;
  answer_pre_provider_ms?: number;
  provider_stream_open_ms?: number;
  provider_first_chunk_ms?: number;
  provider_ttft_ms?: number;
  provider_first_delta_after_first_chunk_ms?: number;
  provider_stream_ms?: number;
  first_delta_to_stream_end_ms?: number;
  heartbeat_drain_ms?: number;
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
  manual_count?: number;
  selected_section_count?: number;
  documents_considered?: number;
  documents_with_hits?: number;
  citations_count?: number;
  successful_llm_calls?: number;
}

export interface RunObservationEvent {
  id: string;
  run_kind: 'chat' | 'compliance';
  run_id: string;
  sequence_no: number;
  event_type: string;
  step: string | null;
  status: string | null;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface RunObservationSnapshot {
  run_kind: 'chat' | 'compliance';
  run_id: string;
  status: string;
  current_step: string | null;
  worker_node_code: string | null;
  queue: Record<string, unknown>;
  timings: Record<string, unknown>;
  execution_context: Record<string, unknown>;
  partial_answer: string | null;
  events: RunObservationEvent[];
}

export interface ChatRun {
  id: string;
  tenant_id: string;
  workspace_id: string | null;
  user_id: string;
  session_id: string | null;
  document_id: string | null;
  version_id: string | null;
  skill_id: string | null;
  provider_id: string | null;
  model: string;
  question: string;
  answer: string | null;
  answer_text: string | null;
  answer_with_marker: string | null;
  status: StandardRunStatus;
  raw_status: RunStatus | null;
  cancel_requested: boolean;
  cancel_reason: string | null;
  execution_context: ChatRunExecutionContext;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  metrics: ChatRunMetrics;
  selected_sections: ChatSelectedSection[];
  citations: ChatCitation[];
  last_error: string | null;
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

// ---------------------------------------------------------------------------
// Platform admin types (mirrors app/schemas/platform.py)
// ---------------------------------------------------------------------------

export interface PlatformTenantMembership {
  id: string;
  tenant_id: string;
  tenant_name: string;
  role: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface PlatformWorkspaceMembership {
  id: string;
  workspace_id: string;
  workspace_name: string;
  workspace_slug: string;
  tenant_id: string;
  tenant_name: string;
  role: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface PlatformUserListItem {
  id: string;
  tenant_id: string;
  username: string;
  email: string | null;
  is_active: boolean;
  can_create_workspace: boolean;
  is_platform_admin: boolean;
  tenant_membership_count: number;
  workspace_membership_count: number;
  created_at: string;
  updated_at: string;
}

export interface PlatformUserDetail extends PlatformUserListItem {
  tenant_memberships: PlatformTenantMembership[];
  workspace_memberships: PlatformWorkspaceMembership[];
}

export interface PlatformUserUpdateInput {
  is_active?: boolean;
  can_create_workspace?: boolean;
  is_platform_admin?: boolean;
}

export interface PlatformWorkspaceMemberOverview {
  id: string;
  user_id: string;
  username: string;
  email: string | null;
  role: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface PlatformWorkspaceListItem {
  id: string;
  tenant_id: string;
  tenant_name: string;
  name: string;
  slug: string;
  status: string;
  is_default: boolean;
  archived_at: string | null;
  archived_by: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  founder_user_id: string | null;
  founder_username: string | null;
  founder_email: string | null;
  member_count: number;
  active_member_count: number;
}

export interface PlatformWorkspaceDetail extends PlatformWorkspaceListItem {
  members: PlatformWorkspaceMemberOverview[];
}

export interface PlatformTenantListItem {
  id: string;
  name: string;
  status: string;
  created_at: string;
  user_count: number;
  workspace_count: number;
}

export interface PlatformTenantUserOverview {
  id: string;
  user_id: string;
  username: string;
  email: string | null;
  role: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface PlatformTenantWorkspaceOverview {
  id: string;
  name: string;
  slug: string;
  status: string;
  is_default: boolean;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface PlatformTenantDetail extends PlatformTenantListItem {
  users: PlatformTenantUserOverview[];
  workspaces: PlatformTenantWorkspaceOverview[];
}

export interface PlatformUserFlags {
  is_active: boolean;
  can_create_workspace: boolean;
  is_platform_admin: boolean;
  must_change_password: boolean;
}

export interface PlatformRequestedContext {
  tenant_id: string | null;
  workspace_id: string | null;
}

export interface PlatformResolvedContext {
  tenant_id: string | null;
  workspace_id: string | null;
  source: string;
}

export interface PlatformEffectiveTenantMembership {
  id: string | null;
  tenant_id: string | null;
  role: string | null;
  status: string | null;
}

export interface PlatformEffectiveWorkspaceMembership {
  id: string | null;
  workspace_id: string | null;
  user_id: string | null;
  role: string | null;
  status: string | null;
  permissions_override: WorkspacePermissions;
  effective_permissions: WorkspacePermissions;
}

export interface PlatformEffectivePermissions {
  can_access_platform_control_plane: boolean;
  can_create_workspace: boolean;
}

export interface PlatformExplainability {
  allowed_reasons: string[];
  denied_reasons: string[];
}

export interface PlatformResourceRule {
  scope: string;
  explanation: string;
  counts: Record<string, number>;
}

export interface PlatformUserAccessPortraitUser {
  id: string;
  username: string;
  email: string | null;
  flags: PlatformUserFlags;
  compat_tenant_id: string | null;
}

export interface PlatformUserRawMemberships {
  tenant_memberships: PlatformTenantMembership[];
  workspace_memberships: PlatformWorkspaceMembership[];
}

export interface PlatformUserEffectivePortrait {
  requested_context: PlatformRequestedContext;
  resolved_context: PlatformResolvedContext | null;
  tenant_membership: PlatformEffectiveTenantMembership;
  workspace_membership: PlatformEffectiveWorkspaceMembership;
  platform_permissions: PlatformEffectivePermissions;
  explainability: PlatformExplainability;
}

export interface PlatformUserAccessPortrait {
  user: PlatformUserAccessPortraitUser;
  raw_memberships: PlatformUserRawMemberships;
  effective_portrait: PlatformUserEffectivePortrait;
  resource_rules: Record<string, PlatformResourceRule>;
}

export interface PlatformWorkspaceFounder {
  membership_id: string | null;
  user_id: string | null;
  username: string | null;
  email: string | null;
}

export interface PlatformWorkspaceMembershipSummary {
  total: number;
  active: number;
  by_role: Record<string, number>;
  active_founder_invariant_ok: boolean;
}

export interface PlatformWorkspacePortraitMember {
  id: string;
  user_id: string;
  username: string;
  email: string | null;
  role: string;
  status: string;
  permissions_override: WorkspacePermissions;
  effective_permissions: WorkspacePermissions;
  created_at: string;
  updated_at: string;
}

export interface PlatformWorkspaceInviteSummary {
  pending: number;
  accepted: number;
  expired: number;
  revoked: number;
}

export interface PlatformWorkspaceArchiveState {
  status: string;
  archived_at: string | null;
  archived_by: string | null;
}

export interface PlatformWorkspaceAccessPortrait {
  workspace: Pick<PlatformWorkspaceListItem, 'id' | 'tenant_id' | 'name' | 'slug' | 'status' | 'is_default'>;
  tenant: Pick<PlatformTenantListItem, 'id' | 'name' | 'status'>;
  founder: PlatformWorkspaceFounder;
  membership_summary: PlatformWorkspaceMembershipSummary;
  members: PlatformWorkspacePortraitMember[];
  invite_summary: PlatformWorkspaceInviteSummary;
  resource_scope: Record<string, PlatformResourceRule>;
  archive_state: PlatformWorkspaceArchiveState;
}
