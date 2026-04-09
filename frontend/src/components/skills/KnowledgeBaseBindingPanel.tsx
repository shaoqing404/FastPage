import React from 'react';

import type { Document } from '../../types';
import { InlineAlert, StatusBadge } from '../ui/workbench';
import type { KnowledgeBaseSummary } from './types';
import { getEnabledKnowledgeBaseDocuments, resolveDocumentDisplayName } from './types';

export const KnowledgeBaseBindingPanel: React.FC<{
  knowledgeBase: KnowledgeBaseSummary | null;
  knowledgeBasesLoaded: boolean;
  knowledgeBasesError?: string;
  onRetry?: () => void;
  documentsById: Map<string, Document>;
  legacyDocumentIds: string[];
}> = ({ knowledgeBase, knowledgeBasesLoaded, knowledgeBasesError, onRetry, documentsById, legacyDocumentIds }) => {
  if (knowledgeBasesError) {
    return (
      <InlineAlert
        tone="danger"
        title="Knowledge bases failed to load"
        action={
          onRetry ? (
            <button type="button" className="btn-secondary" onClick={onRetry}>
              Retry
            </button>
          ) : null
        }
      >
        {knowledgeBasesError}
      </InlineAlert>
    );
  }

  if (!knowledgeBasesLoaded) {
    return (
      <div className="rounded-[24px] border border-white/75 bg-white/58 p-4 text-sm text-slate-500">
        Loading knowledge base context…
      </div>
    );
  }

  if (!knowledgeBase) {
    return (
      <div className="space-y-3 rounded-[24px] border border-amber-200 bg-amber-50/80 p-4">
        <div className="space-y-1">
          <p className="text-sm font-medium text-amber-950">Skill binding is knowledge-base-first</p>
          <p className="text-sm text-amber-800">
            Select a knowledge base before saving. Raw <code>document_ids</code> remain compatibility-only and are not the primary workflow anymore.
          </p>
        </div>
        {legacyDocumentIds.length > 0 && (
          <div className="space-y-2">
            <p className="text-xs font-medium uppercase tracking-[0.18em] text-amber-700">Legacy shim snapshot</p>
            <div className="flex flex-wrap gap-2">
              {legacyDocumentIds.map((documentId) => (
                <StatusBadge key={documentId}>
                  {resolveDocumentDisplayName(documentId, documentsById)}
                </StatusBadge>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  }

  const enabledDocuments = getEnabledKnowledgeBaseDocuments(knowledgeBase);

  return (
    <div className="space-y-4 rounded-[24px] border border-white/75 bg-white/58 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <p className="text-sm font-medium text-slate-900">{knowledgeBase.name}</p>
          <p className="text-sm text-slate-500">{knowledgeBase.description || 'No knowledge base description provided.'}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <StatusBadge tone={knowledgeBase.status === 'active' ? 'success' : 'warning'}>{knowledgeBase.status}</StatusBadge>
          <StatusBadge tone="accent">{enabledDocuments.length} enabled docs</StatusBadge>
          <StatusBadge>{knowledgeBase.documents.length} total docs</StatusBadge>
        </div>
      </div>

      <InlineAlert tone="success" title="Compatibility shim">
        Saving this skill will keep <code>document_ids</code> synchronized from the enabled knowledge base documents for current runtime compatibility.
      </InlineAlert>

      {enabledDocuments.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {enabledDocuments.map((document) => (
            <StatusBadge key={document.document_id}>
              {document.label || resolveDocumentDisplayName(document.document_id, documentsById)}
            </StatusBadge>
          ))}
        </div>
      ) : (
        <div className="rounded-[20px] border border-dashed border-slate-200 bg-white/70 px-4 py-3 text-sm text-slate-500">
          This knowledge base has no enabled documents. The skill can still be configured, but retrieval will have no active manuals.
        </div>
      )}
    </div>
  );
};
