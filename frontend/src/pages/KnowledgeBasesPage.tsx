import React, { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Layers3, Loader2, Plus, Save, Workflow } from 'lucide-react';

import { KnowledgeBaseList } from '../components/knowledge-bases/KnowledgeBaseList';
import { KnowledgeBaseMembershipEditor } from '../components/knowledge-bases/KnowledgeBaseMembershipEditor';
import { EmptyState, Field, GlassPanel, InlineAlert, KeyMetric, SectionToolbar, StatusBadge } from '../components/ui/workbench';
import { documentsApi } from '../features/documents/api';
import { knowledgeBasesApi } from '../features/knowledge-bases/api';
import type { KnowledgeBase, KnowledgeBaseDocumentBinding, KnowledgeBaseMutationPayload } from '../features/knowledge-bases/types';
import { formatDateTime, getErrorMessage } from '../lib/utils';

type KnowledgeBaseFormState = {
  name: string;
  description: string;
  status: string;
};

const EMPTY_FORM: KnowledgeBaseFormState = {
  name: '',
  description: '',
  status: 'active',
};

export const KnowledgeBasesPage: React.FC = () => {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState('');
  const [selectedKnowledgeBaseId, setSelectedKnowledgeBaseId] = useState('');
  const [isCreateMode, setIsCreateMode] = useState(false);
  const [draftSourceKey, setDraftSourceKey] = useState('empty');
  const [draftFormState, setDraftFormState] = useState<KnowledgeBaseFormState>(EMPTY_FORM);
  const [draftMembership, setDraftMembership] = useState<KnowledgeBaseDocumentBinding[]>([]);
  const [metadataError, setMetadataError] = useState('');
  const [membershipError, setMembershipError] = useState('');

  const {
    data: knowledgeBases = [],
    isLoading: knowledgeBasesLoading,
    error: knowledgeBasesError,
  } = useQuery({
    queryKey: ['knowledge-bases'],
    queryFn: () => knowledgeBasesApi.list(),
  });
  const {
    data: documents = [],
    isLoading: documentsLoading,
    error: documentsError,
  } = useQuery({
    queryKey: ['documents'],
    queryFn: documentsApi.list,
  });

  const effectiveSelectedKnowledgeBaseId = useMemo(() => {
    if (isCreateMode) return '';
    if (selectedKnowledgeBaseId && knowledgeBases.some((knowledgeBase) => knowledgeBase.id === selectedKnowledgeBaseId)) {
      return selectedKnowledgeBaseId;
    }
    return knowledgeBases[0]?.id || '';
  }, [isCreateMode, knowledgeBases, selectedKnowledgeBaseId]);

  const selectedKnowledgeBase = useMemo(
    () => knowledgeBases.find((knowledgeBase) => knowledgeBase.id === effectiveSelectedKnowledgeBaseId) || null,
    [effectiveSelectedKnowledgeBaseId, knowledgeBases],
  );

  const currentSourceKey = isCreateMode ? 'create' : effectiveSelectedKnowledgeBaseId || 'empty';
  const formState =
    draftSourceKey === currentSourceKey ? draftFormState : isCreateMode ? EMPTY_FORM : deriveFormState(selectedKnowledgeBase);
  const membershipDraft =
    draftSourceKey === currentSourceKey ? draftMembership : isCreateMode ? [] : deriveMembership(selectedKnowledgeBase);

  const createMutation = useMutation({
    mutationFn: (payload: KnowledgeBaseMutationPayload) => knowledgeBasesApi.create(payload),
    onSuccess: (knowledgeBase) => {
      setMetadataError('');
      setMembershipError('');
      setIsCreateMode(false);
      setSelectedKnowledgeBaseId(knowledgeBase.id);
      setDraftSourceKey('empty');
      queryClient.invalidateQueries({ queryKey: ['knowledge-bases'] });
    },
    onError: (error: unknown) => {
      setMetadataError(getErrorMessage(error, 'Knowledge Base create failed'));
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ knowledgeBaseId, payload }: { knowledgeBaseId: string; payload: Partial<KnowledgeBaseMutationPayload> }) =>
      knowledgeBasesApi.update(knowledgeBaseId, payload),
    onSuccess: () => {
      setMetadataError('');
      setDraftSourceKey('empty');
      queryClient.invalidateQueries({ queryKey: ['knowledge-bases'] });
    },
    onError: (error: unknown) => {
      setMetadataError(getErrorMessage(error, 'Knowledge Base update failed'));
    },
  });

  const replaceDocumentsMutation = useMutation({
    mutationFn: ({ knowledgeBaseId, documents: nextDocuments }: { knowledgeBaseId: string; documents: KnowledgeBaseDocumentBinding[] }) =>
      knowledgeBasesApi.replaceDocuments(knowledgeBaseId, nextDocuments),
    onSuccess: () => {
      setMembershipError('');
      setDraftSourceKey('empty');
      queryClient.invalidateQueries({ queryKey: ['knowledge-bases'] });
    },
    onError: (error: unknown) => {
      setMembershipError(getErrorMessage(error, 'Knowledge Base membership save failed'));
    },
  });

  const totalEnabledMemberships = useMemo(
    () => knowledgeBases.reduce((count, knowledgeBase) => count + knowledgeBase.documents.filter((document) => document.enabled).length, 0),
    [knowledgeBases],
  );
  const documentMembershipCounts = useMemo(() => {
    const counts = new Map<string, number>();
    knowledgeBases.forEach((knowledgeBase) => {
      knowledgeBase.documents.forEach((document) => {
        counts.set(document.document_id, (counts.get(document.document_id) || 0) + 1);
      });
    });
    return counts;
  }, [knowledgeBases]);
  const unassignedDocuments = useMemo(
    () => documents.filter((document) => !documentMembershipCounts.has(document.id)).length,
    [documentMembershipCounts, documents],
  );

  const primaryError =
    knowledgeBasesError || documentsError
      ? [knowledgeBasesError, documentsError].filter(Boolean).map((error) => getErrorMessage(error, 'Failed to load page data')).join(' · ')
      : '';

  const handleSelectKnowledgeBase = (knowledgeBaseId: string) => {
    setIsCreateMode(false);
    setDraftSourceKey('empty');
    setMetadataError('');
    setMembershipError('');
    setSelectedKnowledgeBaseId(knowledgeBaseId);
  };

  const handleCreateMode = () => {
    setIsCreateMode(true);
    setDraftSourceKey('empty');
    setSelectedKnowledgeBaseId('');
    setMetadataError('');
    setMembershipError('');
  };

  const handleFormChange = (field: keyof KnowledgeBaseFormState, value: string) => {
    stageDraft(currentSourceKey, { ...formState, [field]: value }, membershipDraft, setDraftSourceKey, setDraftFormState, setDraftMembership);
  };

  const handleMembershipChange = (documentId: string, update: Partial<KnowledgeBaseDocumentBinding>) => {
    stageDraft(
      currentSourceKey,
      formState,
      sortMembership(membershipDraft.map((item) => (item.document_id === documentId ? { ...item, ...update } : item))),
      setDraftSourceKey,
      setDraftFormState,
      setDraftMembership,
    );
  };

  const handleAddDocument = (documentId: string) => {
    stageDraft(
      currentSourceKey,
      formState,
      sortMembership([
        ...membershipDraft,
        {
          document_id: documentId,
          pinned_version_id: null,
          enabled: true,
          label: null,
          sort_order: membershipDraft.length,
        },
      ]),
      setDraftSourceKey,
      setDraftFormState,
      setDraftMembership,
    );
  };

  const handleRemoveDocument = (documentId: string) => {
    stageDraft(
      currentSourceKey,
      formState,
      sortMembership(membershipDraft.filter((item) => item.document_id !== documentId)),
      setDraftSourceKey,
      setDraftFormState,
      setDraftMembership,
    );
  };

  const handleSaveMetadata = () => {
    const name = formState.name.trim();
    if (!name) {
      setMetadataError('Knowledge Base name is required');
      return;
    }

    const payload: KnowledgeBaseMutationPayload = {
      name,
      description: formState.description.trim() ? formState.description.trim() : null,
      status: formState.status,
      retrieval_profile: selectedKnowledgeBase?.retrieval_profile || {},
      documents: sortMembership(membershipDraft),
    };

    if (isCreateMode) {
      createMutation.mutate(payload);
      return;
    }

    if (!selectedKnowledgeBase) {
      setMetadataError('Select a Knowledge Base first');
      return;
    }

    updateMutation.mutate({
      knowledgeBaseId: selectedKnowledgeBase.id,
      payload: {
        name: payload.name,
        description: payload.description,
        status: payload.status,
      },
    });
  };

  const handleSaveMembership = () => {
    if (!selectedKnowledgeBase) {
      setMembershipError('Create or select a Knowledge Base before saving membership');
      return;
    }

    replaceDocumentsMutation.mutate({
      knowledgeBaseId: selectedKnowledgeBase.id,
      documents: sortMembership(membershipDraft),
    });
  };

  const activeStatusLabel = formState.status === 'active' ? 'Enabled' : formState.status === 'disabled' ? 'Disabled' : formState.status;
  const editorLoading = knowledgeBasesLoading || documentsLoading;
  const metadataSaving = createMutation.isPending || updateMutation.isPending;

  return (
    <div className="space-y-8">
      <SectionToolbar
        title="Knowledge Bases"
        description="Manage Workspace-scoped Knowledge Bases as first-class resources instead of burying Document grouping inside raw configuration."
        actions={
          <button type="button" className="btn-primary" onClick={handleCreateMode}>
            <Plus size={16} />
            <span>Create Knowledge Base</span>
          </button>
        }
      />

      {primaryError && (
        <InlineAlert tone="danger" title="Knowledge Base page failed to load">
          {primaryError}
        </InlineAlert>
      )}

      <div className="grid grid-cols-4 gap-4">
        <KeyMetric label="Knowledge Bases" value={knowledgeBases.length} hint="Current Workspace catalog" />
        <KeyMetric label="Enabled" value={knowledgeBases.filter((knowledgeBase) => knowledgeBase.status === 'active').length} hint="Ready for reuse" />
        <KeyMetric label="Enabled Documents" value={totalEnabledMemberships} hint="Across all Knowledge Bases" />
        <KeyMetric label="Unassigned Documents" value={unassignedDocuments} hint="Documents not in any Knowledge Base" />
      </div>

      <div className="grid grid-cols-[0.8fr_1.2fr] gap-6">
        <GlassPanel
          title="Knowledge Base catalog"
          subtitle="Reusable retrieval scopes inside the current Workspace."
          actions={<input value={search} onChange={(event) => setSearch(event.target.value)} className="field w-64" placeholder="Search Knowledge Bases" />}
        >
          <KnowledgeBaseList
            knowledgeBases={knowledgeBases}
            selectedKnowledgeBaseId={selectedKnowledgeBaseId}
            search={search}
            isLoading={knowledgeBasesLoading}
            onSelect={handleSelectKnowledgeBase}
            onCreate={handleCreateMode}
          />
        </GlassPanel>

        <GlassPanel
          title={isCreateMode ? 'Create Knowledge Base' : selectedKnowledgeBase?.name || 'Knowledge Base details'}
          subtitle={
            isCreateMode
              ? 'Define metadata first, then save the Knowledge Base with its initial Document membership.'
              : 'Edit metadata and manage which Workspace Documents participate in this Knowledge Base.'
          }
        >
          {editorLoading && !selectedKnowledgeBase && !isCreateMode ? (
            <div className="empty-state min-h-[420px]">
              <Loader2 size={20} className="animate-spin text-blue-600" />
              <p className="text-sm text-slate-500">Loading Knowledge Base details…</p>
            </div>
          ) : knowledgeBases.length === 0 && !isCreateMode ? (
            <EmptyState
              title="Knowledge Base management starts here"
              description="Create the first Knowledge Base for this Workspace to make Document grouping reusable and explicit."
              action={
                <button type="button" className="btn-primary" onClick={handleCreateMode}>
                  <Plus size={16} />
                  <span>Create Knowledge Base</span>
                </button>
              }
            />
          ) : isCreateMode || selectedKnowledgeBase ? (
            <div className="space-y-6">
              {metadataError && (
                <InlineAlert tone="danger" title="Knowledge Base metadata failed to save">
                  {metadataError}
                </InlineAlert>
              )}

              {isCreateMode && (
                <InlineAlert tone="warning" title="Membership is still a draft">
                  Document membership below will be created together with the new Knowledge Base when you save metadata.
                </InlineAlert>
              )}

              <div className="grid grid-cols-4 gap-4">
                <div className="surface-soft p-4">
                  <p className="metric-label">Workspace resource</p>
                  <p className="mt-2 text-sm font-medium text-slate-900">{isCreateMode ? 'New Knowledge Base draft' : 'Saved Knowledge Base'}</p>
                </div>
                <div className="surface-soft p-4">
                  <p className="metric-label">Status</p>
                  <div className="mt-3">
                    <StatusBadge tone={formState.status === 'active' ? 'success' : 'warning'}>{activeStatusLabel}</StatusBadge>
                  </div>
                </div>
                <div className="surface-soft p-4">
                  <p className="metric-label">Documents</p>
                  <p className="mt-2 text-sm font-medium text-slate-900">{membershipDraft.length} total members</p>
                </div>
                <div className="surface-soft p-4">
                  <p className="metric-label">Enabled members</p>
                  <p className="mt-2 text-sm font-medium text-slate-900">{membershipDraft.filter((document) => document.enabled).length}</p>
                </div>
              </div>

              <div className="grid gap-4 lg:grid-cols-[1fr_0.92fr]">
                <div className="space-y-4">
                  <Field label="Knowledge Base name" required>
                    <input
                      className="field"
                      value={formState.name}
                      onChange={(event) => handleFormChange('name', event.target.value)}
                      placeholder="Airport operations knowledge base"
                    />
                  </Field>

                  <Field label="Description" hint="Explain what this Knowledge Base covers so other operators know when to reuse it.">
                    <textarea
                      className="field min-h-[120px] resize-y"
                      value={formState.description}
                      onChange={(event) => handleFormChange('description', event.target.value)}
                      placeholder="Operational manuals, SOPs, and versioned procedures for the airport team."
                    />
                  </Field>
                </div>

                <div className="space-y-4">
                  <Field label="Status" hint="Disabled Knowledge Bases stay visible but should not be treated as active configuration.">
                    <select className="field" value={formState.status} onChange={(event) => handleFormChange('status', event.target.value)}>
                      <option value="active">Enabled</option>
                      <option value="disabled">Disabled</option>
                    </select>
                  </Field>

                  <div className="surface-soft space-y-3 p-4">
                    <div className="flex items-center gap-2 text-slate-900">
                      <Workflow size={16} />
                      <p className="text-sm font-medium">Retrieval profile</p>
                    </div>
                    <p className="text-sm text-slate-500">
                      {selectedKnowledgeBase?.retrieval_profile && Object.keys(selectedKnowledgeBase.retrieval_profile).length > 0
                        ? summarizeRetrievalProfile(selectedKnowledgeBase)
                        : 'No explicit retrieval profile is set yet. This Knowledge Base will follow backend defaults.'}
                    </p>
                  </div>

                  <div className="surface-soft space-y-2 p-4">
                    <p className="text-sm font-medium text-slate-900">Last updated</p>
                    <p className="text-sm text-slate-500">{selectedKnowledgeBase ? formatDateTime(selectedKnowledgeBase.updated_at) : 'Not saved yet'}</p>
                  </div>
                </div>
              </div>

              <div className="flex flex-wrap gap-3">
                <button type="button" className="btn-primary" onClick={handleSaveMetadata} disabled={metadataSaving}>
                  {metadataSaving ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
                  <span>{isCreateMode ? (metadataSaving ? 'Creating…' : 'Create Knowledge Base') : metadataSaving ? 'Saving metadata…' : 'Save metadata'}</span>
                </button>

                {!isCreateMode && (
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => {
                      setDraftSourceKey('empty');
                      if (selectedKnowledgeBase) handleSelectKnowledgeBase(selectedKnowledgeBase.id);
                    }}
                  >
                    <Layers3 size={16} />
                    <span>Reset to saved state</span>
                  </button>
                )}
              </div>

              <KnowledgeBaseMembershipEditor
                documents={documents}
                membership={membershipDraft}
                disabled={isCreateMode}
                savePending={replaceDocumentsMutation.isPending}
                error={membershipError}
                onAddDocument={handleAddDocument}
                onRemoveDocument={handleRemoveDocument}
                onMembershipChange={handleMembershipChange}
                onSave={handleSaveMembership}
              />
            </div>
          ) : (
            <EmptyState title="Select a Knowledge Base" description="Choose a Knowledge Base from the Workspace catalog or create a new one." />
          )}
        </GlassPanel>
      </div>

      <GlassPanel title="Workspace coverage" subtitle="A quick read on how Documents are being reused across Knowledge Bases.">
        {documentsLoading ? (
          <div className="empty-state min-h-[180px]">
            <Loader2 size={20} className="animate-spin text-blue-600" />
            <p className="text-sm text-slate-500">Loading Workspace Documents…</p>
          </div>
        ) : documents.length === 0 ? (
          <EmptyState title="No Documents yet" description="Upload Documents on the Documents page, then add them into one or more Knowledge Bases." />
        ) : (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {documents.map((document) => {
              const membershipCount = documentMembershipCounts.get(document.id) || 0;

              return (
                <div key={document.id} className="surface-soft space-y-3 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate font-medium text-slate-900">{document.display_name}</p>
                      <p className="truncate text-sm text-slate-500">{document.source_filename}</p>
                    </div>
                    <StatusBadge tone={document.status === 'index_ready' ? 'success' : document.status === 'failed' ? 'danger' : 'accent'}>
                      {document.status}
                    </StatusBadge>
                  </div>
                  <p className="text-sm text-slate-500">
                    {membershipCount > 0 ? `Included in ${membershipCount} Knowledge Base${membershipCount > 1 ? 's' : ''}.` : 'Not assigned to any Knowledge Base yet.'}
                  </p>
                </div>
              );
            })}
          </div>
        )}
      </GlassPanel>
    </div>
  );
};

