import React from 'react';
import { StatusBadge } from '../ui/workbench';
import type { FastSearchNode } from '../../features/search/api';

interface FastSearchNodeListProps {
  nodes: FastSearchNode[];
}

export const FastSearchNodeList: React.FC<FastSearchNodeListProps> = ({ nodes }) => {
  if (!nodes || nodes.length === 0) {
    return null;
  }

  return (
    <div className="space-y-4">
      {nodes.map((node, i) => (
        <div key={`${node.node_id}-${i}`} className="surface-soft p-4 space-y-2 rounded-xl">
          <div className="flex items-start justify-between">
            <div className="flex-1 min-w-0 pr-4">
              <h4 className="text-sm font-semibold text-slate-900 truncate" title={node.title || 'Untitled Node'}>
                {node.title || 'Untitled Node'}
              </h4>
              <div className="flex items-center gap-3 mt-1 text-xs text-slate-500">
                <span>Node ID: {node.node_id}</span>
                {(node.page_start || node.page_end) && (
                  <span>Page {node.page_start}{node.page_end && node.page_end !== node.page_start ? `-${node.page_end}` : ''}</span>
                )}
                <span>Score: {node.score.toFixed(4)}</span>
              </div>
            </div>
            <StatusBadge tone={node.source === 'document_routing_nodes' ? 'success' : 'accent'}>
              {node.source.replace(/_/g, ' ')}
            </StatusBadge>
          </div>
          {(node.snippet || node.summary) && (
            <p className="text-sm text-slate-700 leading-relaxed bg-white/50 p-3 rounded-lg border border-slate-100 mt-2">
              {node.snippet || node.summary}
            </p>
          )}
        </div>
      ))}
    </div>
  );
};
