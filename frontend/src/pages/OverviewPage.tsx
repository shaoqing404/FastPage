import React, { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, BookCopy, CheckCircle2, Clock3, KeyRound, MessageSquare, Sparkles, Waves } from 'lucide-react';

import { authApi } from '../features/auth/api';
import { chatApi } from '../features/chat/api';
import { documentsApi } from '../features/documents/api';
import { metricsApi, jobsApi } from '../features/metrics/api';
import { providersApi } from '../features/providers/api';
import { skillsApi } from '../features/skills/api';
import { GlassPanel, KeyMetric, SectionToolbar, StatusBadge } from '../components/ui/workbench';
import { formatDateTime, formatRelativeTime, resolveProviderName } from '../lib/utils';

export const OverviewPage: React.FC = () => {
  const user = JSON.parse(localStorage.getItem('user') || '{}');
  const { data: overview } = useQuery({ queryKey: ['metrics-overview'], queryFn: metricsApi.overview });
  const { data: documents = [] } = useQuery({ queryKey: ['documents'], queryFn: documentsApi.list });
  const { data: skills = [] } = useQuery({ queryKey: ['skills'], queryFn: skillsApi.list });
  const { data: providers = [] } = useQuery({ queryKey: ['providers'], queryFn: providersApi.list });
  const { data: directAskSessions = [] } = useQuery({ queryKey: ['chat-sessions'], queryFn: () => chatApi.listSessions() });
  const { data: skillSessions = [] } = useQuery({
    queryKey: ['all-skill-sessions', ...skills.map((skill) => skill.id)],
    queryFn: async () => {
      const results = await Promise.all(skills.map((skill) => chatApi.listSkillSessions(skill.id)));
      return results.flat();
    },
    enabled: skills.length > 0,
  });
  const { data: runs = [] } = useQuery({ queryKey: ['all-runs'], queryFn: () => chatApi.listRuns() });
  const { data: jobs = [] } = useQuery({ queryKey: ['all-jobs'], queryFn: () => jobsApi.list() });
  const { data: apiKeys = [] } = useQuery({ queryKey: ['api-keys'], queryFn: authApi.listApiKeys });

  const readyDocuments = useMemo(() => documents.filter((document) => document.status === 'index_ready').length, [documents]);
  const failedRuns = useMemo(() => runs.filter((run) => run.status === 'failed'), [runs]);
  const activeJobs = useMemo(() => jobs.filter((job) => ['uploaded', 'queued', 'parsing'].includes(job.status)), [jobs]);
  const defaultProvider = providers.find((provider) => provider.is_default) || null;
  const sessions = useMemo(
    () => [...directAskSessions, ...skillSessions].sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()),
    [directAskSessions, skillSessions],
  );

  return (
    <div className="space-y-8">
      <SectionToolbar
        title="Overview"
        description="A single operational surface for documents, model execution, and recent knowledge work."
      />

      <GlassPanel className="overflow-visible" bodyClassName="space-y-8">
        <div className="grid grid-cols-[1.4fr_1fr] gap-6">
          <div className="space-y-4">
            <div className="inline-flex items-center gap-2 rounded-full bg-blue-50 px-3 py-1 text-xs font-medium uppercase tracking-[0.18em] text-blue-600">
              <Sparkles size={14} />
              <span>Operational summary</span>
            </div>
            <div className="space-y-3">
              <h1 className="max-w-3xl text-5xl font-semibold tracking-[-0.05em] text-slate-950">
                Build, inspect, and chat against your structured knowledge base without dropping into raw config.
              </h1>
              <p className="max-w-3xl text-base leading-7 text-slate-600">
                Welcome back, {user.username || 'operator'}. This workbench keeps document ingestion, skill design, provider control, and
                session health in one Apple-style surface instead of scattering them across generic admin pages.
              </p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <KeyMetric label="Documents" value={overview?.documents ?? 0} hint={`${readyDocuments} ready for chat`} />
            <KeyMetric label="Skills" value={skills.length} hint="Reusable knowledge behaviors" />
            <KeyMetric label="Chat Runs" value={overview?.chat_runs ?? 0} hint={`${failedRuns.length} failed recently`} />
            <KeyMetric label="Providers" value={providers.length} hint={defaultProvider ? `${defaultProvider.name} is tenant default` : 'No tenant default yet'} />
          </div>
        </div>

        <div className="grid grid-cols-4 gap-4">
          <div className="surface-soft p-4">
            <p className="metric-label">Tenant default provider</p>
            <p className="mt-2 text-lg font-semibold text-slate-900">{defaultProvider?.name || 'Backend resolved'}</p>
            <p className="mt-1 text-sm text-slate-500">{defaultProvider?.default_model || 'System default execution may be used'}</p>
          </div>
          <div className="surface-soft p-4">
            <p className="metric-label">Open sessions</p>
            <p className="mt-2 text-lg font-semibold text-slate-900">{sessions.length}</p>
            <p className="mt-1 text-sm text-slate-500">Direct ask plus skill-scoped session continuity</p>
          </div>
          <div className="surface-soft p-4">
            <p className="metric-label">API keys</p>
            <p className="mt-2 text-lg font-semibold text-slate-900">{apiKeys.length}</p>
            <p className="mt-1 text-sm text-slate-500">Tenant-scoped programmatic access</p>
          </div>
          <div className="surface-soft p-4">
            <p className="metric-label">Active parse jobs</p>
            <p className="mt-2 text-lg font-semibold text-slate-900">{activeJobs.length}</p>
            <p className="mt-1 text-sm text-slate-500">Real-time ingestion pipeline load</p>
          </div>
        </div>
      </GlassPanel>

      <div className="grid grid-cols-[1.1fr_1fr] gap-6">
        <GlassPanel title="Recent work" subtitle="Latest sessions, runs, and ingestions across the tenant.">
          <div className="space-y-3">
            {runs.slice(0, 5).map((run) => (
              <div key={run.id} className="list-row">
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <StatusBadge tone={run.status === 'completed' ? 'success' : run.status === 'failed' ? 'danger' : 'accent'}>
                      {run.status}
                    </StatusBadge>
                    <span className="text-sm text-slate-500">{formatRelativeTime(run.created_at)}</span>
                  </div>
                  <p className="text-sm font-medium text-slate-900">{run.question}</p>
                  <p className="text-sm text-slate-500">
                    {resolveProviderName(run.provider_id, providers)} · {run.model}
                  </p>
                </div>
                <div className="text-right text-sm text-slate-500">
                  <p>{run.metrics.total_ms ? `${run.metrics.total_ms} ms` : 'No timing'}</p>
                  <p>{run.citations.length} citations</p>
                </div>
              </div>
            ))}
            {runs.length === 0 && <div className="empty-state min-h-[140px]">No runs yet.</div>}
          </div>
        </GlassPanel>

        <GlassPanel title="Attention queue" subtitle="Items that need review before the next work session.">
          <div className="space-y-4">
            <div className="surface-soft flex items-start gap-3 p-4">
              <Clock3 size={18} className="mt-0.5 text-blue-600" />
              <div>
                <p className="font-medium text-slate-900">Sessions and recent work</p>
                <p className="text-sm text-slate-500">
                  {sessions.length > 0 ? `${sessions[0].title} was updated ${formatRelativeTime(sessions[0].updated_at)}.` : 'No conversation session created yet.'}
                </p>
              </div>
            </div>
            <div className="surface-soft flex items-start gap-3 p-4">
              <BookCopy size={18} className="mt-0.5 text-blue-600" />
              <div>
                <p className="font-medium text-slate-900">Documents ready for chat</p>
                <p className="text-sm text-slate-500">
                  {readyDocuments} of {documents.length} documents are ready. {activeJobs.length > 0 ? `${activeJobs.length} jobs are still processing.` : 'No active parse backlog.'}
                </p>
              </div>
            </div>
            <div className="surface-soft flex items-start gap-3 p-4">
              <AlertTriangle size={18} className="mt-0.5 text-amber-600" />
              <div>
                <p className="font-medium text-slate-900">Failure watchlist</p>
                <p className="text-sm text-slate-500">
                  {failedRuns.length > 0
                    ? `${failedRuns.length} runs failed recently. Review execution context in Chat or Activity.`
                    : 'No failed runs in the recent run list.'}
                </p>
              </div>
            </div>
            <div className="surface-soft flex items-start gap-3 p-4">
              <KeyRound size={18} className="mt-0.5 text-blue-600" />
              <div>
                <p className="font-medium text-slate-900">Provider resolution</p>
                <p className="text-sm text-slate-500">
                  Skill-bound provider overrides request provider. Tenant default is {defaultProvider?.name || 'not configured'}, then backend system default takes over.
                </p>
              </div>
            </div>
          </div>
        </GlassPanel>
      </div>

      <div className="grid grid-cols-[1fr_1fr_1fr] gap-6">
        <GlassPanel title="Latest documents" subtitle="Recently ingested or updated assets.">
          <div className="space-y-3">
            {documents.slice(0, 4).map((document) => (
              <div key={document.id} className="list-row">
                <div>
                  <p className="font-medium text-slate-900">{document.display_name}</p>
                  <p className="text-sm text-slate-500">{formatDateTime(document.updated_at)}</p>
                </div>
                <StatusBadge tone={document.status === 'index_ready' ? 'success' : document.status === 'failed' ? 'danger' : 'accent'}>
                  {document.status}
                </StatusBadge>
              </div>
            ))}
          </div>
        </GlassPanel>

        <GlassPanel title="Latest sessions" subtitle="Continuity surfaces for ongoing chat work.">
          <div className="space-y-3">
            {sessions.slice(0, 4).map((session) => (
              <div key={session.id} className="list-row">
                <div>
                  <p className="font-medium text-slate-900">{session.title}</p>
                  <p className="text-sm text-slate-500">{formatDateTime(session.updated_at)}</p>
                </div>
                <MessageSquare size={18} className="text-slate-400" />
              </div>
            ))}
            {sessions.length === 0 && <p className="text-sm text-slate-500">No sessions yet.</p>}
          </div>
        </GlassPanel>

        <GlassPanel title="System posture" subtitle="High-level health without pretending to be a full admin suite.">
          <div className="space-y-4">
            <div className="surface-soft flex items-start gap-3 p-4">
              <CheckCircle2 size={18} className="mt-0.5 text-emerald-600" />
              <div>
                <p className="font-medium text-slate-900">Providers configured</p>
                <p className="text-sm text-slate-500">{providers.length} provider profiles available for tenant use.</p>
              </div>
            </div>
            <div className="surface-soft flex items-start gap-3 p-4">
              <Waves size={18} className="mt-0.5 text-blue-600" />
              <div>
                <p className="font-medium text-slate-900">Chat session continuity</p>
                <p className="text-sm text-slate-500">Session history is available through the current backend session endpoints.</p>
              </div>
            </div>
            <div className="surface-soft flex items-start gap-3 p-4">
              <AlertTriangle size={18} className="mt-0.5 text-amber-600" />
              <div>
                <p className="font-medium text-slate-900">Backend defaults</p>
                <p className="text-sm text-slate-500">Exact system default base URL and model are not exposed by API in this phase.</p>
              </div>
            </div>
          </div>
        </GlassPanel>
      </div>
    </div>
  );
};
