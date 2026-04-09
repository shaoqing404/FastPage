import type {
  ComplianceCheck,
  ComplianceCitation,
  ComplianceConflict,
  ComplianceEvidence,
  ComplianceExecutionContextGeneration,
  ComplianceExecutionContextMerge,
  ComplianceExecutionContextRetrieval,
  ComplianceExecutionContextTarget,
  ComplianceGap,
  ComplianceGenerationConfig,
  ComplianceOutputConfig,
  ComplianceResolvedManual,
  ComplianceRetrievalConfig,
  ComplianceRun,
  ComplianceRunError,
  ComplianceRunExecutionContext,
  ComplianceRunMetrics,
  ComplianceRunMetricsError,
  ComplianceRunRawStatus,
  ComplianceRunInput,
  ComplianceStructuredResult,
  ComplianceTarget,
  ComplianceVerdict,
  ComplianceVerdictPolicy,
  StandardRunStatus,
} from '../../types';

const DEFAULT_VERDICT_POLICY: ComplianceVerdictPolicy = {
  allowed_values: ['pass', 'fail', 'inconclusive', 'not_applicable'],
  default_on_gap: 'inconclusive',
};

const DEFAULT_OUTPUT_CONFIG: ComplianceOutputConfig = {
  include_summary: true,
  include_answer: true,
  include_evidence: true,
  include_gaps: true,
  include_conflicts: true,
};

const DEFAULT_RETRIEVAL_CONFIG: ComplianceRetrievalConfig = {
  per_document_top_k: 5,
  global_top_k: 8,
  selection_mode: 'outline_llm',
  max_context_pages: 20,
  max_context_tokens: 12000,
};

const DEFAULT_GENERATION_CONFIG: ComplianceGenerationConfig = {
  temperature: 0,
};

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null;

const toStringOrNull = (value: unknown): string | null => {
  if (typeof value !== 'string') return null;
  const normalized = value.trim();
  return normalized ? normalized : null;
};

const toStringOrFallback = (value: unknown, fallback: string): string => toStringOrNull(value) ?? fallback;

const toNumberOrNull = (value: unknown): number | null => {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value !== 'string') return null;
  const normalized = Number(value);
  return Number.isFinite(normalized) ? normalized : null;
};

const toStringArray = (value: unknown): string[] =>
  Array.isArray(value)
    ? value.map((item) => toStringOrNull(item)).filter((item): item is string => Boolean(item))
    : [];

const formatPageLabel = (pageStart: number | null, pageEnd: number | null) => {
  if (pageStart === null && pageEnd === null) return null;
  if (pageStart !== null && pageEnd !== null) {
    return pageStart === pageEnd ? `p. ${pageStart}` : `pp. ${pageStart}-${pageEnd}`;
  }
  return `p. ${pageStart ?? pageEnd}`;
};

const normalizeTarget = (value: unknown, fallbackKnowledgeBaseId?: string | null): ComplianceTarget => {
  const record = isRecord(value) ? value : {};
  return {
    mode: 'knowledge_base',
    knowledge_base_id: toStringOrFallback(record.knowledge_base_id, fallbackKnowledgeBaseId ?? ''),
  };
};

const normalizeVerdictPolicy = (value: unknown): ComplianceVerdictPolicy => {
  const record = isRecord(value) ? value : {};
  const allowedValues = toStringArray(record.allowed_values) as ComplianceVerdict[];
  const defaultOnGap = toStringOrNull(record.default_on_gap) as ComplianceVerdict | null;
  return {
    allowed_values: allowedValues.length > 0 ? allowedValues : DEFAULT_VERDICT_POLICY.allowed_values,
    default_on_gap: defaultOnGap ?? DEFAULT_VERDICT_POLICY.default_on_gap,
  };
};

const normalizeOutputConfig = (value: unknown): ComplianceOutputConfig => {
  const record = isRecord(value) ? value : {};
  return {
    include_summary: record.include_summary === undefined ? DEFAULT_OUTPUT_CONFIG.include_summary : Boolean(record.include_summary),
    include_answer: record.include_answer === undefined ? DEFAULT_OUTPUT_CONFIG.include_answer : Boolean(record.include_answer),
    include_evidence: record.include_evidence === undefined ? DEFAULT_OUTPUT_CONFIG.include_evidence : Boolean(record.include_evidence),
    include_gaps: record.include_gaps === undefined ? DEFAULT_OUTPUT_CONFIG.include_gaps : Boolean(record.include_gaps),
    include_conflicts: record.include_conflicts === undefined ? DEFAULT_OUTPUT_CONFIG.include_conflicts : Boolean(record.include_conflicts),
  };
};

