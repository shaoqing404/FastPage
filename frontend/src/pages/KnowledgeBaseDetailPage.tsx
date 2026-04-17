import React, { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft,
  ChevronRight,
  Loader2,
  Save,
  Settings2,
  Trash2,
  Upload,
} from 'lucide-react';

import { KnowledgeBaseMembershipEditor } from '../components/knowledge-bases/KnowledgeBaseMembershipEditor';
import { Field, GlassPanel, InlineAlert, SectionToolbar } from '../components/ui/workbench';
import { documentsApi } from '../features/documents/api';
import { knowledgeBasesApi } from '../features/knowledge-bases/api';
import type {
  KnowledgeBase,
  KnowledgeBaseDocumentBinding,
  KnowledgeBaseDocumentBindingInput,
} from '../features/knowledge-bases/types';
import { resolveStoredUser, resolveStoredWorkspaceMembership } from '../lib/api/client';
import { formatDateTime, getErrorMessage } from '../lib/utils';
import type { ResourceVisibility } from '../types';

type MetadataFormState = {
  name: string;
  description: string;
  status: string;
  visibility: ResourceVisibility;
};

const deriveMetadata = (kb: KnowledgeBase | null): MetadataFormState =>
  kb
    ? { name: kb.name, description: kb.description || '', status: kb.status, visibility: kb.visibility }
    : { name: '', description: '', status: 'active', visibility: 'private' };

const deriveMembership = (kb: KnowledgeBase | null): KnowledgeBaseDocumentBinding[] =>
  [...(kb?.documents || [])].sort((a, b) => {
    if (a.sort_order !== b.sort_order) return a.sort_order - b.sort_order;
    return a.document_id.localeCompare(b.document_id);
  });

const canEditKnowledgeBase = (userId: string, kb: KnowledgeBase, workspaceRole: string | null, canManage: boolean) => {
  if (workspaceRole === 'founder' || workspaceRole === 'admin') return true;
  if (kb.created_by === userId) return true;
  if (!canManage) return false;
  return kb.visibility === 'workspace_edit';
};

