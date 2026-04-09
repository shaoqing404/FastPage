import React from 'react';

import type { ComplianceRun, ComplianceVerdict } from '../../types';
import { cn } from '../../lib/utils';
import { StatusBadge } from '../ui/workbench';
import { formatComplianceLabel, getRunStatusTone, getVerdictTone } from './utils';

export const ComplianceRunStatusBadge: React.FC<{
  run: Pick<ComplianceRun, 'status' | 'raw_status'>;
}> = ({ run }) => (
  <div className="flex flex-wrap items-center gap-2">
    <StatusBadge tone={getRunStatusTone(run.status)}>{formatComplianceLabel(run.status)}</StatusBadge>
    {run.raw_status && run.raw_status !== run.status && (
      <span className="rounded-full border border-slate-200 bg-white/70 px-2.5 py-1 text-[11px] font-medium uppercase tracking-[0.14em] text-slate-500">
        {formatComplianceLabel(run.raw_status)}
      </span>
    )}
  </div>
);

export const ComplianceVerdictBadge: React.FC<{
  verdict: ComplianceVerdict | null | undefined;
  className?: string;
}> = ({ verdict, className }) =>
  verdict ? (
    <StatusBadge tone={getVerdictTone(verdict)}>
      <span className={cn('inline-flex items-center gap-1', className)}>{formatComplianceLabel(verdict)}</span>
    </StatusBadge>
  ) : (
    <StatusBadge tone="default">
      <span className={cn('inline-flex items-center gap-1', className)}>No Verdict</span>
    </StatusBadge>
  );
