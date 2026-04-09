import React from 'react';
import { Plus, ShieldCheck } from 'lucide-react';

import type { ComplianceCheck } from '../../features/compliance/types';
import type { KnowledgeBase } from '../../features/knowledge-bases/types';
import { formatDateTime, cn } from '../../lib/utils';
import { EmptyState, StatusBadge } from '../ui/workbench';

const getCheckStatusTone = (status: string): 'default' | 'success' | 'warning' => {
  if (status === 'active') return 'success';
  if (status === 'disabled') return 'warning';
  return 'default';
};

const formatVerdictLabel = (value: string) =>
  value
    .split('_')
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
    .join(' ');

const summarizeVerdictPolicy = (check: ComplianceCheck) =>
  `${check.verdict_policy.allowed_values.map(formatVerdictLabel).join(' / ')} · Gap -> ${formatVerdictLabel(check.verdict_policy.default_on_gap)}`;

interface ComplianceCheckListProps {
  checks: ComplianceCheck[];
  knowledgeBasesById: Map<string, KnowledgeBase>;
  selectedCheckId: string;
  search: string;
  isLoading: boolean;
  onSelect: (checkId: string) => void;
  onCreate: () => void;
}

export const ComplianceCheckList: React.FC<ComplianceCheckListProps> = ({
  checks,
  knowledgeBasesById,
  selectedCheckId,
  search,
  isLoading,
  onSelect,
  onCreate,
}) => {
  const normalizedSearch = search.trim().toLowerCase();
  const filteredChecks = checks.filter((check) => {
    if (!normalizedSearch) return true;
    const knowledgeBaseName = knowledgeBasesById.get(check.target.knowledge_base_id)?.name || '';
    return [check.name, check.description || '', check.query_template, knowledgeBaseName].some((value) =>
      value.toLowerCase().includes(normalizedSearch),
    );
  });

  if (isLoading) {
    return (
      <div className="empty-state min-h-[280px]">
        <ShieldCheck size={18} className="text-slate-400" />
        <p className="text-sm text-slate-500">Loading Compliance Checks…</p>
      </div>
    );
  }

  if (checks.length === 0) {
    return (
      <EmptyState
        title="No Compliance Checks yet"
        description="Create a saved check definition so operators can manage compliance logic as a reusable product capability."
        action={
          <button type="button" className="btn-primary" onClick={onCreate}>
            <Plus size={16} />
            <span>Create Check</span>
          </button>
        }
      />
    );
  }

  if (filteredChecks.length === 0) {
    return <EmptyState title="No matching checks" description="Try a different search term or create another compliance check." />;
  }

  return (
    <div className="scroll-area max-h-[860px] space-y-3 overflow-auto pr-1">
      {filteredChecks.map((check) => {
        const knowledgeBase = knowledgeBasesById.get(check.target.knowledge_base_id) || null;

        return (
          <button
            type="button"
            key={check.id}
            onClick={() => onSelect(check.id)}
            className={cn('list-row w-full text-left', selectedCheckId === check.id && 'list-row-active')}
          >
            <div className="min-w-0 space-y-3">
              <div className="flex items-center gap-2">
                <ShieldCheck size={16} className="text-slate-400" />
                <p className="truncate font-medium text-slate-900">{check.name}</p>
              </div>

              <div className="space-y-2 text-sm text-slate-500">
                <p className="line-clamp-2">{check.description || check.query_template}</p>
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span>Knowledge Base: {knowledgeBase?.name || 'Unavailable'}</span>
                  <span>Verdict: {summarizeVerdictPolicy(check)}</span>
                </div>
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span>Selection: {check.retrieval_config.selection_mode}</span>
                  <span>Updated {formatDateTime(check.updated_at)}</span>
                </div>
              </div>
            </div>

            <StatusBadge tone={getCheckStatusTone(check.status)}>
              {check.status === 'active' ? 'Enabled' : check.status === 'disabled' ? 'Disabled' : check.status}
            </StatusBadge>
          </button>
        );
      })}
    </div>
  );
};
