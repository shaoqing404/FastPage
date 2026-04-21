import React, { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Activity, AlertTriangle, ArrowRight, BookCopy, CheckCircle2, Clock3, KeyRound, Layers3, MessageSquare, Settings2, Sparkles, Waves } from 'lucide-react';
import { Link } from 'react-router-dom';

import { authApi } from '../features/auth/api';
import { chatApi } from '../features/chat/api';
import { documentsApi } from '../features/documents/api';
import { knowledgeBasesApi } from '../features/knowledge-bases/api';
import { metricsApi, jobsApi } from '../features/metrics/api';
import { providersApi } from '../features/providers/api';
import { skillsApi } from '../features/skills/api';
import { GlassPanel, KeyMetric, SectionToolbar, StatusBadge } from '../components/ui/workbench';
import { formatDateTime, formatRelativeTime, resolveProviderName, resolveWorkspaceDefaultProvider } from '../lib/utils';
import { resolveStoredWorkspace } from '../lib/api/client';

export const OverviewPage: React.FC = () => {
  const user = JSON.parse(localStorage.getItem('user') || '{}');
  const workspace = resolveStoredWorkspace();
  const { data: overview } = useQuery({ queryKey: ['metrics-overview'], queryFn: metricsApi.overview });
  const { data: documents = [] } = useQuery({ queryKey: ['documents'], queryFn: () => documentsApi.list() });
  const { data: knowledgeBases = [] } = useQuery({ queryKey: ['knowledge-bases'], queryFn: () => knowledgeBasesApi.list() });
  const { data: skills = [] } = useQuery({ queryKey: ['skills'], queryFn: skillsApi.list });
  const { data: providers = [] } = useQuery({ queryKey: ['provider-catalog'], queryFn: providersApi.listCatalog });
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
  const enabledKnowledgeBaseDocuments = useMemo(
    () => knowledgeBases.reduce((total, knowledgeBase) => total + knowledgeBase.documents.filter((document) => document.enabled).length, 0),
    [knowledgeBases],
  );
  const failedRuns = useMemo(() => runs.filter((run) => run.status === 'failed'), [runs]);
  const activeJobs = useMemo(() => jobs.filter((job) => ['uploaded', 'queued', 'parsing'].includes(job.status)), [jobs]);
  const workspaceDefaultProvider = resolveWorkspaceDefaultProvider(workspace?.default_provider_id ?? null, providers);
  const tenantDefaultProvider = providers.find((provider) => provider.is_default) || null;
  const sessions = useMemo(
    () => [...directAskSessions, ...skillSessions].sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()),
    [directAskSessions, skillSessions],
  );

  return (
    <div className="space-y-8">
      <SectionToolbar
        title="Workspace"
        description="Operate this Workspace through Knowledge Bases, Documents, Skills, Runs, and Providers."
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
                Run this Workspace through Knowledge Bases, Documents, Skills, and Runs instead of disconnected feature pages.
              </h1>
              <p className="max-w-3xl text-base leading-7 text-slate-600">
                Welcome back, {user.username || 'operator'}. Knowledge Base is now the formal resource above Document scope, so this console can
                express Skill design, Provider control, and Run review as one Workspace model instead of a loose tool collection.
              </p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <KeyMetric label="Documents" value={overview?.documents ?? 0} hint={`${readyDocuments} ready for chat`} />
            <KeyMetric label="Knowledge Bases" value={knowledgeBases.length} hint="Reusable retrieval scopes" />
            <KeyMetric label="Runs" value={overview?.chat_runs ?? 0} hint={`${failedRuns.length} failed recently`} />
            <KeyMetric
              label="Providers"
              value={providers.length}
              hint={
                workspaceDefaultProvider
                  ? `${workspaceDefaultProvider.name} is workspace default`
                  : tenantDefaultProvider
                    ? `${tenantDefaultProvider.name} is tenant default fallback`
                    : 'No workspace default yet'
              }
            />
          </div>
        </div>

        <div className="grid grid-cols-4 gap-4">
          <div className="surface-soft flex h-full flex-col gap-4 p-4">
            <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
              <Layers3 size={18} className="text-blue-600" />
              <span>Knowledge Base path</span>
            </div>
            <div className="space-y-1">
              <p className="text-lg font-semibold text-slate-900">{knowledgeBases.length} reusable scopes</p>
              <p className="text-sm text-slate-500">{enabledKnowledgeBaseDocuments} enabled Documents are packaged for reuse across this Workspace.</p>
            </div>
            <Link to="/knowledge-bases" className="btn-secondary mt-auto">
              <span>Open Knowledge Bases</span>
              <ArrowRight size={16} />
            </Link>
          </div>
          <div className="surface-soft flex h-full flex-col gap-4 p-4">
            <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
              <Settings2 size={18} className="text-blue-600" />
              <span>Skill path</span>
            </div>
            <div className="space-y-1">
              <p className="text-lg font-semibold text-slate-900">{skills.length} Skills</p>
              <p className="text-sm text-slate-500">Bind prompt, Knowledge Base, and Provider into reusable execution entry points.</p>
            </div>
            <Link to="/skills" className="btn-secondary mt-auto">
              <span>Open Skills</span>
              <ArrowRight size={16} />
            </Link>
          </div>
          <div className="surface-soft flex h-full flex-col gap-4 p-4">
            <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
              <Activity size={18} className="text-blue-600" />
              <span>Run path</span>
            </div>
            <div className="space-y-1">
              <p className="text-lg font-semibold text-slate-900">{overview?.chat_runs ?? 0} Runs</p>
              <p className="text-sm text-slate-500">{failedRuns.length > 0 ? `${failedRuns.length} failed recently.` : 'Review execution history or jump into skill-scoped chat.'}</p>
            </div>
            <div className="mt-auto flex flex-wrap gap-2">
              <Link to="/runs" className="btn-primary">
                <span>View Runs</span>
              </Link>
              <Link to="/chat" className="btn-secondary">
                <span>Open Skill Chat</span>
              </Link>
            </div>
          </div>
          <div className="surface-soft flex h-full flex-col gap-4 p-4">
            <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
              <KeyRound size={18} className="text-blue-600" />
              <span>Provider path</span>
            </div>
            <div className="space-y-1">
              <p className="text-lg font-semibold text-slate-900">{workspaceDefaultProvider?.name || tenantDefaultProvider?.name || 'Backend resolved'}</p>
              <p className="text-sm text-slate-500">
                {workspaceDefaultProvider?.default_model || tenantDefaultProvider?.default_model || 'System default execution may be used'} · {apiKeys.length} workspace API keys issued.
              </p>
            </div>
            <Link to="/providers" className="btn-secondary mt-auto">
              <span>Open Providers</span>
              <ArrowRight size={16} />
            </Link>
          </div>
        </div>
      </GlassPanel>

      <div className="grid grid-cols-[1.1fr_1fr] gap-6">
        <GlassPanel title="Recent work" subtitle="Latest sessions, runs, and ingestion work across the Workspace.">
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
                  {readyDocuments} of {documents.length} Documents are ready. {activeJobs.length > 0 ? `${activeJobs.length} jobs are still processing.` : 'No active parse backlog.'}
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
                  Skill-bound provider overrides runtime test override. Workspace default is {workspaceDefaultProvider?.name || 'not configured'}, then tenant default {tenantDefaultProvider?.name || 'not configured'}, then backend system fallback.
                </p>
              </div>
            </div>
          </div>
        </GlassPanel>
      </div>

      <div className="grid grid-cols-4 gap-6">
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

        <GlassPanel title="Knowledge Base coverage" subtitle="How the current Workspace is packaging Documents into reusable scopes.">
          <div className="space-y-3">
            {knowledgeBases.slice(0, 4).map((knowledgeBase) => (
              <div key={knowledgeBase.id} className="list-row">
                <div>
                  <p className="font-medium text-slate-900">{knowledgeBase.name}</p>
                  <p className="text-sm text-slate-500">{knowledgeBase.documents.filter((document) => document.enabled).length} enabled Documents</p>
                </div>
                <StatusBadge tone={knowledgeBase.status === 'active' ? 'success' : knowledgeBase.status === 'disabled' ? 'warning' : 'default'}>
                  {knowledgeBase.status === 'active' ? 'Enabled' : knowledgeBase.status === 'disabled' ? 'Disabled' : knowledgeBase.status}
                </StatusBadge>
              </div>
            ))}
            {knowledgeBases.length === 0 && <p className="text-sm text-slate-500">No Knowledge Base has been created in this Workspace yet.</p>}
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
                <p className="text-sm text-slate-500">{providers.length} provider profiles available for Workspace use.</p>
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
