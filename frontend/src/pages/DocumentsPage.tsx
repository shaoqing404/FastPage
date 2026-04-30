import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { BookMarked, BookCopy, Eye, FileUp, History, Loader2, RefreshCcw, Trash2, Share2 } from 'lucide-react';

import { ExpertDrawer, GlassPanel, InlineAlert, KeyMetric, SectionToolbar, StatusBadge } from '../components/ui/workbench';
import { documentsApi } from '../features/documents/api';
import { knowledgeBasesApi } from '../features/knowledge-bases/api';
import { jobsApi } from '../features/metrics/api';
import { resolveStoredUser } from '../lib/api/client';
import { formatDateTime, getErrorMessage } from '../lib/utils';

export const DocumentsPage: React.FC = () => {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const currentUser = resolveStoredUser();

  const [search, setSearch] = useState('');
  const [selectedDocId, setSelectedDocId] = useState<string>('');
  const [versionDrawerOpen, setVersionDrawerOpen] = useState(false);
  const [structureDrawerOpen, setStructureDrawerOpen] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [documentError, setDocumentError] = useState('');
  const [shareKbId, setShareKbId] = useState('');
  const [sharePending, setSharePending] = useState(false);
  const [shareError, setShareError] = useState('');
  const [shareSuccess, setShareSuccess] = useState('');

  const { data: documents = [], isLoading } = useQuery({
    queryKey: ['documents', 'me'],
    queryFn: () => documentsApi.list({ ownerMe: true }),
  });
  const { data: knowledgeBases = [] } = useQuery({ queryKey: ['knowledge-bases'], queryFn: () => knowledgeBasesApi.list() });
  const { data: jobs = [] } = useQuery({
    queryKey: ['all-jobs'],
    queryFn: () => jobsApi.list(),
    refetchInterval: (query) => (query.state.data?.some((job) => ['uploaded', 'queued', 'parsing'].includes(job.status)) ? 2500 : false),
  });

  const selectedDoc = documents.find((document) => document.id === selectedDocId) || documents[0] || null;
  const activeJobs = jobs.filter((job) => ['uploaded', 'queued', 'parsing'].includes(job.status));
  const filteredDocuments = documents.filter((document) =>
    document.display_name.toLowerCase().includes(search.trim().toLowerCase()),
  );

  // Compute which KBs each doc already belongs to
  const documentMembershipCounts = new Map<string, number>();
  knowledgeBases.forEach((kb) => {
    kb.documents.forEach((m) => {
      documentMembershipCounts.set(m.document_id, (documentMembershipCounts.get(m.document_id) || 0) + 1);
    });
  });

  // KBs that already include the selected doc
  const selectedDocKbs = selectedDoc
    ? knowledgeBases.filter((kb) => kb.documents.some((m) => m.document_id === selectedDoc.id))
    : [];

  // KBs where the doc is NOT yet a member (for share dropdown)
  const availableKbsToShare = knowledgeBases.filter(
    (kb) => !kb.documents.some((m) => m.document_id === selectedDoc?.id),
  );

  const { data: versions = [], isLoading: loadingVersions } = useQuery({
    queryKey: ['versions', selectedDoc?.id],
    queryFn: () => documentsApi.listVersions(selectedDoc!.id),
    enabled: Boolean(selectedDoc?.id),
  });

  const { data: structure, isLoading: loadingStructure } = useQuery({
    queryKey: ['structure', selectedDoc?.id, selectedDoc?.active_version_id],
    queryFn: () => documentsApi.getStructure(selectedDoc!.id, selectedDoc?.active_version_id || undefined),
    enabled: Boolean(selectedDoc?.id && structureDrawerOpen),
  });

  const uploadMutation = useMutation({
    mutationFn: (file: File) => documentsApi.upload(file),
    onSuccess: (data) => {
      setDocumentError('');
      queryClient.invalidateQueries({ queryKey: ['documents'] });
      queryClient.invalidateQueries({ queryKey: ['all-jobs'] });
      parseMutation.mutate({ documentId: data.document_id, versionId: data.version_id });
      setUploading(false);
      setSelectedDocId(data.document_id);
    },
    onError: (error: unknown) => {
      setUploading(false);
      setDocumentError(getErrorMessage(error, 'Upload failed'));
    },
  });

  const parseMutation = useMutation({
    mutationFn: ({ documentId, versionId }: { documentId: string; versionId?: string }) =>
      documentsApi.parse(documentId, versionId),
    onSuccess: () => {
      setDocumentError('');
      queryClient.invalidateQueries({ queryKey: ['documents'] });
      queryClient.invalidateQueries({ queryKey: ['all-jobs'] });
    },
    onError: (error: unknown) => setDocumentError(getErrorMessage(error, 'Parse request failed')),
  });

  const reparseMutation = useMutation({
    mutationFn: ({ documentId, versionId }: { documentId: string; versionId?: string }) =>
      documentsApi.rebuild(documentId, versionId),
    onSuccess: () => {
      setDocumentError('');
      queryClient.invalidateQueries({ queryKey: ['documents'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-bases'] });
      queryClient.invalidateQueries({ queryKey: ['versions'] });
      queryClient.invalidateQueries({ queryKey: ['structure'] });
      queryClient.invalidateQueries({ queryKey: ['all-jobs'] });
    },
    onError: (error: unknown) => setDocumentError(getErrorMessage(error, '重建请求失败')),
  });

  const restoreMutation = useMutation({
    mutationFn: (versionId: string) => documentsApi.restore(selectedDoc!.id, versionId),
    onSuccess: () => {
      setDocumentError('');
      queryClient.invalidateQueries({ queryKey: ['documents'] });
      queryClient.invalidateQueries({ queryKey: ['versions', selectedDoc?.id] });
    },
    onError: (error: unknown) => setDocumentError(getErrorMessage(error, 'Restore failed')),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => documentsApi.delete(id),
    onSuccess: () => {
      setDocumentError('');
      setStructureDrawerOpen(false);
      setVersionDrawerOpen(false);
      if (selectedDoc) {
        setSelectedDocId((currentId) => (currentId === selectedDoc.id ? '' : currentId));
      }
      queryClient.invalidateQueries({ queryKey: ['documents'] });
    },
    onError: (error: unknown) => setDocumentError(getErrorMessage(error, 'Delete document failed')),
  });

  const handleUpload = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setUploading(true);
    uploadMutation.mutate(file);
  };

  const handleShareToKb = async () => {
    if (!selectedDoc || !shareKbId) return;
    setSharePending(true);
    setShareError('');
    setShareSuccess('');
    try {
      await knowledgeBasesApi.addDocument(shareKbId, {
        document_id: selectedDoc.id,
        enabled: true,
        sort_order: 0,
      });
      queryClient.invalidateQueries({ queryKey: ['knowledge-bases'] });
      setShareSuccess('Document added to Knowledge Base.');
      setShareKbId('');
      setTimeout(() => setShareSuccess(''), 3000);
    } catch (e) {
      setShareError(getErrorMessage(e, 'Failed to share to Knowledge Base'));
    } finally {
      setSharePending(false);
    }
  };

  const selectedDocJob = selectedDoc ? activeJobs.find((job) => job.document_id === selectedDoc.id) || null : null;
  const myDocCount = currentUser?.id
    ? documents.filter((d) => d.owner_user_id === currentUser.id).length
    : documents.length;

  return (
    <div className="space-y-8">
      <SectionToolbar
        title="My Documents"
        description="Your personal document library. Upload files here, then share them to a Knowledge Base for use in retrieval."
        actions={
          <label className="btn-primary cursor-pointer">
            {uploading ? <Loader2 size={16} className="animate-spin" /> : <FileUp size={16} />}
            <span>{uploading ? 'Uploading…' : 'Add PDF'}</span>
            <input type="file" className="hidden" accept=".pdf" onChange={handleUpload} />
          </label>
        }
      />

      {documentError && (
        <InlineAlert tone="danger" title="Document operation failed">
          {documentError}
        </InlineAlert>
      )}

      <div className="grid grid-cols-4 gap-4">
        <KeyMetric label="My Documents" value={myDocCount} hint="Files you own" />
        <KeyMetric label="Ready" value={documents.filter((d) => d.status === 'index_ready').length} hint="Available for retrieval" />
        <KeyMetric label="Active jobs" value={activeJobs.length} hint="Parsing in progress" />
        <KeyMetric
          label="Shared to KBs"
          value={documents.filter((d) => (documentMembershipCounts.get(d.id) || 0) > 0).length}
          hint="Documents assigned to a Knowledge Base"
        />
      </div>

      {activeJobs.length > 0 && (
        <GlassPanel title="Active ingestion" subtitle="Live parse pipeline progress for recently uploaded documents.">
          <div className="space-y-3">
            {activeJobs.slice(0, 4).map((job) => (
              <div key={job.id} className="surface-soft p-4">
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <p className="font-medium text-slate-900">Document {job.document_id.slice(0, 8)}</p>
                    <p className="text-sm text-slate-500">{job.current_step || 'Processing'}</p>
                  </div>
                  <StatusBadge tone="accent">{job.progress_percent}%</StatusBadge>
                </div>
                <div className="mt-3 h-2 rounded-full bg-slate-200">
                  <div className="h-2 rounded-full bg-blue-600 transition-all" style={{ width: `${job.progress_percent}%` }} />
                </div>
              </div>
            ))}
          </div>
        </GlassPanel>
      )}

      <div className="grid grid-cols-[0.88fr_1.12fr] gap-6">
        <GlassPanel
          title="My library"
          subtitle="All documents you have uploaded to this workspace."
          actions={<input value={search} onChange={(e) => setSearch(e.target.value)} className="field w-64" placeholder="Filter documents" />}
        >
          <div className="scroll-area max-h-[760px] space-y-3 overflow-auto pr-1">
            {isLoading ? (
              <div className="empty-state min-h-[180px]">
                <Loader2 size={20} className="animate-spin text-blue-600" />
                <p className="text-sm text-slate-500">Loading documents…</p>
              </div>
            ) : (
              filteredDocuments.map((document) => (
                <button
                  type="button"
                  key={document.id}
                  onClick={() => setSelectedDocId(document.id)}
                  className={`list-row w-full text-left ${selectedDocId === document.id ? 'list-row-active' : ''}`}
                >
                  <div className="space-y-2">
                    <div className="flex items-center gap-2">
                      <BookCopy size={16} className="text-slate-400" />
                      <p className="font-medium text-slate-900">{document.display_name}</p>
                    </div>
                    <p className="text-sm text-slate-500">{formatDateTime(document.updated_at)}</p>
                  </div>
                  <StatusBadge tone={document.status === 'index_ready' ? 'success' : document.status === 'failed' ? 'danger' : 'accent'}>
                    {document.status}
                  </StatusBadge>
                </button>
              ))
            )}
            {!isLoading && filteredDocuments.length === 0 && (
              <div className="empty-state min-h-[180px]">
                <p className="text-base font-medium text-slate-900">No matching documents</p>
                <p className="text-sm text-slate-500">Try a different search or upload a new PDF.</p>
              </div>
            )}
          </div>
        </GlassPanel>

        <GlassPanel title={selectedDoc?.display_name || '文档检查'} subtitle="查看元数据、版本、知识库归属，并基于当前手册生成重建版本。">
          {selectedDoc ? (
            <div className="space-y-6">
              {selectedDocJob && (
                <InlineAlert tone="warning" title="Parsing in progress">
                  <div className="space-y-1">
                    <p>{selectedDocJob.current_step || 'Processing document structure'}.</p>
                    <p>{selectedDocJob.progress_percent}% complete.</p>
                  </div>
                </InlineAlert>
              )}

              <div className="grid grid-cols-3 gap-4">
                <div className="surface-soft p-4">
                  <p className="metric-label">Status</p>
                  <div className="mt-3">
                    <StatusBadge tone={selectedDoc.status === 'index_ready' ? 'success' : selectedDoc.status === 'failed' ? 'danger' : 'accent'}>
                      {selectedDoc.status}
                    </StatusBadge>
                  </div>
                </div>
                <div className="surface-soft p-4">
                  <p className="metric-label">Created</p>
                  <p className="mt-3 text-sm font-medium text-slate-900">{formatDateTime(selectedDoc.created_at)}</p>
                </div>
                <div className="surface-soft p-4">
                  <p className="metric-label">Active version</p>
                  <p className="mt-3 text-sm font-medium text-slate-900">{selectedDoc.active_version_id?.slice(0, 8) || 'N/A'}</p>
                </div>
              </div>

              <dl className="data-kv">
                <dt>Document ID</dt>
                <dd>{selectedDoc.id}</dd>
                <dt>Source file</dt>
                <dd>{selectedDoc.source_filename}</dd>
                <dt>Updated</dt>
                <dd>{formatDateTime(selectedDoc.updated_at)}</dd>
                <dt>Owner</dt>
                <dd>{selectedDoc.owner_user_id}</dd>
                {selectedDoc.uploaded_via_kb_id && (
                  <>
                    <dt>Uploaded via KB</dt>
                    <dd className="font-mono text-xs">{selectedDoc.uploaded_via_kb_id}</dd>
                  </>
                )}
              </dl>

              {/* Share to Knowledge Base */}
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <Share2 size={16} className="text-slate-400" />
                  <p className="text-sm font-medium text-slate-900">Share to Knowledge Base</p>
                </div>

                {selectedDocKbs.length > 0 && (
                  <div className="space-y-2">
                    <p className="text-xs text-slate-500">Already in:</p>
                    {selectedDocKbs.map((kb) => (
                      <button
                        key={kb.id}
                        type="button"
                        className="flex items-center gap-2 text-sm text-blue-600 hover:underline"
                        onClick={() => navigate(`/knowledge-bases/${kb.id}`)}
                      >
                        <BookMarked size={14} />
                        {kb.name}
                      </button>
                    ))}
                  </div>
                )}

                {availableKbsToShare.length > 0 ? (
                  <div className="flex items-center gap-2">
                    <select
                      id="share-to-kb-select"
                      className="field flex-1"
                      value={shareKbId}
                      onChange={(e) => setShareKbId(e.target.value)}
                    >
                      <option value="">Select a Knowledge Base…</option>
                      {availableKbsToShare.map((kb) => (
                        <option key={kb.id} value={kb.id}>{kb.name}</option>
                      ))}
                    </select>
                    <button
                      type="button"
                      className="btn-primary"
                      disabled={!shareKbId || sharePending}
                      onClick={handleShareToKb}
                    >
                      {sharePending ? <Loader2 size={16} className="animate-spin" /> : <Share2 size={16} />}
                      <span>{sharePending ? 'Sharing…' : 'Share'}</span>
                    </button>
                  </div>
                ) : (
                  <p className="text-sm text-slate-500">
                    {knowledgeBases.length === 0
                      ? 'No Knowledge Bases yet. Create one first.'
                      : 'This document is already in all Knowledge Bases.'}
                  </p>
                )}

                {shareError && <InlineAlert tone="danger" title="Share failed">{shareError}</InlineAlert>}
                {shareSuccess && <InlineAlert tone="success" title="Shared">{shareSuccess}</InlineAlert>}
              </div>

              <div className="space-y-3">
                <div className="rounded-xl border border-blue-100 bg-blue-50/60 px-4 py-3 text-sm text-blue-800">
                  重建会基于当前激活版本创建一个新版本，重新解析页面/章节文本，并生成新的 ES 文本索引。
                </div>
                <div className="flex flex-wrap gap-3">
                  <button type="button" className="btn-secondary" onClick={() => setVersionDrawerOpen(true)}>
                    <History size={16} />
                    <span>版本历史</span>
                  </button>
                  <button type="button" className="btn-secondary" onClick={() => setStructureDrawerOpen(true)} disabled={!selectedDoc.active_version_id}>
                    <Eye size={16} />
                    <span>查看结构</span>
                  </button>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => reparseMutation.mutate({ documentId: selectedDoc.id, versionId: selectedDoc.active_version_id || undefined })}
                    disabled={reparseMutation.isPending}
                  >
                    {reparseMutation.isPending ? <Loader2 size={16} className="animate-spin" /> : <RefreshCcw size={16} />}
                    <span>{reparseMutation.isPending ? '正在重建…' : '重建为新版本'}</span>
                  </button>
                  <button type="button" className="btn-ghost text-red-600" onClick={() => deleteMutation.mutate(selectedDoc.id)}>
                    <Trash2 size={16} />
                    <span>删除文档</span>
                  </button>
                </div>
              </div>
            </div>
          ) : (
            <div className="empty-state min-h-[520px]">
              <p className="text-base font-medium text-slate-900">Select a document</p>
              <p className="text-sm text-slate-500">Choose a document from your library to inspect its metadata and share it to a Knowledge Base.</p>
            </div>
          )}
        </GlassPanel>
      </div>

      <ExpertDrawer
        open={versionDrawerOpen}
        onClose={() => setVersionDrawerOpen(false)}
        title={selectedDoc ? `${selectedDoc.display_name} versions` : 'Version history'}
        description="Restore older parses or inspect the current active version."
      >
        <div className="space-y-3">
          {loadingVersions ? (
            <div className="empty-state min-h-[160px]">
              <Loader2 size={20} className="animate-spin text-blue-600" />
              <p className="text-sm text-slate-500">Loading versions…</p>
            </div>
          ) : (
            versions.map((version) => (
              <div key={version.id} className="surface-soft space-y-3 p-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="font-medium text-slate-900">Version {version.version_no}</p>
                    <p className="text-sm text-slate-500">{formatDateTime(version.created_at)}</p>
                  </div>
                  <StatusBadge tone={version.id === selectedDoc?.active_version_id ? 'success' : version.parse_status === 'failed' ? 'danger' : 'accent'}>
                    {version.id === selectedDoc?.active_version_id ? 'active' : version.parse_status}
                  </StatusBadge>
                </div>
                {version.parse_error && <p className="text-sm text-red-600">{version.parse_error}</p>}
                {version.id !== selectedDoc?.active_version_id && (
                  <button type="button" className="btn-secondary" onClick={() => restoreMutation.mutate(version.id)} disabled={restoreMutation.isPending}>
                    <span>Restore this version</span>
                  </button>
                )}
              </div>
            ))
          )}
        </div>
      </ExpertDrawer>

      <ExpertDrawer
        open={structureDrawerOpen}
        onClose={() => setStructureDrawerOpen(false)}
        title={selectedDoc ? `${selectedDoc.display_name} structure` : 'Document structure'}
        description="A raw structure view is kept in an expert drawer to avoid overwhelming the main workflow."
      >
        {loadingStructure ? (
          <div className="empty-state min-h-[160px]">
            <Loader2 size={20} className="animate-spin text-blue-600" />
            <p className="text-sm text-slate-500">Loading structure…</p>
          </div>
        ) : (
          <pre className="max-h-[70vh] overflow-auto rounded-[24px] bg-slate-950 p-4 text-xs leading-6 text-slate-100">
            {JSON.stringify(structure, null, 2)}
          </pre>
        )}
      </ExpertDrawer>
    </div>
  );
};