const normalizeRetrievalConfig = (value: unknown): ComplianceRetrievalConfig => {
  const record = isRecord(value) ? value : {};
  return {
    per_document_top_k: toNumberOrNull(record.per_document_top_k) ?? DEFAULT_RETRIEVAL_CONFIG.per_document_top_k,
    global_top_k: toNumberOrNull(record.global_top_k) ?? DEFAULT_RETRIEVAL_CONFIG.global_top_k,
    selection_mode: toStringOrFallback(record.selection_mode, DEFAULT_RETRIEVAL_CONFIG.selection_mode),
    max_context_pages: record.max_context_pages === null ? null : (toNumberOrNull(record.max_context_pages) ?? DEFAULT_RETRIEVAL_CONFIG.max_context_pages),
    max_context_tokens:
      record.max_context_tokens === null ? null : (toNumberOrNull(record.max_context_tokens) ?? DEFAULT_RETRIEVAL_CONFIG.max_context_tokens),
  };
};

const normalizeGenerationConfig = (value: unknown): ComplianceGenerationConfig => {
  const record = isRecord(value) ? value : {};
  return {
    temperature: record.temperature === null ? null : (toNumberOrNull(record.temperature) ?? DEFAULT_GENERATION_CONFIG.temperature),
  };
};

const normalizeRunInput = (value: unknown): ComplianceRunInput => {
  const record = isRecord(value) ? value : {};
  return {
    question: toStringOrFallback(record.question, ''),
    facts: isRecord(record.facts) ? record.facts : {},
  };
};

const normalizeCitation = (value: unknown, index: number, fallbackKnowledgeBaseId: string): ComplianceCitation => {
  const record = isRecord(value) ? value : {};
  const documentLabel = toStringOrNull(record.document_label);
  const versionLabel = toStringOrNull(record.version_label);
  const documentId = toStringOrFallback(record.document_id, '');
  const sourceBaseLabel = documentLabel ?? documentId;
  const sourceLabel = versionLabel ? `${sourceBaseLabel} (${versionLabel})` : sourceBaseLabel;
  const pageStart = toNumberOrNull(record.page_start);
  const pageEnd = toNumberOrNull(record.page_end);

  return {
    citation_id: toStringOrFallback(record.citation_id, `cit_${index + 1}`),
    knowledge_base_id: toStringOrFallback(record.knowledge_base_id, fallbackKnowledgeBaseId),
    document_id: documentId,
    version_id: toStringOrFallback(record.version_id, ''),
    node_id: toStringOrNull(record.node_id),
    page_start: pageStart,
    page_end: pageEnd,
    title: toStringOrNull(record.title),
    snippet_id: toStringOrFallback(record.snippet_id, `${documentId}:${index + 1}`),
    document_label: documentLabel,
    version_label: versionLabel,
    source_label: sourceLabel,
    page_label: formatPageLabel(pageStart, pageEnd),
  };
};

const normalizeCitations = (value: unknown, fallbackKnowledgeBaseId: string): ComplianceCitation[] =>
  Array.isArray(value) ? value.map((item, index) => normalizeCitation(item, index, fallbackKnowledgeBaseId)) : [];

const normalizeEvidence = (
  value: unknown,
  citationsById: Record<string, ComplianceCitation>,
): ComplianceEvidence[] => {
  if (!Array.isArray(value)) return [];

  return value
    .map((item, index) => {
      const record = isRecord(item) ? item : {};
      const citationIds = toStringArray(record.citation_ids).filter((citationId) => Boolean(citationsById[citationId]));
      const explicitProvenance = normalizeCitations(record.provenance, '');
      const provenance =
        explicitProvenance.length > 0
          ? explicitProvenance.map((citation) => citationsById[citation.citation_id] ?? citation)
          : citationIds.map((citationId) => citationsById[citationId]).filter((citation): citation is ComplianceCitation => Boolean(citation));
      const effectiveCitationIds = citationIds.length > 0 ? citationIds : provenance.map((citation) => citation.citation_id);
      const statement = toStringOrNull(record.statement);

      if (!statement) return null;

      return {
        evidence_id: toStringOrFallback(record.evidence_id, `ev_${index + 1}`),
        kind: toStringOrFallback(record.kind, 'supporting'),
        statement,
        citation_ids: effectiveCitationIds,
        citation_count: effectiveCitationIds.length,
        provenance,
        source_count: toNumberOrNull(record.source_count) ?? provenance.length,
      };
    })
    .filter((item): item is ComplianceEvidence => Boolean(item));
};

