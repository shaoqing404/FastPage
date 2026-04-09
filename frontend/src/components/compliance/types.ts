import type { ComplianceCheckStatus, ComplianceVerdict } from '../../features/compliance/types';

export const DEFAULT_COMPLIANCE_VERDICTS: ComplianceVerdict[] = ['pass', 'fail', 'inconclusive', 'not_applicable'];

export interface ComplianceCheckDraft {
  name: string;
  description: string;
  status: ComplianceCheckStatus;
  knowledge_base_id: string;
  query_template: string;
  instructions: string;
  allowed_values: ComplianceVerdict[];
  default_on_gap: ComplianceVerdict;
  include_summary: boolean;
  include_answer: boolean;
  include_evidence: boolean;
  include_gaps: boolean;
  include_conflicts: boolean;
  per_document_top_k: string;
  global_top_k: string;
  selection_mode: 'outline_llm' | 'lexical_fallback';
  max_context_pages: string;
  max_context_tokens: string;
  temperature: string;
}
