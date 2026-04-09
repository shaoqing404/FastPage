import React from 'react';
import { Loader2, Search } from 'lucide-react';

import type { ComplianceCheck, ComplianceRun, KnowledgeBase } from '../../types';
import { formatDateTime, formatRelativeTime } from '../../lib/utils';
import { EmptyState } from '../ui/workbench';
import { ComplianceRunStatusBadge, ComplianceVerdictBadge } from './ComplianceBadges';

type ComplianceRunListProps = {
  runs: ComplianceRun[];
  hasAnyRuns: boolean;
  selectedRunId: string;
  knowledgeBasesById: Record<string, KnowledgeBase>;
  checksById: Record<string, ComplianceCheck>;
  search: string;
  onSearchChange: (value: string) => void;
  statusFilter: string;
  onStatusFilterChange: (value: string) => void;
  modeFilter: string;
  onModeFilterChange: (value: string) => void;
  checkFilter: string;
  onCheckFilterChange: (value: string) => void;
  onSelect: (runId: string) => void;
  isLoading?: boolean;
};

export const ComplianceRunList: React.FC<ComplianceRunListProps> = ({
  runs,
  hasAnyRuns,
  selectedRunId,
  knowledgeBasesById,
  checksById,
  search,
  onSearchChange,
  statusFilter,
  onStatusFilterChange,
  modeFilter,
  onModeFilterChange,
  checkFilter,
  onCheckFilterChange,
  onSelect,
  isLoading = false,
}) => (
  <div className="space-y-4">
    <div className="space-y-3">
      <label className="relative block">
        <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
        <input
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
          className="field pl-10"
          placeholder="Search question, summary, verdict"
        />
      </label>

      <div className="grid gap-3 sm:grid-cols-3">
        <select className="field" value={statusFilter} onChange={(event) => onStatusFilterChange(event.target.value)}>
          <option value="all">All statuses</option>
          <option value="queued">Queued</option>
          <option value="running">Running</option>
          <option value="completed">Completed</option>
          <option value="failed">Failed</option>
        </select>

        <select className="field" value={modeFilter} onChange={(event) => onModeFilterChange(event.target.value)}>
          <option value="all">All modes</option>
          <option value="single_manual">Single manual</option>
          <option value="multi_manual_federated">Multi-manual federated</option>
        </select>

        <select className="field" value={checkFilter} onChange={(event) => onCheckFilterChange(event.target.value)}>
          <option value="all">All run sources</option>
          <option value="adhoc">Ad hoc only</option>
          {Object.values(checksById).map((check) => (
            <option key={check.id} value={check.id}>
              {check.name}
            </option>
          ))}
        </select>
      </div>
    </div>

    {isLoading ? (
      <div className="empty-state min-h-[320px]">
        <Loader2 size={20} className="animate-spin text-blue-600" />
        <p className="text-sm text-slate-500">Loading compliance runs…</p>
      </div>
    ) : runs.length === 0 ? (
      <EmptyState
        title={hasAnyRuns ? 'No runs match the current filters' : 'No compliance runs yet'}
        description={
          hasAnyRuns
            ? 'Adjust the filters or search text to bring matching runs back into the log.'
            : 'Launch an ad hoc run or execute a saved check to build a result history here.'
        }
      />
    ) : (
      <div className="scroll-area max-h-[980px] space-y-3 overflow-auto pr-1">
        {runs.map((run) => {
          const knowledgeBase = knowledgeBasesById[run.target.knowledge_base_id];
          const check = run.compliance_check_id ? checksById[run.compliance_check_id] : null;
          const summary = run.summary || run.answer || (run.status === 'failed' ? run.error?.message : null) || 'No structured summary recorded yet.';
          const factsCount = Object.keys(run.input.facts || {}).length;

          return (
            <button
              type="button"
              key={run.id}
              onClick={() => onSelect(run.id)}
              className={`list-row w-full space-y-3 text-left ${selectedRunId === run.id ? 'list-row-active' : ''}`}
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="space-y-2">
                  <ComplianceRunStatusBadge run={run} />
                  <p className="line-clamp-2 text-sm font-semibold text-slate-900">{run.input.question}</p>
                </div>
                <ComplianceVerdictBadge verdict={run.verdict} />
              </div>

              <p className="line-clamp-2 text-sm text-slate-500">{summary}</p>

              <div className="flex flex-wrap gap-2 text-[11px] font-medium uppercase tracking-[0.14em] text-slate-500">
                <span>{check ? check.name : 'Ad hoc run'}</span>
                <span>{knowledgeBase?.name || run.target.knowledge_base_id}</span>
                <span>{run.mode === 'multi_manual_federated' ? 'Multi-manual' : 'Single manual'}</span>
              </div>

              <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-slate-500">
                <div className="flex flex-wrap gap-3">
                  <span>{run.result.evidence_count} evidence</span>
                  <span>{run.result.gap_count} gaps</span>
                  <span>{run.result.conflict_count} conflicts</span>
                  <span>{run.citations.length} citations</span>
                  <span>{factsCount} facts</span>
                </div>
                <div className="text-right">
                  <p>{formatRelativeTime(run.created_at)}</p>
                  <p className="text-xs">{formatDateTime(run.created_at)}</p>
                </div>
              </div>
            </button>
          );
        })}
      </div>
    )}
  </div>
);
