import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { ArrowDownUp, BookCopy, Loader2, Pin, Plus, Trash2 } from 'lucide-react';

import { documentsApi } from '../../features/documents/api';
import type { Document, DocumentVersion } from '../../types';
import type { KnowledgeBaseDocumentBinding } from '../../features/knowledge-bases/types';
import { EmptyState, Field, InlineAlert, StatusBadge } from '../ui/workbench';

const getDocumentTone = (status: Document['status']): 'accent' | 'danger' | 'success' => {
  if (status === 'index_ready') return 'success';
  if (status === 'failed') return 'danger';
  return 'accent';
};

const getMembershipTone = (enabled: boolean): 'success' | 'warning' => (enabled ? 'success' : 'warning');

interface KnowledgeBaseMembershipEditorProps {
  documents: Document[];
  membership: KnowledgeBaseDocumentBinding[];
  disabled?: boolean;
  savePending?: boolean;
  error?: string;
  onAddDocument: (documentId: string) => void;
  onRemoveDocument: (documentId: string) => void;
  onMembershipChange: (documentId: string, update: Partial<KnowledgeBaseDocumentBinding>) => void;
  onSave: () => void;
}

export const KnowledgeBaseMembershipEditor: React.FC<KnowledgeBaseMembershipEditorProps> = ({
  documents,
  membership,
  disabled = false,
  savePending = false,
  error,
  onAddDocument,
  onRemoveDocument,
  onMembershipChange,
  onSave,
}) => {
  const sortedMembership = [...membership].sort((left, right) => {
    if (left.sort_order !== right.sort_order) return left.sort_order - right.sort_order;
    return left.document_id.localeCompare(right.document_id);
  });

  const memberDocumentIds = new Set(sortedMembership.map((item) => item.document_id));
  const availableDocuments = documents
    .filter((document) => !memberDocumentIds.has(document.id))
    .sort((left, right) => left.display_name.localeCompare(right.display_name));

  return (
    <div className="space-y-6">
      {error && (
        <InlineAlert tone="danger" title="Knowledge Base membership failed to save">
          {error}
        </InlineAlert>
      )}

      <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-sm font-medium text-slate-900">Documents in this Knowledge Base</p>
              <p className="text-sm text-slate-500">Keep membership readable with per-Document status, pinning, labels, and ordering.</p>
            </div>
            <button type="button" className="btn-primary" onClick={onSave} disabled={disabled || savePending}>
              {savePending ? <Loader2 size={16} className="animate-spin" /> : <ArrowDownUp size={16} />}
              <span>{savePending ? 'Saving membership…' : 'Save membership'}</span>
            </button>
          </div>

          {sortedMembership.length === 0 ? (
            <EmptyState
              title="No Documents in this Knowledge Base"
              description="Add one or more Documents from this Workspace so the Knowledge Base becomes a reusable retrieval scope."
            />
          ) : (
            sortedMembership.map((item) => {
              const document = documents.find((candidate) => candidate.id === item.document_id) || null;

              return (
                <MembershipRow
                  key={item.document_id}
                  document={document}
                  membership={item}
                  disabled={disabled}
                  onChange={(update) => onMembershipChange(item.document_id, update)}
                  onRemove={() => onRemoveDocument(item.document_id)}
                />
              );
            })
          )}
        </div>

        <div className="space-y-3">
          <div>
            <p className="text-sm font-medium text-slate-900">Add Workspace Documents</p>
            <p className="text-sm text-slate-500">Documents stay reusable. Membership here does not duplicate the underlying Document asset.</p>
          </div>

          {documents.length === 0 ? (
            <EmptyState title="No Documents in this Workspace" description="Upload a Document first, then attach it to a Knowledge Base." />
          ) : availableDocuments.length === 0 ? (
            <EmptyState title="All Documents already added" description="This Knowledge Base already references every available Document in the current Workspace." />
          ) : (
            <div className="space-y-3">
              {availableDocuments.map((document) => (
                <div key={document.id} className="surface-soft flex items-center justify-between gap-3 p-4">
                  <div className="min-w-0 space-y-2">
                    <div className="flex items-center gap-2">
                      <BookCopy size={16} className="text-slate-400" />
                      <p className="truncate font-medium text-slate-900">{document.display_name}</p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <StatusBadge tone={getDocumentTone(document.status)}>{document.status}</StatusBadge>
                      <span className="text-sm text-slate-500">{document.source_filename}</span>
                    </div>
                  </div>
                  <button type="button" className="btn-secondary" onClick={() => onAddDocument(document.id)} disabled={disabled}>
                    <Plus size={16} />
                    <span>Add</span>
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

const MembershipRow: React.FC<{
  document: Document | null;
  membership: KnowledgeBaseDocumentBinding;
  disabled: boolean;
  onChange: (update: Partial<KnowledgeBaseDocumentBinding>) => void;
  onRemove: () => void;
}> = ({ document, membership, disabled, onChange, onRemove }) => {
  const { data: versions = [], isLoading: versionsLoading } = useQuery({
    queryKey: ['document-versions', membership.document_id],
    queryFn: () => documentsApi.listVersions(membership.document_id),
    enabled: Boolean(document),
  });

  return (
    <div className="surface-soft space-y-4 p-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <BookCopy size={16} className="text-slate-400" />
            <p className="font-medium text-slate-900">{document?.display_name || membership.document_id}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <StatusBadge tone={getMembershipTone(membership.enabled)}>{membership.enabled ? 'Enabled' : 'Disabled'}</StatusBadge>
            {document && <StatusBadge tone={getDocumentTone(document.status)}>{document.status}</StatusBadge>}
            {membership.label && <StatusBadge>{membership.label}</StatusBadge>}
          </div>
          <p className="text-sm text-slate-500">{document?.source_filename || 'Document metadata unavailable in current Workspace listing.'}</p>
        </div>

        <button type="button" className="btn-ghost text-red-600" onClick={onRemove} disabled={disabled}>
          <Trash2 size={16} />
          <span>Remove</span>
        </button>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Field label="Membership status">
          <select
            className="field"
            value={membership.enabled ? 'enabled' : 'disabled'}
            disabled={disabled}
            onChange={(event) => onChange({ enabled: event.target.value === 'enabled' })}
          >
            <option value="enabled">Enabled</option>
            <option value="disabled">Disabled</option>
          </select>
        </Field>

        <Field label="Label" hint="Optional operator-facing alias inside this Knowledge Base.">
          <input
            className="field"
            value={membership.label || ''}
            disabled={disabled}
            placeholder="Company SOP"
            onChange={(event) => onChange({ label: event.target.value.trim() ? event.target.value : null })}
          />
        </Field>

        <Field label="Sort order" hint="Lower values appear first in the Knowledge Base.">
          <input
            className="field"
            type="number"
            value={membership.sort_order}
            disabled={disabled}
            onChange={(event) => onChange({ sort_order: Number(event.target.value) || 0 })}
          />
        </Field>

        <Field label="Pinned version" hint="Leave unpinned to follow the active Document version.">
          <select
            className="field"
            value={membership.pinned_version_id || ''}
            disabled={disabled || versionsLoading}
            onChange={(event) => onChange({ pinned_version_id: event.target.value || null })}
          >
            <option value="">Use active version</option>
            {versions.map((version) => (
              <option key={version.id} value={version.id}>
                {describeVersion(version)}
              </option>
            ))}
          </select>
        </Field>
      </div>

      <div className="flex flex-wrap gap-3 text-sm text-slate-500">
        <div className="inline-flex items-center gap-2">
          <Pin size={14} />
          <span>{membership.pinned_version_id ? `Pinned to ${shortVersionId(membership.pinned_version_id)}` : 'Following active version'}</span>
        </div>
        {versionsLoading && (
          <div className="inline-flex items-center gap-2">
            <Loader2 size={14} className="animate-spin" />
            <span>Loading versions…</span>
          </div>
        )}
      </div>
    </div>
  );
};

const describeVersion = (version: DocumentVersion) => `Version ${version.version_no} · ${version.parse_status}`;

const shortVersionId = (versionId: string) => versionId.slice(0, 8);
