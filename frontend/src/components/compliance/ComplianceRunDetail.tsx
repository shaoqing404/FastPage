import React from 'react';
import { AlertTriangle, Loader2, Sparkles } from 'lucide-react';

import { RunObservationTimeline } from '../runtime/RunObservationTimeline';
import type { ComplianceCheck, ComplianceRun, KnowledgeBase, ModelProvider } from '../../types';
import { formatDateTime, resolveProviderName } from '../../lib/utils';
import { AnswerContent } from '../ui/AnswerContent';
import { EmptyState, GlassPanel, InlineAlert, StatusBadge } from '../ui/workbench';
import { ComplianceCitationCard } from './ComplianceCitationCard';
import { ComplianceRunStatusBadge, ComplianceVerdictBadge } from './ComplianceBadges';
import { formatCitationChain, formatComplianceLabel } from './utils';

const confidenceLabel = (confidence: number | null) => {
  if (confidence === null || Number.isNaN(confidence)) return 'Unspecified';
  return `${Math.round(confidence * 100)}% confidence`;
};

const severityTone = (severity: string) => {
  switch (severity) {
    case 'critical':
    case 'high':
      return 'danger';
    case 'medium':
      return 'warning';
    case 'low':
      return 'accent';
    default:
      return 'default';
  }
};

