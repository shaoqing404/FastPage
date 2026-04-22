import React from 'react';

import type { RunObservationSnapshot } from '../../types';
import { KeyMetric } from '../ui/workbench';

export const RunStepPanel: React.FC<{ snapshot: RunObservationSnapshot | null }> = ({ snapshot }) => {
  if (!snapshot) return null;

  return (
    <div className="grid grid-cols-2 gap-3">
      <KeyMetric label="Current step" value={snapshot.current_step || 'N/A'} />
      <KeyMetric label="Worker" value={snapshot.worker_node_code || 'N/A'} />
      <KeyMetric label="Queue" value={snapshot.queue.queue_ms ? `${snapshot.queue.queue_ms} ms` : 'N/A'} />
      <KeyMetric label="Latency" value={snapshot.timings.total_ms ? `${snapshot.timings.total_ms} ms` : 'N/A'} />
    </div>
  );
};
