import React, { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Activity, AlertTriangle, Clock3, FileStack, RefreshCcw } from 'lucide-react';

import { AnswerContent } from '../components/ui/AnswerContent';
import { GlassPanel, KeyMetric, SectionToolbar, StatusBadge } from '../components/ui/workbench';
import { chatApi } from '../features/chat/api';
import { jobsApi, metricsApi } from '../features/metrics/api';
import { providersApi } from '../features/providers/api';
import type { ChatRun, ParseJob } from '../types';
import { formatDateTime, formatPageRange, resolveProviderName } from '../lib/utils';

type ActivityItem =
  | { kind: 'run'; id: string; payload: ChatRun }
  | { kind: 'job'; id: string; payload: ParseJob };

export const ActivityPage: React.FC = () => {
  const [selection, setSelection] = useState<ActivityItem | null>(null);
  const { data: overview } = useQuery({ queryKey: ['metrics-overview'], queryFn: metricsApi.overview, staleTime: 5000 });
  const { data: runs = [] } = useQuery({ queryKey: ['all-runs'], queryFn: () => chatApi.listRuns(), staleTime: 5000 });
  const { data: jobs = [] } = useQuery({ queryKey: ['all-jobs'], queryFn: () => jobsApi.list(), staleTime: 5000 });
  const { data: providers = [] } = useQuery({ queryKey: ['providers'], queryFn: providersApi.list });

  const activeRuns = useMemo(() => runs.filter((run) => run.status !== 'completed' && run.status !== 'failed').length, [runs]);
  const failedRuns = useMemo(() => runs.filter((run) => run.status === 'failed'), [runs]);
  const activeJobs = useMemo(() => jobs.filter((job) => ['uploaded', 'queued', 'parsing'].includes(job.status)).length, [jobs]);

  return (
    <div className="space-y-8">
      <SectionToolbar title="Activity" description="Runs, jobs, diagnostics, and failure context in one inspectable surface." />

      <div className="grid grid-cols-4 gap-4">
        <KeyMetric label="Chat runs" value={overview?.chat_runs ?? 0} hint={`${activeRuns} active`} />
        <KeyMetric label="Parse jobs" value={overview?.parse_jobs ?? 0} hint={`${activeJobs} in progress`} />
        <KeyMetric label="Failures" value={failedRuns.length} hint="Recent runs requiring review" />
        <KeyMetric label="Documents" value={overview?.documents ?? 0} hint="Current tenant footprint" />
      </div>

      <div className="grid grid-cols-[1.1fr_1.1fr_0.9fr] gap-6">
        <GlassPanel
          title="Run log"
          subtitle="Conversation runs and skill executions."
          actions={
            <button type="button" className="btn-secondary">
              <RefreshCcw size={16} />
              <span>Live</span>
            </button>
          }
        >
          <div className="scroll-area max-h-[720px] space-y-3 overflow-auto pr-1">
            {runs.map((run) => (
              <button
                type="button"
                key={run.id}
                onClick={() => setSelection({ kind: 'run', id: run.id, payload: run })}
                className={`list-row w-full text-left ${selection?.id === run.id ? 'list-row-active' : ''}`}
              >
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <StatusBadge tone={run.status === 'completed' ? 'success' : run.status === 'failed' ? 'danger' : 'accent'}>
                      {run.status}
                    </StatusBadge>
                    <span className="text-sm text-slate-500">{formatDateTime(run.created_at)}</span>
                  </div>
                  <p className="line-clamp-2 text-sm font-medium text-slate-900">{run.question}</p>
                  <p className="text-sm text-slate-500">
                    {resolveProviderName(run.provider_id, providers)} · {run.model}
                  </p>
                </div>
                <div className="text-right text-sm text-slate-500">
                  <p>{run.metrics.total_ms ? `${run.metrics.total_ms} ms` : 'No timing'}</p>
                  <p>{run.citations.length} citations</p>
                </div>
              </button>
            ))}
          </div>
        </GlassPanel>

        <GlassPanel title="Parse jobs" subtitle="Ingestion pipeline status across document versions.">
          <div className="scroll-area max-h-[720px] space-y-3 overflow-auto pr-1">
            {jobs.map((job) => (
              <button
                type="button"
                key={job.id}
                onClick={() => setSelection({ kind: 'job', id: job.id, payload: job })}
                className={`list-row w-full text-left ${selection?.id === job.id ? 'list-row-active' : ''}`}
              >
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <StatusBadge tone={job.status === 'index_ready' ? 'success' : job.status === 'failed' ? 'danger' : 'accent'}>
                      {job.status}
                    </StatusBadge>
                    <span className="text-sm text-slate-500">{formatDateTime(job.created_at)}</span>
                  </div>
                  <p className="text-sm font-medium text-slate-900">Document {job.document_id.slice(0, 8)}</p>
                  <p className="text-sm text-slate-500">{job.current_step || 'Waiting for next step'}</p>
                </div>
                <div className="text-right text-sm text-slate-500">
                  <p>{job.progress_percent}%</p>
                  <p>{job.model || 'Default parse model'}</p>
                </div>
              </button>
            ))}
          </div>
        </GlassPanel>

        <GlassPanel title="Inspector" subtitle="Detailed context for the selected run or parse job.">
          {selection?.kind === 'run' ? (
            <RunInspector run={selection.payload} providers={providers} />
          ) : selection?.kind === 'job' ? (
            <JobInspector job={selection.payload} />
          ) : (
            <div className="empty-state min-h-[520px]">
              <p className="text-base font-medium text-slate-900">Select an activity item</p>
              <p className="text-sm text-slate-500">Pick a run or parse job from the lists to inspect its execution details.</p>
            </div>
          )}
        </GlassPanel>
      </div>
    </div>
  );
};

