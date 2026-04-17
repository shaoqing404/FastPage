import React from 'react';
import { BookMarked, Database } from 'lucide-react';

import { EmptyState, StatusBadge } from '../ui/workbench';
import { formatDateTime } from '../../lib/utils';
import { cn } from '../../lib/utils';
import type { KnowledgeBase } from '../../features/knowledge-bases/types';

const getKnowledgeBaseStatusTone = (status: string): 'default' | 'success' | 'warning' => {
  if (status === 'active') return 'success';
  if (status === 'disabled') return 'warning';
  return 'default';
};

const getEnabledDocumentCount = (knowledgeBase: KnowledgeBase) => knowledgeBase.documents.filter((document) => document.enabled).length;

interface KnowledgeBaseListProps {
  knowledgeBases: KnowledgeBase[];
  selectedKnowledgeBaseId: string;
  search: string;
  isLoading: boolean;
  onSelect: (knowledgeBaseId: string) => void;
  onCreate: () => void;
}

export const KnowledgeBaseList: React.FC<KnowledgeBaseListProps> = ({
  knowledgeBases,
  selectedKnowledgeBaseId,
  search,
  isLoading,
  onSelect,
  onCreate,
}) => {
  const normalizedSearch = search.trim().toLowerCase();
  const filteredKnowledgeBases = knowledgeBases.filter((knowledgeBase) => {
    if (!normalizedSearch) return true;
    return (
      knowledgeBase.name.toLowerCase().includes(normalizedSearch) ||
      knowledgeBase.description?.toLowerCase().includes(normalizedSearch)
    );
  });

  if (isLoading) {
    return (
      <div className="empty-state min-h-[260px]">
        <Database size={18} className="text-slate-400" />
        <p className="text-sm text-slate-500">Loading Knowledge Bases…</p>
      </div>
    );
  }

  if (knowledgeBases.length === 0) {
    return (
      <EmptyState
        title="No Knowledge Bases yet"
        description="Create a Knowledge Base for this Workspace so Documents can be grouped into a reusable retrieval scope."
        action={
          <button type="button" className="btn-primary" onClick={onCreate}>
            <BookMarked size={16} />
            <span>Create Knowledge Base</span>
          </button>
        }
      />
    );
  }

  if (filteredKnowledgeBases.length === 0) {
    return <EmptyState title="No matching Knowledge Bases" description="Try a different search term or create another Knowledge Base." />;
  }

  return (
    <div className="scroll-area max-h-[840px] space-y-3 overflow-auto pr-1">
      {filteredKnowledgeBases.map((knowledgeBase) => {
        const enabledDocumentCount = getEnabledDocumentCount(knowledgeBase);

        return (
          <button
            type="button"
            key={knowledgeBase.id}
            onClick={() => onSelect(knowledgeBase.id)}
            className={cn('list-row w-full text-left', selectedKnowledgeBaseId === knowledgeBase.id && 'list-row-active')}
          >
            <div className="min-w-0 space-y-2">
              <div className="flex items-center gap-2">
                <BookMarked size={16} className="text-slate-400" />
                <p className="truncate font-medium text-slate-900">{knowledgeBase.name}</p>
                <StatusBadge tone={knowledgeBase.visibility === 'workspace_edit' ? 'accent' : knowledgeBase.visibility === 'workspace_read' ? 'default' : 'warning'}>
                  {knowledgeBase.visibility}
                </StatusBadge>
              </div>
              <p className="line-clamp-2 text-sm text-slate-500">{knowledgeBase.description || 'No description yet.'}</p>
              <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                <span>{enabledDocumentCount} enabled Documents</span>
                <span>{knowledgeBase.documents.length} total members</span>
                <span>Updated {formatDateTime(knowledgeBase.updated_at)}</span>
              </div>
            </div>
            <StatusBadge tone={getKnowledgeBaseStatusTone(knowledgeBase.status)}>
              {knowledgeBase.status === 'active' ? 'Enabled' : knowledgeBase.status === 'disabled' ? 'Disabled' : knowledgeBase.status}
            </StatusBadge>
          </button>
        );
      })}
    </div>
  );
};
