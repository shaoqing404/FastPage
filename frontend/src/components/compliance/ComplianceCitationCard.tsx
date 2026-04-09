import React from 'react';

import type { ComplianceCitation } from '../../types';
import { cn } from '../../lib/utils';
import { formatCitationChain } from './utils';

const metaPillClassName = 'rounded-full border border-slate-200 bg-white/75 px-2.5 py-1 text-[11px] font-medium text-slate-600';

export const ComplianceCitationCard: React.FC<{
  citation: ComplianceCitation;
  compact?: boolean;
  className?: string;
}> = ({ citation, compact = false, className }) => (
  <article className={cn('surface-soft space-y-3 p-4', compact && 'space-y-2 p-3.5', className)}>
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full bg-slate-900 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-white">
            {citation.citation_id}
          </span>
          <p className="truncate text-sm font-semibold text-slate-900">{citation.title || 'Untitled citation'}</p>
        </div>
        <p className="text-sm text-slate-500">{citation.source_label}</p>
      </div>
      {citation.page_label && <span className={metaPillClassName}>{citation.page_label}</span>}
    </div>

    <div className="flex flex-wrap gap-2">
      <span className={metaPillClassName}>Document {citation.document_label || citation.document_id || 'Unknown'}</span>
      <span className={metaPillClassName}>Version {citation.version_label || citation.version_id || 'Unknown'}</span>
      <span className={metaPillClassName}>KB {citation.knowledge_base_id || 'N/A'}</span>
      <span className={metaPillClassName}>{citation.node_id ? `Node ${citation.node_id}` : 'Node unavailable'}</span>
    </div>

    <div className="space-y-1 text-sm">
      <p className="text-slate-500">Provenance chain</p>
      <p className="text-slate-900">{formatCitationChain(citation)}</p>
      <p className="text-xs text-slate-500">Snippet {citation.snippet_id}</p>
    </div>
  </article>
);