export const ComplianceRunDetail: React.FC<{
  run: ComplianceRun | null;
  check?: ComplianceCheck | null;
  knowledgeBase?: KnowledgeBase | null;
  providers?: ModelProvider[];
  observationSnapshot?: import('../../types').RunObservationSnapshot | null;
  isLoading?: boolean;
  isRefreshing?: boolean;
  loadError?: string;
}> = ({ run, check = null, knowledgeBase = null, providers = [], observationSnapshot = null, isLoading = false, isRefreshing = false, loadError }) => {
  if (isLoading && !run) {
    return (
      <GlassPanel title="Run detail" subtitle="Structured compliance result">
        <div className="empty-state min-h-[480px]">
          <Loader2 size={20} className="animate-spin text-blue-600" />
          <p className="text-sm text-slate-500">Loading compliance run detail…</p>
        </div>
      </GlassPanel>
    );
  }

  if (!run) {
    return (
      <GlassPanel title="Run detail" subtitle="Structured compliance result">
        <EmptyState
          title="Select a run"
          description="Choose a compliance run from the left to inspect verdict, evidence provenance, gaps, conflicts, and execution context."
        />
      </GlassPanel>
    );
  }

  const providerLabel = resolveProviderName(run.provider_id, providers);
  const resolvedManuals = run.execution_context.resolved_manuals || [];
  const retrieval = run.execution_context.retrieval;
  const merge = run.execution_context.merge;
  const generation = run.execution_context.generation;

  return (
    <div className="space-y-6">
      <GlassPanel
        title="Run detail"
        subtitle={knowledgeBase ? `Knowledge Base: ${knowledgeBase.name}` : `Knowledge Base: ${run.target.knowledge_base_id}`}
        actions={isRefreshing ? <Loader2 size={16} className="animate-spin text-blue-600" /> : undefined}
      >
        <div className="space-y-6">
          {loadError && (
            <InlineAlert tone="danger" title="Run detail refresh failed">
              {loadError}
            </InlineAlert>
          )}

          {run.status === 'running' || run.status === 'queued' ? (
            <InlineAlert tone="warning" title="Run still in progress">
              The backend is still retrieving or composing this result. The page refreshes automatically while the run is active.
            </InlineAlert>
          ) : null}

          {run.status === 'failed' && (
            <InlineAlert tone="danger" title={run.error?.code ? `Run failed · ${run.error.code}` : 'Run failed'}>
              {run.error?.message || 'The backend returned a failed run state without a structured error message.'}
            </InlineAlert>
          )}

          <div className="space-y-4">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  <ComplianceRunStatusBadge run={run} />
                  <ComplianceVerdictBadge verdict={run.verdict} />
                  <span className="rounded-full border border-slate-200 bg-white/75 px-3 py-1 text-xs font-medium text-slate-600">
                    {confidenceLabel(run.confidence)}
                  </span>
                </div>
                <div>
                  <p className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500">Question</p>
                  <h2 className="mt-2 text-[28px] font-semibold tracking-[-0.03em] text-slate-900">{run.input.question}</h2>
                </div>
              </div>

              <div className="min-w-[260px] rounded-[24px] border border-white/80 bg-white/75 p-4">
                <dl className="data-kv">
                  <dt>Run source</dt>
                  <dd>{check ? check.name : 'Ad hoc run'}</dd>
                  <dt>Created</dt>
                  <dd>{formatDateTime(run.created_at)}</dd>
                  <dt>Finished</dt>
                  <dd>{formatDateTime(run.finished_at)}</dd>
                  <dt>Provider</dt>
                  <dd>{providerLabel}</dd>
                  <dt>Model</dt>
                  <dd>{run.model || generation.model || 'Backend default'}</dd>
                  <dt>Mode</dt>
                  <dd>{formatComplianceLabel(run.mode)}</dd>
                </dl>
              </div>
            </div>

            <div className="grid gap-3 md:grid-cols-4">
              <div className="surface-soft p-4">
                <p className="metric-label">Manuals</p>
                <p className="mt-2 text-xl font-semibold text-slate-900">{run.metrics.manual_count ?? resolvedManuals.length}</p>
                <p className="mt-1 text-sm text-slate-500">Resolved for this run</p>
              </div>
              <div className="surface-soft p-4">
                <p className="metric-label">Citations</p>
                <p className="mt-2 text-xl font-semibold text-slate-900">{run.citations.length}</p>
                <p className="mt-1 text-sm text-slate-500">Selected into result context</p>
              </div>
              <div className="surface-soft p-4">
                <p className="metric-label">Evidence</p>
                <p className="mt-2 text-xl font-semibold text-slate-900">{run.result.evidence_count}</p>
                <p className="mt-1 text-sm text-slate-500">Grounded result statements</p>
              </div>
              <div className="surface-soft p-4">
                <p className="metric-label">Latency</p>
                <p className="mt-2 text-xl font-semibold text-slate-900">{run.metrics.total_ms ? `${run.metrics.total_ms} ms` : 'N/A'}</p>
                <p className="mt-1 text-sm text-slate-500">End-to-end runtime</p>
              </div>
            </div>
          </div>
        </div>
      </GlassPanel>

      <GlassPanel title="Summary and answer" subtitle="Short operator read first, detailed answer second.">
        <div className="grid gap-4 xl:grid-cols-[0.8fr_1.2fr]">
          <div className="surface-soft space-y-3 p-4">
            <p className="metric-label">Summary</p>
            <AnswerContent content={run.summary} emptyFallback="No summary was returned for this run." />
          </div>
          <div className="surface-soft space-y-3 p-4">
            <p className="metric-label">Answer</p>
            <AnswerContent content={run.answer} emptyFallback="No answer body was returned for this run." />
          </div>
        </div>
      </GlassPanel>

      <GlassPanel title="Runtime timeline" subtitle="Observe worker stage transitions, rerank decisions, and model I/O.">
        <RunObservationTimeline
          snapshot={observationSnapshot}
          title="Compliance execution timeline"
          emptyTitle="No runtime timeline yet"
          emptyDescription="Run this check to populate the backend execution timeline."
        />
      </GlassPanel>

      <GlassPanel title="Evidence" subtitle="Each evidence statement carries its citation ids and full provenance chain.">
        {run.evidence.length === 0 ? (
          <EmptyState
            title="No evidence items"
            description="This run did not return grounded evidence statements. Review gaps, conflicts, or the failure state below."
          />
        ) : (
          <div className="space-y-4">
            {run.evidence.map((item) => (
              <article key={item.evidence_id} className="surface-soft space-y-4 p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded-full bg-blue-600 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-white">
                        {item.kind}
                      </span>
                      <span className="rounded-full border border-slate-200 bg-white/75 px-2.5 py-1 text-[11px] font-medium text-slate-600">
                        {item.source_count} source{item.source_count === 1 ? '' : 's'}
                      </span>
                    </div>
                    <p className="text-sm font-medium leading-6 text-slate-900">{item.statement}</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {item.citation_ids.map((citationId) => (
                      <span key={citationId} className="rounded-full border border-slate-200 bg-white/75 px-2.5 py-1 text-[11px] font-medium text-slate-600">
                        {citationId}
                      </span>
                    ))}
                  </div>
                </div>

                <div className="space-y-3">
                  <p className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500">Provenance</p>
                  <div className="grid gap-3 xl:grid-cols-2">
                    {item.provenance.map((citation) => (
                      <ComplianceCitationCard key={`${item.evidence_id}-${citation.citation_id}`} citation={citation} compact />
                    ))}
                  </div>
                </div>
              </article>
            ))}
          </div>
        )}
      </GlassPanel>

      <div className="grid gap-6 xl:grid-cols-2">
        <GlassPanel title="Gaps" subtitle="What the retrieved manuals still do not establish.">
          {run.gaps.length === 0 ? (
            <EmptyState title="No gaps recorded" description="The model did not explicitly report unresolved evidence gaps for this run." />
          ) : (
            <div className="space-y-3">
              {run.gaps.map((gap) => (
                <article key={gap.gap_id} className="surface-soft space-y-3 p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge tone={severityTone(gap.severity)}>{formatComplianceLabel(gap.severity)}</StatusBadge>
                    <span className="rounded-full border border-slate-200 bg-white/75 px-2.5 py-1 text-[11px] font-medium text-slate-600">
                      {formatComplianceLabel(gap.type)}
                    </span>
                  </div>
                  <p className="text-sm leading-6 text-slate-900">{gap.statement}</p>
                  <div className="flex flex-wrap gap-2">
                    {gap.related_citation_ids.length > 0 ? (
                      gap.related_citation_ids.map((citationId) => (
                        <span key={citationId} className="rounded-full border border-slate-200 bg-white/75 px-2.5 py-1 text-[11px] font-medium text-slate-600">
                          {citationId}
                        </span>
                      ))
                    ) : (
                      <span className="text-sm text-slate-500">No direct citation attached.</span>
                    )}
                  </div>
                </article>
              ))}
            </div>
          )}
        </GlassPanel>

        <GlassPanel title="Conflicts" subtitle="Cross-source disagreements and unresolved interpretation clashes.">
          {run.conflicts.length === 0 ? (
            <EmptyState title="No conflicts recorded" description="The result did not identify explicit cross-source conflicts in the selected evidence." />
          ) : (
            <div className="space-y-3">
              {run.conflicts.map((conflict) => (
                <article key={conflict.conflict_id} className="surface-soft space-y-3 p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge tone={conflict.resolution_status === 'resolved' ? 'success' : 'warning'}>
                      {formatComplianceLabel(conflict.resolution_status)}
                    </StatusBadge>
                    <span className="rounded-full border border-slate-200 bg-white/75 px-2.5 py-1 text-[11px] font-medium text-slate-600">
                      {formatComplianceLabel(conflict.type)}
                    </span>
                  </div>
                  <p className="text-sm leading-6 text-slate-900">{conflict.summary}</p>
                  <div className="flex flex-wrap gap-2">
                    {conflict.citation_ids.length > 0 ? (
                      conflict.citation_ids.map((citationId) => (
                        <span key={citationId} className="rounded-full border border-slate-200 bg-white/75 px-2.5 py-1 text-[11px] font-medium text-slate-600">
                          {citationId}
                        </span>
                      ))
                    ) : (
                      <span className="text-sm text-slate-500">No citation ids attached.</span>
                    )}
                  </div>
                </article>
              ))}
            </div>
          )}
        </GlassPanel>
      </div>

      <GlassPanel title="Citation index" subtitle="Full source lineage for every citation returned in the run.">
        {run.citations.length === 0 ? (
          <EmptyState title="No citations returned" description="The run did not expose citation records. If this was unexpected, inspect the failure state or retrieval context." />
        ) : (
          <div className="grid gap-4 xl:grid-cols-2">
            {run.citations.map((citation) => (
              <ComplianceCitationCard key={citation.citation_id} citation={citation} />
            ))}
          </div>
        )}
      </GlassPanel>

      <GlassPanel title="Execution context" subtitle="How the backend resolved scope, retrieval fan-out, merge, and generation for this run.">
        <div className="space-y-6">
          <div className="grid gap-4 xl:grid-cols-[0.86fr_1.14fr]">
            <div className="surface-soft space-y-3 p-4">
              <p className="metric-label">Resolved scope</p>
              <dl className="data-kv">
                <dt>Knowledge Base</dt>
                <dd>{knowledgeBase?.name || run.execution_context.target.knowledge_base_id || run.target.knowledge_base_id}</dd>
                <dt>Requested mode</dt>
                <dd>{formatComplianceLabel(run.execution_context.target.requested_mode)}</dd>
                <dt>Resolved mode</dt>
                <dd>{formatComplianceLabel(run.execution_context.target.resolved_mode || run.mode)}</dd>
                <dt>Saved check</dt>
                <dd>{check?.name || 'Ad hoc run'}</dd>
              </dl>
            </div>

            <div className="surface-soft space-y-3 p-4">
              <p className="metric-label">Generation</p>
              <dl className="data-kv">
                <dt>Provider</dt>
                <dd>{resolveProviderName(generation.provider_id || run.provider_id, providers)}</dd>
                <dt>Model</dt>
                <dd>{generation.model || run.model || 'Backend default'}</dd>
                <dt>Temperature</dt>
                <dd>{generation.temperature ?? 'Default'}</dd>
                <dt>Input tokens</dt>
                <dd>{run.metrics.input_tokens ?? 'N/A'}</dd>
                <dt>Total tokens</dt>
                <dd>{run.metrics.total_tokens ?? 'N/A'}</dd>
              </dl>
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-3">
            <div className="surface-soft p-4">
              <p className="metric-label">Retrieval</p>
              <p className="mt-2 text-xl font-semibold text-slate-900">{retrieval.documents_with_hits ?? 0} / {retrieval.documents_considered ?? 0}</p>
              <p className="mt-1 text-sm text-slate-500">Documents with hits</p>
            </div>
            <div className="surface-soft p-4">
              <p className="metric-label">Merge candidates</p>
              <p className="mt-2 text-xl font-semibold text-slate-900">{merge.candidate_count ?? 0}</p>
              <p className="mt-1 text-sm text-slate-500">Before global selection</p>
            </div>
            <div className="surface-soft p-4">
              <p className="metric-label">Selected citations</p>
              <p className="mt-2 text-xl font-semibold text-slate-900">{merge.selected_citation_count ?? run.citations.length}</p>
              <p className="mt-1 text-sm text-slate-500">Merged result context</p>
            </div>
          </div>

          <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
            <div className="surface-soft space-y-3 p-4">
              <p className="metric-label">Retrieval configuration</p>
              <dl className="data-kv">
                <dt>Per-doc top K</dt>
                <dd>{retrieval.per_document_top_k ?? 'N/A'}</dd>
                <dt>Global top K</dt>
                <dd>{retrieval.global_top_k ?? 'N/A'}</dd>
                <dt>Selection mode</dt>
                <dd>{retrieval.selection_mode || 'N/A'}</dd>
                <dt>Retrieve ms</dt>
                <dd>{run.metrics.retrieve_ms ?? 'N/A'}</dd>
                <dt>Answer ms</dt>
                <dd>{run.metrics.answer_ms ?? 'N/A'}</dd>
              </dl>
            </div>

            <div className="surface-soft space-y-3 p-4">
              <div className="flex items-center gap-2">
                <Sparkles size={16} className="text-blue-600" />
                <p className="text-sm font-medium text-slate-900">Resolved manuals</p>
              </div>
              {resolvedManuals.length === 0 ? (
                <p className="text-sm text-slate-500">No resolved manuals were returned in execution context.</p>
              ) : (
                <div className="space-y-3">
                  {resolvedManuals.map((manual) => (
                    <div key={`${manual.document_id}:${manual.version_id}`} className="rounded-2xl border border-slate-200 bg-white/70 p-3">
                      <p className="text-sm font-medium text-slate-900">{manual.label || manual.document_id}</p>
                      <p className="text-sm text-slate-500">{manual.version_label || manual.version_id}</p>
                      <p className="mt-2 text-xs text-slate-500">
                        {manual.label || manual.document_id} / {manual.version_label || manual.version_id}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {run.status === 'failed' && (
            <div className="surface-soft space-y-3 p-4">
              <div className="flex items-center gap-2 text-slate-900">
                <AlertTriangle size={16} className="text-amber-600" />
                <p className="text-sm font-medium">Failure context</p>
              </div>
              <p className="text-sm text-slate-600">
                {run.error?.message || 'The backend marked this run as failed without a structured message.'}
              </p>
              {run.citations.length > 0 && (
                <p className="text-xs text-slate-500">
                  Partial citations were still returned. Review provenance above before treating any partial answer as final.
                </p>
              )}
            </div>
          )}

          {run.citations.length > 0 && (
            <div className="rounded-[24px] border border-white/75 bg-white/70 p-4">
              <p className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500">Provenance pattern</p>
              <p className="mt-2 text-sm text-slate-900">{formatCitationChain(run.citations[0])}</p>
              <p className="mt-1 text-xs text-slate-500">Every citation above follows the same document / version / page / node chain rendering.</p>
            </div>
          )}
        </div>
      </GlassPanel>
    </div>
  );
};