export const KnowledgeBaseDetailPage: React.FC = () => {
  const { kbId } = useParams<{ kbId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const user = resolveStoredUser();
  const workspaceMembership = resolveStoredWorkspaceMembership();
  const canManage = workspaceMembership?.permissions?.can_manage_knowledge_bases === true;

  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [metadataForm, setMetadataForm] = useState<MetadataFormState | null>(null);
  const [membership, setMembership] = useState<KnowledgeBaseDocumentBinding[] | null>(null);
  const [metadataError, setMetadataError] = useState('');
  const [metadataSuccess, setMetadataSuccess] = useState('');
  const [membershipError, setMembershipError] = useState('');

  // Upload state
  const [uploadPending, setUploadPending] = useState(false);
  const [uploadError, setUploadError] = useState('');

  const { data: kb, isLoading: kbLoading } = useQuery({
    queryKey: ['knowledge-base', kbId],
    queryFn: () => knowledgeBasesApi.get(kbId!),
    enabled: !!kbId,
  });

  const { data: documents = [], isLoading: docsLoading } = useQuery({
    queryKey: ['documents'],
    queryFn: () => documentsApi.list(),
  });

  // Derive form state from loaded KB
  const effectiveMetadata = metadataForm ?? deriveMetadata(kb ?? null);
  const effectiveMembership = membership ?? deriveMembership(kb ?? null);

  const editable = kb && user?.id ? canEditKnowledgeBase(user.id, kb, workspaceMembership?.role ?? null, canManage) : false;

  // Metadata update
  const updateMetadataMutation = useMutation({
    mutationFn: (payload: Partial<MetadataFormState>) => knowledgeBasesApi.update(kbId!, payload),
    onSuccess: () => {
      setMetadataError('');
      setMetadataSuccess('Metadata saved.');
      setMetadataForm(null);
      queryClient.invalidateQueries({ queryKey: ['knowledge-base', kbId] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-bases'] });
      setTimeout(() => setMetadataSuccess(''), 3000);
    },
    onError: (e: unknown) => setMetadataError(getErrorMessage(e, 'Failed to update metadata')),
  });

  // Membership save (replace all)
  const saveMembershipMutation = useMutation({
    mutationFn: (docs: KnowledgeBaseDocumentBindingInput[]) => knowledgeBasesApi.replaceDocuments(kbId!, docs),
    onSuccess: () => {
      setMembershipError('');
      setMembership(null);
      queryClient.invalidateQueries({ queryKey: ['knowledge-base', kbId] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-bases'] });
    },
    onError: (e: unknown) => setMembershipError(getErrorMessage(e, 'Failed to save membership')),
  });

  // Delete KB
  const deleteMutation = useMutation({
    mutationFn: () => knowledgeBasesApi.delete(kbId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['knowledge-bases'] });
      navigate('/knowledge-bases', { replace: true });
    },
    onError: (e: unknown) => setMetadataError(getErrorMessage(e, 'Failed to delete Knowledge Base')),
  });

  // Upload file directly to KB
  const handleFileUpload = async (file: File) => {
    if (!kbId) return;
    setUploadPending(true);
    setUploadError('');
    try {
      // Pass kbId so the backend records which KB triggered this upload
      const result = await documentsApi.upload(file, undefined, kbId);
      // Auto-add to KB membership
      const newBinding: KnowledgeBaseDocumentBindingInput = {
        document_id: result.document_id,
        enabled: true,
        sort_order: effectiveMembership.length,
      };
      await knowledgeBasesApi.addDocument(kbId, newBinding);
      queryClient.invalidateQueries({ queryKey: ['knowledge-base', kbId] });
      queryClient.invalidateQueries({ queryKey: ['documents'] });
      setMembership(null); // reset to re-derive
    } catch (e) {
      setUploadError(getErrorMessage(e, 'Upload failed'));
    } finally {
      setUploadPending(false);
    }
  };

  // Metadata form helpers
  const updateField = <K extends keyof MetadataFormState>(key: K, value: MetadataFormState[K]) => {
    setMetadataForm((prev) => ({ ...(prev ?? deriveMetadata(kb ?? null)), [key]: value }));
  };

  const hasMetadataChanges = kb && metadataForm && (
    metadataForm.name !== kb.name ||
    metadataForm.description !== (kb.description || '') ||
    metadataForm.status !== kb.status ||
    metadataForm.visibility !== kb.visibility
  );

  // Membership helpers
  const handleAddDocument = (docId: string) => {
    const current = membership ?? deriveMembership(kb ?? null);
    setMembership([...current, { document_id: docId, pinned_version_id: null, enabled: true, label: null, sort_order: current.length }]);
  };

  const handleRemoveDocument = (docId: string) => {
    const current = membership ?? deriveMembership(kb ?? null);
    setMembership(current.filter((m) => m.document_id !== docId));
  };

  const handleMembershipChange = (docId: string, update: Partial<KnowledgeBaseDocumentBinding>) => {
    const current = membership ?? deriveMembership(kb ?? null);
    setMembership(current.map((m) => (m.document_id === docId ? { ...m, ...update } : m)));
  };

  const handleSaveMembership = () => {
    saveMembershipMutation.mutate(
      effectiveMembership.map((m) => ({
        document_id: m.document_id,
        pinned_version_id: m.pinned_version_id,
        enabled: m.enabled,
        label: m.label,
        sort_order: m.sort_order,
      })),
    );
  };

  if (!kbId) return null;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button type="button" className="btn-secondary" onClick={() => navigate('/knowledge-bases')}>
          <ArrowLeft size={16} />
          <span>All Knowledge Bases</span>
        </button>
        <div className="flex-1" />
        <button
          type="button"
          className="btn-ghost text-sm"
          onClick={() => setSidebarOpen(!sidebarOpen)}
        >
          {sidebarOpen ? <ChevronRight size={16} /> : <Settings2 size={16} />}
          <span>{sidebarOpen ? 'Hide sidebar' : 'Settings'}</span>
        </button>
      </div>

      {kbLoading && (
        <div className="flex items-center justify-center py-20">
          <Loader2 size={20} className="animate-spin text-slate-400" />
          <span className="ml-2 text-sm text-slate-500">Loading Knowledge Base…</span>
        </div>
      )}

      {kb && (
        <>
          <SectionToolbar
            title={kb.name}
            description={kb.description || 'No description'}
          />

          <div className={`grid gap-6 ${sidebarOpen ? 'lg:grid-cols-[1fr_340px]' : ''}`}>
            {/* Main content: Document management */}
            <div className="space-y-6 min-w-0">
              {/* Upload area */}
              <GlassPanel title="Upload Documents" subtitle="Upload new files directly into this Knowledge Base.">
                <div className="space-y-3">
                  <label
                    htmlFor="kb-file-upload"
                    className={`flex cursor-pointer items-center justify-center gap-3 rounded-xl border-2 border-dashed border-slate-300/80 bg-slate-50/50 p-8 text-sm text-slate-500 transition hover:border-blue-400 hover:bg-blue-50/30 ${uploadPending ? 'pointer-events-none opacity-60' : ''}`}
                  >
                    {uploadPending ? (
                      <>
                        <Loader2 size={20} className="animate-spin" />
                        <span>Uploading…</span>
                      </>
                    ) : (
                      <>
                        <Upload size={20} />
                        <span>Drop a file here or click to upload</span>
                      </>
                    )}
                    <input
                      id="kb-file-upload"
                      type="file"
                      className="sr-only"
                      disabled={uploadPending}
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        if (file) handleFileUpload(file);
                        e.target.value = '';
                      }}
                    />
                  </label>
                  {uploadError && <InlineAlert tone="danger" title="Upload failed">{uploadError}</InlineAlert>}
                </div>
              </GlassPanel>

              {/* Document membership editor */}
              <GlassPanel
                title="Document Membership"
                subtitle={`${effectiveMembership.filter((m) => m.enabled).length} enabled · ${effectiveMembership.length} total`}
              >
                {docsLoading ? (
                  <div className="flex items-center justify-center py-10">
                    <Loader2 size={16} className="animate-spin text-slate-400" />
                    <span className="ml-2 text-sm text-slate-500">Loading documents…</span>
                  </div>
                ) : (
                  <KnowledgeBaseMembershipEditor
                    documents={documents}
                    membership={effectiveMembership}
                    disabled={!editable}
                    savePending={saveMembershipMutation.isPending}
                    error={membershipError}
                    onAddDocument={handleAddDocument}
                    onRemoveDocument={handleRemoveDocument}
                    onMembershipChange={handleMembershipChange}
                    onSave={handleSaveMembership}
                  />
                )}
              </GlassPanel>
            </div>

            {/* Sidebar: Metadata */}
            {sidebarOpen && (
              <div className="space-y-5">
                <GlassPanel title="Settings" subtitle="Knowledge Base metadata and configuration.">
                  <form
                    className="space-y-4"
                    onSubmit={(e) => {
                      e.preventDefault();
                      if (!metadataForm) return;
                      updateMetadataMutation.mutate(metadataForm);
                    }}
                  >
                    <Field label="Name">
                      <input
                        id="kb-detail-name"
                        className="field"
                        value={effectiveMetadata.name}
                        disabled={!editable}
                        onChange={(e) => updateField('name', e.target.value)}
                      />
                    </Field>
                    <Field label="Description">
                      <textarea
                        id="kb-detail-desc"
                        className="field min-h-[80px]"
                        value={effectiveMetadata.description}
                        disabled={!editable}
                        onChange={(e) => updateField('description', e.target.value)}
                      />
                    </Field>
                    <Field label="Status">
                      <select
                        id="kb-detail-status"
                        className="field"
                        value={effectiveMetadata.status}
                        disabled={!editable}
                        onChange={(e) => updateField('status', e.target.value)}
                      >
                        <option value="active">Active</option>
                        <option value="disabled">Disabled</option>
                      </select>
                    </Field>
                    <Field label="Visibility">
                      <select
                        id="kb-detail-visibility"
                        className="field"
                        value={effectiveMetadata.visibility}
                        disabled={!editable}
                        onChange={(e) => updateField('visibility', e.target.value as ResourceVisibility)}
                      >
                        <option value="private">Private</option>
                        <option value="workspace_read">Workspace Read</option>
                        <option value="workspace_edit">Workspace Edit</option>
                      </select>
                    </Field>

                    {metadataError && <InlineAlert tone="danger" title="Error">{metadataError}</InlineAlert>}
                    {metadataSuccess && <InlineAlert tone="success" title="Saved">{metadataSuccess}</InlineAlert>}

                    {editable && (
                      <button
                        type="submit"
                        className="btn-primary w-full"
                        disabled={!hasMetadataChanges || updateMetadataMutation.isPending}
                      >
                        {updateMetadataMutation.isPending ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
                        <span>{updateMetadataMutation.isPending ? 'Saving…' : 'Save metadata'}</span>
                      </button>
                    )}
                  </form>
                </GlassPanel>

                <GlassPanel title="Info" subtitle="Read-only details.">
                  <div className="space-y-3 text-sm">
                    <Field label="ID"><p className="text-slate-900 font-mono text-xs break-all">{kb.id}</p></Field>
                    <Field label="Created by"><p className="text-slate-900 font-mono text-xs">{kb.created_by}</p></Field>
                    <Field label="Created"><p className="text-slate-900">{formatDateTime(kb.created_at)}</p></Field>
                    <Field label="Updated"><p className="text-slate-900">{formatDateTime(kb.updated_at)}</p></Field>
                    <Field label="Retrieval profile">
                      <pre className="text-xs text-slate-600 bg-slate-50 rounded-lg p-2 overflow-x-auto">
                        {JSON.stringify(kb.retrieval_profile, null, 2)}
                      </pre>
                    </Field>
                  </div>
                </GlassPanel>

                {/* Danger zone */}
                {editable && (
                  <GlassPanel title="Danger zone">
                    <button
                      type="button"
                      className="btn-ghost text-red-600 w-full"
                      disabled={deleteMutation.isPending}
                      onClick={() => {
                        if (window.confirm(`Delete "${kb.name}"? This cannot be undone.`)) {
                          deleteMutation.mutate();
                        }
                      }}
                    >
                      {deleteMutation.isPending ? <Loader2 size={16} className="animate-spin" /> : <Trash2 size={16} />}
                      <span>{deleteMutation.isPending ? 'Deleting…' : 'Delete Knowledge Base'}</span>
                    </button>
                  </GlassPanel>
                )}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
};
