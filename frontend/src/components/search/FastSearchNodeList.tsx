import React, { useState } from 'react';
import { Check, Copy } from 'lucide-react';
import { StatusBadge } from '../ui/workbench';
import type { FastSearchNode } from '../../features/search/api';

interface FastSearchNodeListProps {
  nodes: FastSearchNode[];
}

const formatPageRange = (node: FastSearchNode) => {
  if (!node.page_start && !node.page_end) return 'N/A';
  if (node.page_start && node.page_end && node.page_end !== node.page_start) return `${node.page_start}-${node.page_end}`;
  return String(node.page_start || node.page_end);
};

const formatNodeBlock = (node: FastSearchNode, index: number) => [
  `# Fast Search Result ${index + 1}`,
  `Title: ${node.title || 'Untitled Node'}`,
  `Node ID: ${node.node_id}`,
  `Pages: ${formatPageRange(node)}`,
  `Score: ${Number.isFinite(node.score) ? node.score.toFixed(4) : 'N/A'}`,
  `Source: ${node.source}`,
  '',
  'Snippet:',
  node.snippet || node.summary || '',
].join('\n').trim();

const writeClipboardText = async (text: string) => {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.setAttribute('readonly', 'true');
  textarea.style.position = 'fixed';
  textarea.style.left = '-9999px';
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand('copy');
  document.body.removeChild(textarea);
};

export const FastSearchNodeList: React.FC<FastSearchNodeListProps> = ({ nodes }) => {
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  if (!nodes || nodes.length === 0) {
    return null;
  }

  const copyText = async (key: string, text: string) => {
    await writeClipboardText(text);
    setCopiedKey(key);
    window.setTimeout(() => setCopiedKey((current) => (current === key ? null : current)), 1400);
  };

  const copyAll = () => {
    void copyText(
      'all',
      nodes.map((node, index) => formatNodeBlock(node, index)).join('\n\n---\n\n'),
    );
  };

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <button type="button" className="btn-secondary" onClick={copyAll}>
          {copiedKey === 'all' ? <Check size={14} /> : <Copy size={14} />}
          <span>{copiedKey === 'all' ? '已复制全部' : '复制全部结果'}</span>
        </button>
      </div>
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
            <div className="flex shrink-0 items-center gap-2">
              <button
                type="button"
                className="btn-secondary px-3 py-1.5 text-xs"
                onClick={() => void copyText(`${node.node_id}-${i}`, formatNodeBlock(node, i))}
              >
                {copiedKey === `${node.node_id}-${i}` ? <Check size={13} /> : <Copy size={13} />}
                <span>{copiedKey === `${node.node_id}-${i}` ? '已复制' : '复制块'}</span>
              </button>
              <StatusBadge tone={node.source === 'document_routing_nodes' ? 'success' : 'accent'}>
                {node.source.replace(/_/g, ' ')}
              </StatusBadge>
            </div>
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
