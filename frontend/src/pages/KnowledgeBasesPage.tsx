import React, { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowRight, BookMarked, Database, Loader2, Plus, Save, X } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

import { EmptyState, Field, GlassPanel, InlineAlert, KeyMetric, SectionToolbar, StatusBadge } from '../components/ui/workbench';
import { documentsApi } from '../features/documents/api';
import { knowledgeBasesApi } from '../features/knowledge-bases/api';
import type { KnowledgeBaseMutationPayload } from '../features/knowledge-bases/types';
import { getErrorMessage } from '../lib/utils';

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

const getKnowledgeBaseStatusTone = (status: string): 'default' | 'success' | 'warning' => {
  if (status === 'active') return 'success';
  if (status === 'disabled') return 'warning';
  return 'default';
};

export const KnowledgeBasesPage: React.FC = () => {
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const [isCreateMode, setIsCreateMode] = useState(false);
  const [formState, setFormState] = useState<KnowledgeBaseFormState>(EMPTY_FORM);
  const [createError, setCreateError] = useState('');

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
    error: documentsError,
  } = useQuery({
    queryKey: ['documents'],
    queryFn: () => documentsApi.list(),
  });

  const createMutation = useMutation({
    mutationFn: (payload: KnowledgeBaseMutationPayload) => knowledgeBasesApi.create(payload),
    onSuccess: (knowledgeBase) => {
      setCreateError('');
      setIsCreateMode(false);
      setFormState(EMPTY_FORM);
      queryClient.invalidateQueries({ queryKey: ['knowledge-bases'] });
      // Upon successful creation, jump straight to the management page
      navigate(`/knowledge-bases/${knowledgeBase.id}`);
    },
    onError: (error: unknown) => {
      setCreateError(getErrorMessage(error, 'Knowledge Base create failed'));
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

  const handleCreateSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const name = formState.name.trim();
    if (!name) {
      setCreateError('Knowledge Base name is required');
      return;
    }

    createMutation.mutate({
      name,
      description: formState.description.trim() ? formState.description.trim() : null,
      status: formState.status,
      retrieval_profile: {},
      documents: [], // initially empty, user will add via detail page
    });
  };

  const handleCreateModeToggle = () => {
    if (isCreateMode) {
      setIsCreateMode(false);
      setFormState(EMPTY_FORM);
      setCreateError('');
    } else {
      setIsCreateMode(true);
    }
  };

  return (
    <div className="space-y-8">
      <SectionToolbar
        title="Knowledge Bases"
        description="Select a Knowledge Base to manage its documents and settings, or create a new one to scope operational retrievals."
        actions={
          <button type="button" className="btn-primary" onClick={handleCreateModeToggle}>
            {isCreateMode ? <X size={16} /> : <Plus size={16} />}
            <span>{isCreateMode ? 'Cancel Creation' : 'Create Knowledge Base'}</span>
          </button>
        }
      />

      {primaryError && (
        <InlineAlert tone="danger" title="Knowledge Base page failed to load">
          {primaryError}
        </InlineAlert>
      )}

      {/* Top Metrics Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KeyMetric label="Knowledge Bases" value={knowledgeBases.length} hint="Current Workspace catalog" />
        <KeyMetric label="Enabled" value={knowledgeBases.filter((kb) => kb.status === 'active').length} hint="Ready for reuse" />
        <KeyMetric label="Enabled Documents" value={totalEnabledMemberships} hint="Across all Knowledge Bases" />
        <KeyMetric label="Unassigned Documents" value={unassignedDocuments} hint="Documents not in any Knowledge Base" />
      </div>

      {/* Inline Create Form overlay (only visible when isCreateMode is true) */}
      {isCreateMode && (
        <GlassPanel title="Create New Knowledge Base" subtitle="Define the metadata now, then you can add documents on the next page.">
          <form className="space-y-6" onSubmit={handleCreateSubmit}>
            {createError && <InlineAlert tone="danger" title="Creation Failed">{createError}</InlineAlert>}

            <div className="grid gap-6 lg:grid-cols-2">
              <div className="space-y-4">
                <Field label="Knowledge Base Name" required>
                  <input
                    className="field"
                    autoFocus
                    value={formState.name}
                    onChange={(e) => setFormState({ ...formState, name: e.target.value })}
                    placeholder="e.g. Airport Operations Manual"
                  />
                </Field>
                <Field label="Description" hint="Explain what this covers so others know when to use it.">
                  <textarea
                    className="field min-h-[105px] resize-y"
                    value={formState.description}
                    onChange={(e) => setFormState({ ...formState, description: e.target.value })}
                    placeholder="SOPs, emergency protocols, and shift guidelines..."
                  />
                </Field>
              </div>
              <div className="space-y-4">
                <Field label="Initial Status" hint="Disabled Knowledge Bases stay visible but shouldn't be treated as active targets for search.">
                  <select
                    className="field"
                    value={formState.status}
                    onChange={(e) => setFormState({ ...formState, status: e.target.value })}
                  >
                    <option value="active">Enabled (Active)</option>
                    <option value="disabled">Disabled (Archived)</option>
                  </select>
                </Field>
                <div className="pt-4 mt-auto">
                  <button type="submit" className="btn-primary w-full" disabled={createMutation.isPending}>
                    {createMutation.isPending ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
                    <span>{createMutation.isPending ? 'Creating…' : 'Create & Continue'}</span>
                  </button>
                </div>
              </div>
            </div>
          </form>
        </GlassPanel>
      )}

      {/* Main Grid View */}
      {knowledgeBasesLoading ? (
        <div className="flex items-center justify-center py-32 opacity-70">
          <Loader2 size={32} className="animate-spin text-blue-500" />
          <span className="ml-4 text-slate-500 font-medium">Loading Knowledge Bases…</span>
        </div>
      ) : knowledgeBases.length === 0 && !isCreateMode ? (
        <EmptyState
          title="No Knowledge Bases yet"
          description="Create the first Knowledge Base for this Workspace to categorize and group documents."
          action={
            <button type="button" className="btn-primary" onClick={handleCreateModeToggle}>
              <Plus size={16} />
              <span>Create Knowledge Base</span>
            </button>
          }
        />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-6">
          {knowledgeBases.map((kb) => {
            const enabledDocs = kb.documents.filter((d) => d.enabled).length;
            const totalDocs = kb.documents.length;
            return (
              <button
                type="button"
                key={kb.id}
                onClick={() => navigate(`/knowledge-bases/${kb.id}`)}
                className="group relative flex flex-col items-start gap-4 text-left rounded-3xl border border-white/60 bg-white/40 p-6 shadow-sm backdrop-blur-xl transition-all hover:-translate-y-1 hover:border-blue-200 hover:bg-white/70 hover:shadow-xl focus:outline-none focus:ring-2 focus:ring-blue-400 focus:ring-offset-2"
              >
                <div className="flex w-full items-start justify-between gap-3">
                  <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-50 to-white text-blue-600 shadow-sm ring-1 ring-slate-100 transition-transform group-hover:scale-110">
                    <BookMarked size={22} className="opacity-90" />
                  </div>
                  <div className="flex flex-col items-end gap-2">
                    <StatusBadge tone={getKnowledgeBaseStatusTone(kb.status)}>
                      {kb.status === 'active' ? 'Enabled' : kb.status === 'disabled' ? 'Disabled' : kb.status}
                    </StatusBadge>
                  </div>
                </div>

                <div className="w-full space-y-1.5 min-h-[72px]">
                  <h3 className="line-clamp-1 text-lg font-semibold tracking-tight text-slate-900 group-hover:text-blue-700">
                    {kb.name}
                  </h3>
                  <p className="line-clamp-2 text-sm leading-relaxed text-slate-500">
                    {kb.description || 'No description provided.'}
                  </p>
                </div>

                <div className="mt-auto w-full pt-4 border-t border-slate-200/50">
                  <div className="flex flex-wrap items-center justify-between gap-y-2 text-xs font-medium uppercase tracking-wider text-slate-400">
                    <div className="flex items-center gap-1.5">
                      <Database size={14} className="text-slate-400" />
                      <span>{enabledDocs} / {totalDocs} Docs</span>
                    </div>
                    <span className="flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100 text-blue-600">
                      Manage <ArrowRight size={14} />
                    </span>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
};