const sortMembership = (documents: KnowledgeBaseDocumentBinding[]) =>
  [...documents].sort((left, right) => {
    if (left.sort_order !== right.sort_order) return left.sort_order - right.sort_order;
    return left.document_id.localeCompare(right.document_id);
  });

const deriveFormState = (knowledgeBase: KnowledgeBase | null): KnowledgeBaseFormState =>
  knowledgeBase
    ? {
        name: knowledgeBase.name,
        description: knowledgeBase.description || '',
        status: knowledgeBase.status,
      }
    : EMPTY_FORM;

const deriveMembership = (knowledgeBase: KnowledgeBase | null) => sortMembership(knowledgeBase?.documents || []);

const stageDraft = (
  sourceKey: string,
  nextFormState: KnowledgeBaseFormState,
  nextMembership: KnowledgeBaseDocumentBinding[],
  setSourceKey: React.Dispatch<React.SetStateAction<string>>,
  setFormState: React.Dispatch<React.SetStateAction<KnowledgeBaseFormState>>,
  setMembership: React.Dispatch<React.SetStateAction<KnowledgeBaseDocumentBinding[]>>,
) => {
  setSourceKey(sourceKey);
  setFormState(nextFormState);
  setMembership(nextMembership);
};

const summarizeRetrievalProfile = (knowledgeBase: KnowledgeBase) => {
  const mode = typeof knowledgeBase.retrieval_profile.mode === 'string' ? knowledgeBase.retrieval_profile.mode : null;
  const perDocumentTopK =
    typeof knowledgeBase.retrieval_profile.per_document_top_k === 'number' ? knowledgeBase.retrieval_profile.per_document_top_k : null;
  const globalTopK = typeof knowledgeBase.retrieval_profile.global_top_k === 'number' ? knowledgeBase.retrieval_profile.global_top_k : null;

  const parts = [
    mode ? `Mode: ${mode}` : null,
    perDocumentTopK !== null ? `Per-Document top K: ${perDocumentTopK}` : null,
    globalTopK !== null ? `Global top K: ${globalTopK}` : null,
  ].filter(Boolean);

  return parts.join(' · ');
};
