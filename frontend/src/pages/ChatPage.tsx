import React, { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ArrowRight, BookCopy, MessageSquare, Settings2, Sparkles } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

import { GlassPanel, KeyMetric, SectionToolbar, StatusBadge } from '../components/ui/workbench';
import { chatApi } from '../features/chat/api';
import { documentsApi } from '../features/documents/api';
import { providersApi } from '../features/providers/api';
import { skillsApi } from '../features/skills/api';
import { resolveProviderById } from '../lib/utils';

export const ChatPage: React.FC = () => {
  const navigate = useNavigate();
  const { data: skills = [] } = useQuery({ queryKey: ['skills'], queryFn: skillsApi.list });
  const { data: providers = [] } = useQuery({ queryKey: ['providers'], queryFn: providersApi.list });
  const { data: documents = [] } = useQuery({ queryKey: ['documents'], queryFn: documentsApi.list });
  const { data: runs = [] } = useQuery({ queryKey: ['all-runs'], queryFn: () => chatApi.listRuns() });

  const skillStats = useMemo(() => {
    const runsBySkill = new Map<string, { runCount: number; sessionIds: Set<string>; latestQuestion: string | null }>();
    for (const run of runs) {
      if (!run.skill_id) continue;
      const entry = runsBySkill.get(run.skill_id) || { runCount: 0, sessionIds: new Set<string>(), latestQuestion: null };
      entry.runCount += 1;
      if (run.session_id) entry.sessionIds.add(run.session_id);
      if (!entry.latestQuestion) entry.latestQuestion = run.question;
      runsBySkill.set(run.skill_id, entry);
    }
    return runsBySkill;
  }, [runs]);

  return (
    <div className="space-y-8">
      <SectionToolbar
        title="Chat"
        description="Start from a skill card, then drop into a dedicated chat workspace for that skill."
      />

      <div className="grid grid-cols-4 gap-4">
        <KeyMetric label="Skills" value={skills.length} hint="Available chat entry points" />
        <KeyMetric label="Skill sessions" value={Array.from(new Set(runs.map((run) => run.session_id).filter(Boolean))).length} hint="Sessions discovered from existing skill runs" />
        <KeyMetric label="Skill runs" value={runs.filter((run) => run.skill_id).length} hint="Chat runs attached to skills" />
        <KeyMetric label="Ready docs" value={documents.filter((document) => document.status === 'index_ready').length} hint="Usable by skill chat" />
      </div>

      <GlassPanel title="Choose a skill" subtitle="The first layer is now skill-first. Open a card to enter that skill's dedicated chat workspace.">
        <div className="grid grid-cols-3 gap-5">
          {skills.map((skill) => {
            const provider = resolveProviderById(skill.provider_id ?? null, providers);
            const linkedDocs = skill.document_ids
              .map((documentId) => documents.find((document) => document.id === documentId)?.display_name)
              .filter((value): value is string => Boolean(value));
            const stats = skillStats.get(skill.id);

            return (
              <button
                key={skill.id}
                type="button"
                onClick={() => navigate(`/chat/skills/${skill.id}`)}
                className="glass-panel overflow-visible text-left transition hover:-translate-y-0.5"
              >
                <div className="glass-panel-body space-y-5">
                  <div className="flex items-start justify-between gap-4">
                    <div className="space-y-2">
                      <div className="inline-flex h-11 w-11 items-center justify-center rounded-[18px] bg-white/85 text-blue-600 shadow-sm">
                        <Settings2 size={18} />
                      </div>
                      <div>
                        <p className="text-lg font-semibold tracking-[-0.02em] text-slate-900">{skill.name}</p>
                        <p className="mt-1 line-clamp-2 text-sm text-slate-500">{skill.system_prompt}</p>
                      </div>
                    </div>
                    <ArrowRight size={18} className="mt-1 text-slate-400" />
                  </div>

                  <div className="flex flex-wrap gap-2">
                    <StatusBadge tone="accent">{provider?.name || 'Tenant default provider'}</StatusBadge>
                    <StatusBadge tone="default">{skill.model}</StatusBadge>
                  </div>

                  <div className="grid grid-cols-3 gap-3">
                    <div className="surface-soft p-3">
                      <p className="metric-label">Docs</p>
                      <p className="mt-2 text-lg font-semibold text-slate-900">{linkedDocs.length}</p>
                    </div>
                    <div className="surface-soft p-3">
                      <p className="metric-label">Runs</p>
                      <p className="mt-2 text-lg font-semibold text-slate-900">{stats?.runCount || 0}</p>
                    </div>
                    <div className="surface-soft p-3">
                      <p className="metric-label">Sessions</p>
                      <p className="mt-2 text-lg font-semibold text-slate-900">{stats?.sessionIds.size || 0}</p>
                    </div>
                  </div>

                  <div className="space-y-3 rounded-[24px] border border-white/75 bg-white/58 p-4">
                    <div className="flex items-center gap-2 text-sm text-slate-600">
                      <BookCopy size={16} />
                      <span>{linkedDocs.length > 0 ? linkedDocs.join(' · ') : 'No linked documents'}</span>
                    </div>
                    <div className="flex items-center gap-2 text-sm text-slate-500">
                      <MessageSquare size={16} />
                      <span>{stats?.latestQuestion || 'No questions asked yet.'}</span>
                    </div>
                  </div>
                </div>
              </button>
            );
          })}

          {skills.length === 0 && (
            <div className="col-span-3 empty-state min-h-[260px]">
              <Sparkles size={22} className="text-blue-600" />
              <p className="text-base font-medium text-slate-900">No skills available</p>
              <p className="text-sm text-slate-500">Create a skill first, then chat through its dedicated route.</p>
            </div>
          )}
        </div>
      </GlassPanel>
    </div>
  );
};
