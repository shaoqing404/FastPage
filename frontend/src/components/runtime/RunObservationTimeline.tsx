import React from 'react';

import type { RunObservationSnapshot } from '../../types';
import { formatDateTime } from '../../lib/utils';
import { EmptyState, StatusBadge } from '../ui/workbench';
import { RunStepPanel } from './RunStepPanel';

const summarizePayload = (payload: Record<string, unknown>) => {
  if (payload.delta && typeof payload.delta === 'object' && 'text' in payload.delta) {
    return String((payload.delta as { text?: string }).text || '');
  }
  if (payload.prompt_text && typeof payload.prompt_text === 'object' && 'text' in payload.prompt_text) {
    return String((payload.prompt_text as { text?: string }).text || '');
  }
  if (payload.error && typeof payload.error === 'object' && 'text' in payload.error) {
    return String((payload.error as { text?: string }).text || '');
  }
  if (payload.response_text && typeof payload.response_text === 'object' && 'text' in payload.response_text) {
    return String((payload.response_text as { text?: string }).text || '');
  }
  const preview = JSON.stringify(payload);
  return preview.length > 220 ? `${preview.slice(0, 220)}…` : preview;
};

export const RunObservationTimeline: React.FC<{
  snapshot: RunObservationSnapshot | null;
  title?: string;
  emptyTitle?: string;
  emptyDescription?: string;
}> = ({ snapshot, title = 'Runtime timeline', emptyTitle = 'No runtime timeline yet', emptyDescription = 'Run this action to populate live runtime observations.' }) => {
  if (!snapshot || snapshot.events.length === 0) {
    return <EmptyState title={emptyTitle} description={emptyDescription} />;
  }

  return (
    <div className="space-y-4">
      <div>
        <p className="text-sm font-semibold text-slate-900">{title}</p>
        <p className="text-sm text-slate-500">Live backend execution trail for this run.</p>
      </div>

      <RunStepPanel snapshot={snapshot} />

      {snapshot.partial_answer && (
        <div className="surface-soft p-4">
          <p className="metric-label">Partial answer</p>
          <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-700">{snapshot.partial_answer}</p>
        </div>
      )}

      <div className="space-y-3">
        {snapshot.events.map((event) => (
          <div key={event.id} className="surface-soft p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <StatusBadge tone={event.event_type.includes('failed') ? 'danger' : event.event_type.includes('completed') ? 'success' : 'accent'}>
                  {event.event_type}
                </StatusBadge>
                {event.step ? <span className="text-xs font-medium text-slate-500">{event.step}</span> : null}
                {event.status ? <span className="text-xs text-slate-400">{event.status}</span> : null}
              </div>
              <span className="text-xs text-slate-400">{formatDateTime(event.created_at)}</span>
            </div>
            <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-700">{summarizePayload(event.payload)}</p>
          </div>
        ))}
      </div>
    </div>
  );
};