const RunInspector = ({ run, providers }: { run: ChatRun; providers: Parameters<typeof resolveProviderName>[1] }) => (
  <div className="space-y-6">
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <StatusBadge tone={run.status === 'completed' ? 'success' : run.status === 'failed' ? 'danger' : 'accent'}>{run.status}</StatusBadge>
        <span className="text-sm text-slate-500">{formatDateTime(run.created_at)}</span>
      </div>
      <p className="text-lg font-semibold tracking-[-0.02em] text-slate-900">{run.question}</p>
      <AnswerContent content={run.answer_text || run.answer} variant="compact" />
    </div>

    <dl className="data-kv">
      <dt>Provider</dt>
      <dd>{resolveProviderName(run.provider_id, providers)}</dd>
      <dt>Model</dt>
      <dd>{run.model}</dd>
      <dt>Session</dt>
      <dd>{run.session_id || 'No session'}</dd>
      <dt>Document</dt>
      <dd>{run.document_id || 'N/A'}</dd>
      <dt>Skill</dt>
      <dd>{run.skill_id || 'Direct ask'}</dd>
    </dl>

    <div className="grid grid-cols-2 gap-3">
      <div className="surface-soft p-4">
        <p className="metric-label">Latency</p>
        <p className="mt-2 text-xl font-semibold text-slate-900">{run.metrics.total_ms ? `${run.metrics.total_ms} ms` : 'N/A'}</p>
      </div>
      <div className="surface-soft p-4">
        <p className="metric-label">Tokens</p>
        <p className="mt-2 text-xl font-semibold text-slate-900">{run.metrics.total_tokens ?? 'N/A'}</p>
      </div>
      <div className="surface-soft p-4">
        <p className="metric-label">Retrieved sections</p>
        <p className="mt-2 text-xl font-semibold text-slate-900">{run.selected_sections.length}</p>
      </div>
      <div className="surface-soft p-4">
        <p className="metric-label">Citations</p>
        <p className="mt-2 text-xl font-semibold text-slate-900">{run.citations.length}</p>
      </div>
    </div>

    <div className="space-y-3">
      <p className="metric-label">Citations</p>
      {run.citations.length > 0 ? (
        <div className="space-y-2">
          {run.citations.map((citation, index) => (
            <div key={`${citation.snippet_id || citation.node_id || index}`} className="surface-soft p-4">
              <div className="flex items-center justify-between gap-3">
                <p className="font-medium text-slate-900">{citation.title || 'Untitled citation'}</p>
                <span className="text-sm text-slate-500">{formatPageRange(citation.page_start, citation.page_end)}</span>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm text-slate-500">No citations recorded.</p>
      )}
    </div>
  </div>
);

const JobInspector = ({ job }: { job: ParseJob }) => (
  <div className="space-y-6">
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <StatusBadge tone={job.status === 'index_ready' ? 'success' : job.status === 'failed' ? 'danger' : 'accent'}>{job.status}</StatusBadge>
        <span className="text-sm text-slate-500">{formatDateTime(job.created_at)}</span>
      </div>
      <p className="text-lg font-semibold tracking-[-0.02em] text-slate-900">Document {job.document_id}</p>
      <p className="text-sm text-slate-500">{job.current_step || 'No active parse step reported.'}</p>
    </div>

    <dl className="data-kv">
      <dt>Version</dt>
      <dd>{job.version_id}</dd>
      <dt>Model</dt>
      <dd>{job.model || 'Backend default'}</dd>
      <dt>Progress</dt>
      <dd>{job.progress_percent}%</dd>
      <dt>Started</dt>
      <dd>{formatDateTime(job.started_at)}</dd>
      <dt>Finished</dt>
      <dd>{formatDateTime(job.finished_at)}</dd>
      <dt>Error</dt>
      <dd>{job.error_message || 'No error recorded'}</dd>
    </dl>

    <div className="grid grid-cols-1 gap-3">
      <div className="surface-soft flex items-start gap-3 p-4">
        <FileStack size={18} className="mt-0.5 text-blue-600" />
        <div>
          <p className="font-medium text-slate-900">Pipeline state</p>
          <p className="text-sm text-slate-500">{job.current_step || 'Waiting in pipeline'}.</p>
        </div>
      </div>
      <div className="surface-soft flex items-start gap-3 p-4">
        <Activity size={18} className="mt-0.5 text-blue-600" />
        <div>
          <p className="font-medium text-slate-900">Status visibility</p>
          <p className="text-sm text-slate-500">Progress is provided by the current job endpoint and refreshed through React Query.</p>
        </div>
      </div>
      <div className="surface-soft flex items-start gap-3 p-4">
        {job.status === 'failed' ? <AlertTriangle size={18} className="mt-0.5 text-amber-600" /> : <Clock3 size={18} className="mt-0.5 text-blue-600" />}
        <div>
          <p className="font-medium text-slate-900">Operator action</p>
          <p className="text-sm text-slate-500">
            {job.status === 'failed' ? 'Review the parse failure and re-run the document from Documents.' : 'Monitor progress here, then inspect the document once parsing completes.'}
          </p>
        </div>
      </div>
    </div>
  </div>
);