const normalizeGaps = (value: unknown): ComplianceGap[] => {
  if (!Array.isArray(value)) return [];

  return value
    .map((item, index) => {
      const record = isRecord(item) ? item : {};
      const statement = toStringOrNull(record.statement);
      if (!statement) return null;

      return {
        gap_id: toStringOrFallback(record.gap_id, `gap_${index + 1}`),
        type: toStringOrFallback(record.type, 'insufficient_evidence'),
        statement,
        severity: toStringOrFallback(record.severity, 'medium'),
        related_citation_ids: toStringArray(record.related_citation_ids),
      };
    })
    .filter((item): item is ComplianceGap => Boolean(item));
};

const normalizeConflicts = (value: unknown): ComplianceConflict[] => {
  if (!Array.isArray(value)) return [];

  return value
    .map((item, index) => {
      const record = isRecord(item) ? item : {};
      const summary = toStringOrNull(record.summary);
      if (!summary) return null;

      return {
        conflict_id: toStringOrFallback(record.conflict_id, `conf_${index + 1}`),
        type: toStringOrFallback(record.type, 'interpretation_conflict'),
        summary,
        citation_ids: toStringArray(record.citation_ids),
        resolution_status: toStringOrFallback(record.resolution_status, 'unresolved'),
      };
    })
    .filter((item): item is ComplianceConflict => Boolean(item));
};

const normalizeExecutionContextTarget = (value: unknown, fallbackKnowledgeBaseId: string): ComplianceExecutionContextTarget => {
  const record = isRecord(value) ? value : {};
  return {
    requested_mode: (toStringOrNull(record.requested_mode) ?? 'knowledge_base') as ComplianceExecutionContextTarget['requested_mode'],
    resolved_mode: (toStringOrNull(record.resolved_mode) ?? null) as ComplianceExecutionContextTarget['resolved_mode'],
    knowledge_base_id: toStringOrNull(record.knowledge_base_id) ?? fallbackKnowledgeBaseId,
  };
};

const normalizeResolvedManuals = (value: unknown): ComplianceResolvedManual[] =>
  Array.isArray(value)
    ? value.map((item) => {
        const record = isRecord(item) ? item : {};
        return {
          document_id: toStringOrFallback(record.document_id, ''),
          version_id: toStringOrFallback(record.version_id, ''),
          label: toStringOrNull(record.label),
          version_label: toStringOrNull(record.version_label),
        };
      })
    : [];

const normalizeExecutionContextRetrieval = (value: unknown): ComplianceExecutionContextRetrieval => {
  const record = isRecord(value) ? value : {};
  return {
    per_document_top_k: toNumberOrNull(record.per_document_top_k),
    global_top_k: toNumberOrNull(record.global_top_k),
    selection_mode: toStringOrNull(record.selection_mode),
    documents_considered: toNumberOrNull(record.documents_considered),
    documents_with_hits: toNumberOrNull(record.documents_with_hits),
  };
};

const normalizeExecutionContextMerge = (value: unknown): ComplianceExecutionContextMerge => {
  const record = isRecord(value) ? value : {};
  return {
    strategy: toStringOrNull(record.strategy),
    candidate_count: toNumberOrNull(record.candidate_count),
    selected_citation_count: toNumberOrNull(record.selected_citation_count),
  };
};

const normalizeExecutionContextGeneration = (value: unknown): ComplianceExecutionContextGeneration => {
  const record = isRecord(value) ? value : {};
  return {
    provider_id: toStringOrNull(record.provider_id),
    model: toStringOrNull(record.model),
    temperature: toNumberOrNull(record.temperature),
  };
};

const normalizeExecutionContext = (value: unknown, fallbackKnowledgeBaseId: string): ComplianceRunExecutionContext => {
  const record = isRecord(value) ? value : {};
  return {
    ...record,
    workspace_id: toStringOrNull(record.workspace_id),
    target: normalizeExecutionContextTarget(record.target, fallbackKnowledgeBaseId),
    resolved_manuals: normalizeResolvedManuals(record.resolved_manuals),
    retrieval: normalizeExecutionContextRetrieval(record.retrieval),
    merge: normalizeExecutionContextMerge(record.merge),
    generation: normalizeExecutionContextGeneration(record.generation),
  };
};

const normalizeMetricsError = (value: unknown): ComplianceRunMetricsError | null => {
  if (!isRecord(value)) return null;
  return {
    code: toStringOrNull(value.code),
    message: toStringOrNull(value.message),
  };
};

const normalizeMetrics = (value: unknown): ComplianceRunMetrics => {
  const record = isRecord(value) ? value : {};
  return {
    ...record,
    retrieve_ms: toNumberOrNull(record.retrieve_ms),
    merge_ms: toNumberOrNull(record.merge_ms),
    answer_ms: toNumberOrNull(record.answer_ms),
    total_ms: toNumberOrNull(record.total_ms),
    manual_count: toNumberOrNull(record.manual_count),
    documents_considered: toNumberOrNull(record.documents_considered),
    documents_with_hits: toNumberOrNull(record.documents_with_hits),
    global_selected_section_count: toNumberOrNull(record.global_selected_section_count),
    input_tokens: toNumberOrNull(record.input_tokens),
    output_tokens: toNumberOrNull(record.output_tokens),
    total_tokens: toNumberOrNull(record.total_tokens),
    successful_llm_calls: toNumberOrNull(record.successful_llm_calls),
    error: normalizeMetricsError(record.error),
  };
};

const normalizeError = (value: unknown): ComplianceRunError | null => {
  if (!isRecord(value)) return null;
  return {
    code: toStringOrNull(value.code),
    message: toStringOrNull(value.message),
    details: isRecord(value.details) ? value.details : null,
  };
};

export const normalizeComplianceRunStatus = (status: string): StandardRunStatus => {
  switch (status) {
    case 'accepted':
    case 'queued':
      return 'queued';
    case 'retrieving':
    case 'answering':
    case 'running':
      return 'running';
    case 'completed':
      return 'completed';
    case 'cancelled':
      return 'cancelled';
    case 'failed':
    default:
      return 'failed';
  }
};

export const normalizeComplianceCheck = (value: unknown): ComplianceCheck => {
  const record = isRecord(value) ? value : {};

  return {
    id: toStringOrFallback(record.id, ''),
    tenant_id: toStringOrFallback(record.tenant_id, ''),
    workspace_id: toStringOrFallback(record.workspace_id, ''),
    name: toStringOrFallback(record.name, ''),
    description: toStringOrNull(record.description),
    status: (toStringOrNull(record.status) ?? 'active') as ComplianceCheck['status'],
    target: normalizeTarget(record.target),
    query_template: toStringOrFallback(record.query_template, ''),
    instructions: toStringOrNull(record.instructions),
    verdict_policy: normalizeVerdictPolicy(record.verdict_policy),
    output_config: normalizeOutputConfig(record.output_config),
    retrieval_config: normalizeRetrievalConfig(record.retrieval_config),
    generation_config: normalizeGenerationConfig(record.generation_config),
    created_by: toStringOrFallback(record.created_by, ''),
    created_at: toStringOrFallback(record.created_at, ''),
    updated_at: toStringOrFallback(record.updated_at, ''),
  };
};

export const normalizeComplianceRun = (value: unknown): ComplianceRun => {
  const record = isRecord(value) ? value : {};
  const target = normalizeTarget(record.target);
  const rawStatus = toStringOrNull(record.status) as ComplianceRunRawStatus | null;
  const citations = normalizeCitations(record.citations, target.knowledge_base_id);
  const citationsById = Object.fromEntries(citations.map((citation) => [citation.citation_id, citation])) as Record<
    string,
    ComplianceCitation
  >;
  const evidence = normalizeEvidence(record.evidence, citationsById);
  const gaps = normalizeGaps(record.gaps);
  const conflicts = normalizeConflicts(record.conflicts);
  const result: ComplianceStructuredResult = {
    summary: toStringOrNull(record.summary),
    answer: toStringOrNull(record.answer),
    verdict: (toStringOrNull(record.verdict) ?? null) as ComplianceVerdict | null,
    confidence: toNumberOrNull(record.confidence),
    citations,
    citations_by_id: citationsById,
    evidence,
    gaps,
    conflicts,
    evidence_count: evidence.length,
    gap_count: gaps.length,
    conflict_count: conflicts.length,
    has_evidence: evidence.length > 0,
    has_gaps: gaps.length > 0,
    has_conflicts: conflicts.length > 0,
  };

  return {
    id: toStringOrFallback(record.id, ''),
    tenant_id: toStringOrFallback(record.tenant_id, ''),
    workspace_id: toStringOrFallback(record.workspace_id, ''),
    user_id: toStringOrFallback(record.user_id, ''),
    compliance_check_id: toStringOrNull(record.compliance_check_id),
    target,
    status: normalizeComplianceRunStatus(rawStatus ?? 'failed'),
    raw_status: rawStatus,
    mode: (toStringOrNull(record.mode) ?? 'single_manual') as ComplianceRun['mode'],
    provider_id: toStringOrNull(record.provider_id),
    model: toStringOrFallback(record.model, ''),
    input: normalizeRunInput(record.input),
    summary: result.summary,
    answer: result.answer,
    verdict: result.verdict,
    confidence: result.confidence,
    citations,
    evidence,
    gaps,
    conflicts,
    execution_context: normalizeExecutionContext(record.execution_context, target.knowledge_base_id),
    metrics: normalizeMetrics(record.metrics),
    error: normalizeError(record.error),
    created_at: toStringOrFallback(record.created_at, ''),
    started_at: toStringOrNull(record.started_at),
    finished_at: toStringOrNull(record.finished_at),
    result,
  };
};
