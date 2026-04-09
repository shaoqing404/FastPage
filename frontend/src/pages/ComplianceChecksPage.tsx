import React, { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Loader2, Plus, ShieldCheck } from 'lucide-react';
import { Link } from 'react-router-dom';

import { ComplianceCheckEditor } from '../components/compliance/ComplianceCheckEditor';
import { ComplianceCheckList } from '../components/compliance/ComplianceCheckList';
import type { ComplianceCheckDraft } from '../components/compliance/types';
import { DEFAULT_COMPLIANCE_VERDICTS } from '../components/compliance/types';
import { EmptyState, GlassPanel, InlineAlert, KeyMetric, SectionToolbar } from '../components/ui/workbench';
import { complianceApi } from '../features/compliance';
import type { ComplianceCheck, ComplianceCheckMutationPayload, ComplianceVerdict } from '../features/compliance/types';
import { knowledgeBasesApi } from '../features/knowledge-bases/api';
import type { KnowledgeBase } from '../features/knowledge-bases/types';
import { getErrorMessage } from '../lib/utils';

const EMPTY_DRAFT: ComplianceCheckDraft = {
  name: '',
  description: '',
  status: 'active',
  knowledge_base_id: '',
  query_template: '',
  instructions: '',
  allowed_values: DEFAULT_COMPLIANCE_VERDICTS,
  default_on_gap: 'inconclusive',
  include_summary: true,
  include_answer: true,
  include_evidence: true,
  include_gaps: true,
  include_conflicts: true,
  per_document_top_k: '5',
  global_top_k: '8',
  selection_mode: 'outline_llm',
  max_context_pages: '20',
  max_context_tokens: '12000',
  temperature: '0',
};

const serializeDraft = (draft: ComplianceCheckDraft): ComplianceCheckMutationPayload => ({
  name: draft.name.trim(),
  description: draft.description.trim() ? draft.description.trim() : null,
  status: draft.status,
  target: {
    mode: 'knowledge_base',
    knowledge_base_id: draft.knowledge_base_id,
  },
  query_template: draft.query_template.trim(),
  instructions: draft.instructions.trim() ? draft.instructions.trim() : null,
  verdict_policy: {
    allowed_values: draft.allowed_values,
    default_on_gap: draft.default_on_gap,
  },
  output_config: {
    include_summary: draft.include_summary,
    include_answer: draft.include_answer,
    include_evidence: draft.include_evidence,
    include_gaps: draft.include_gaps,
    include_conflicts: draft.include_conflicts,
  },
  retrieval_config: {
    per_document_top_k: parseRequiredInteger(draft.per_document_top_k, 5),
    global_top_k: parseRequiredInteger(draft.global_top_k, 8),
    selection_mode: draft.selection_mode,
    max_context_pages: parseOptionalInteger(draft.max_context_pages),
    max_context_tokens: parseOptionalInteger(draft.max_context_tokens),
  },
  generation_config: {
    temperature: parseOptionalFloat(draft.temperature),
  },
});

const deriveDraft = (check: ComplianceCheck | null): ComplianceCheckDraft =>
  check
    ? {
        name: check.name,
        description: check.description || '',
        status: check.status,
        knowledge_base_id: check.target.knowledge_base_id,
        query_template: check.query_template,
        instructions: check.instructions || '',
        allowed_values: sortVerdicts(check.verdict_policy.allowed_values),
        default_on_gap: check.verdict_policy.default_on_gap,
        include_summary: check.output_config.include_summary,
        include_answer: check.output_config.include_answer,
        include_evidence: check.output_config.include_evidence,
        include_gaps: check.output_config.include_gaps,
        include_conflicts: check.output_config.include_conflicts,
        per_document_top_k: String(check.retrieval_config.per_document_top_k),
        global_top_k: String(check.retrieval_config.global_top_k),
        selection_mode: check.retrieval_config.selection_mode === 'lexical_fallback' ? 'lexical_fallback' : 'outline_llm',
        max_context_pages:
          typeof check.retrieval_config.max_context_pages === 'number' ? String(check.retrieval_config.max_context_pages) : '',
        max_context_tokens:
          typeof check.retrieval_config.max_context_tokens === 'number' ? String(check.retrieval_config.max_context_tokens) : '',
        temperature: typeof check.generation_config.temperature === 'number' ? String(check.generation_config.temperature) : '',
      }
    : EMPTY_DRAFT;

export const ComplianceChecksPage: React.FC = () => {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState('');
  const [selectedCheckId, setSelectedCheckId] = useState('');
  const [isCreateMode, setIsCreateMode] = useState(false);
  const [draftSourceKey, setDraftSourceKey] = useState('empty');
  const [draftState, setDraftState] = useState<ComplianceCheckDraft>(EMPTY_DRAFT);
  const [editorError, setEditorError] = useState('');
  const [savedMessage, setSavedMessage] = useState('');
  const [pageNotice, setPageNotice] = useState('');

  const {
    data: checks = [],
    isLoading: checksLoading,
    error: checksError,
  } = useQuery({
    queryKey: ['compliance-checks'],
    queryFn: () => complianceApi.checks.list(),
  });

  const {
    data: knowledgeBases = [],
    isLoading: knowledgeBasesLoading,
    error: knowledgeBasesError,
  } = useQuery({
    queryKey: ['knowledge-bases'],
    queryFn: () => knowledgeBasesApi.list(),
  });

  const knowledgeBasesById = useMemo(() => new Map(knowledgeBases.map((knowledgeBase) => [knowledgeBase.id, knowledgeBase])), [knowledgeBases]);

  const effectiveSelectedCheckId = useMemo(() => {
    if (isCreateMode) return '';
    if (selectedCheckId && checks.some((check) => check.id === selectedCheckId)) {
      return selectedCheckId;
    }
    return checks[0]?.id || '';
  }, [checks, isCreateMode, selectedCheckId]);

  const selectedCheck = useMemo(
    () => checks.find((check) => check.id === effectiveSelectedCheckId) || null,
    [checks, effectiveSelectedCheckId],
  );

  const currentSourceKey = isCreateMode ? 'create' : effectiveSelectedCheckId || 'empty';
  const draft = draftSourceKey === currentSourceKey ? draftState : isCreateMode ? EMPTY_DRAFT : deriveDraft(selectedCheck);
  const baselineDraft = isCreateMode ? EMPTY_DRAFT : deriveDraft(selectedCheck);
  const isDirty = JSON.stringify(serializeDraft(draft)) !== JSON.stringify(serializeDraft(baselineDraft));
  const activeChecks = checks.filter((check) => check.status === 'active').length;
  const coveredKnowledgeBaseCount = new Set(checks.map((check) => check.target.knowledge_base_id)).size;
  const primaryError =
    checksError || knowledgeBasesError
      ? [checksError, knowledgeBasesError].filter(Boolean).map((error) => getErrorMessage(error, 'Failed to load compliance data')).join(' · ')
      : '';

  const stageDraft = (nextDraft: ComplianceCheckDraft) => {
    setDraftSourceKey(currentSourceKey);
    setDraftState({
      ...nextDraft,
      allowed_values: sortVerdicts(nextDraft.allowed_values),
      default_on_gap: resolveDefaultOnGap(nextDraft.allowed_values, nextDraft.default_on_gap),
    });
    setEditorError('');
    setSavedMessage('');
    setPageNotice('');
  };

  const createMutation = useMutation({
    mutationFn: (payload: ComplianceCheckMutationPayload) => complianceApi.checks.create(payload),
    onSuccess: async (createdCheck) => {
      setIsCreateMode(false);
      setSelectedCheckId(createdCheck.id);
      setDraftSourceKey('empty');
      setEditorError('');
      setSavedMessage(`Created "${createdCheck.name}" and bound it to ${knowledgeBasesById.get(createdCheck.target.knowledge_base_id)?.name || 'the selected Knowledge Base'}.`);
      await queryClient.invalidateQueries({ queryKey: ['compliance-checks'] });
    },
    onError: (error: unknown) => {
      setEditorError(getErrorMessage(error, 'Compliance Check create failed'));
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ checkId, payload }: { checkId: string; payload: ComplianceCheckMutationPayload }) => complianceApi.checks.update(checkId, payload),
    onSuccess: async (updatedCheck) => {
      setDraftSourceKey('empty');
      setEditorError('');
      setSavedMessage(`Saved "${updatedCheck.name}" for ${knowledgeBasesById.get(updatedCheck.target.knowledge_base_id)?.name || 'the selected Knowledge Base'}.`);
      await queryClient.invalidateQueries({ queryKey: ['compliance-checks'] });
    },
    onError: (error: unknown) => {
      setEditorError(getErrorMessage(error, 'Compliance Check update failed'));
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (checkId: string) => complianceApi.checks.delete(checkId),
    onSuccess: async (_, deletedCheckId) => {
      const deletedCheck = checks.find((check) => check.id === deletedCheckId) || null;
      setSelectedCheckId('');
      setIsCreateMode(false);
      setDraftSourceKey('empty');
      setDraftState(EMPTY_DRAFT);
      setEditorError('');
      setSavedMessage('');
      setPageNotice(deletedCheck ? `Deleted "${deletedCheck.name}".` : 'Deleted compliance check.');
      await queryClient.invalidateQueries({ queryKey: ['compliance-checks'] });
    },
    onError: (error: unknown) => {
      setEditorError(getErrorMessage(error, 'Compliance Check delete failed'));
    },
  });

  const handleSelectCheck = (checkId: string) => {
    setSelectedCheckId(checkId);
    setIsCreateMode(false);
    setDraftSourceKey('empty');
    setEditorError('');
    setSavedMessage('');
    setPageNotice('');
  };

  const handleCreateMode = () => {
    setSelectedCheckId('');
    setIsCreateMode(true);
    setDraftSourceKey('empty');
    setEditorError('');
    setSavedMessage('');
    setPageNotice('');
  };

  const handleReset = () => {
    setDraftSourceKey('empty');
    setDraftState(isCreateMode ? EMPTY_DRAFT : deriveDraft(selectedCheck));
    setEditorError('');
    setSavedMessage('');
    setPageNotice('');
  };

  const handleSave = () => {
    const validationError = validateDraft(draft, knowledgeBasesById);
    if (validationError) {
      setEditorError(validationError);
      setSavedMessage('');
      return;
    }

    const payload = serializeDraft(draft);
    if (isCreateMode) {
      createMutation.mutate(payload);
      return;
    }

    if (!selectedCheck) {
      setEditorError('Select a Compliance Check first.');
      return;
    }

    updateMutation.mutate({ checkId: selectedCheck.id, payload });
  };

  const handleDelete = () => {
    if (!selectedCheck) return;
    const confirmed = window.confirm(`Delete "${selectedCheck.name}"? This cannot be undone.`);
    if (!confirmed) return;
    deleteMutation.mutate(selectedCheck.id);
  };

  const savePending = createMutation.isPending || updateMutation.isPending;
  const editorLoading = checksLoading || knowledgeBasesLoading;
  const saveBlocked =
    savePending ||
    deleteMutation.isPending ||
    !draft.name.trim() ||
    !draft.query_template.trim() ||
    !draft.knowledge_base_id ||
    !knowledgeBasesById.has(draft.knowledge_base_id);

  return (
    <div className="space-y-8">
      <SectionToolbar
        title="Compliance Checks"
        description="Manage saved compliance definitions as Knowledge Base-backed product capabilities instead of interface-level CRUD payloads."
        actions={
          <button type="button" className="btn-primary" onClick={handleCreateMode}>
            <Plus size={16} />
            <span>Create Check</span>
          </button>
        }
      />

      {primaryError && (
        <InlineAlert tone="danger" title="Compliance Checks page failed to load">
          {primaryError}
        </InlineAlert>
      )}

      {pageNotice && !primaryError && (
        <InlineAlert tone="success" title="Catalog updated">
          {pageNotice}
        </InlineAlert>
      )}

      <div className="grid grid-cols-4 gap-4">
        <KeyMetric label="Checks" value={checks.length} hint="Saved compliance definitions" />
        <KeyMetric label="Enabled" value={activeChecks} hint="Ready for use" />
        <KeyMetric label="Knowledge Bases" value={coveredKnowledgeBaseCount} hint="Referenced by checks" />
        <KeyMetric label="Available KBs" value={knowledgeBases.length} hint="Workspace selection targets" />
      </div>

      <div className="grid gap-6 xl:grid-cols-[0.82fr_1.18fr]">
        <GlassPanel
          title="Check catalog"
          subtitle="Browse saved checks by Knowledge Base, verdict behavior, and availability."
          actions={<input className="field w-64" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search checks" />}
        >
          <ComplianceCheckList
            checks={checks}
            knowledgeBasesById={knowledgeBasesById}
            selectedCheckId={effectiveSelectedCheckId}
            search={search}
            isLoading={checksLoading}
            onSelect={handleSelectCheck}
            onCreate={handleCreateMode}
          />
        </GlassPanel>

        <GlassPanel
          title={isCreateMode ? 'Create Compliance Check' : selectedCheck?.name || 'Compliance Check details'}
          subtitle={
            isCreateMode
              ? 'Bind a new check to a Knowledge Base, define its question, and tune verdict and retrieval behavior.'
              : 'Edit the saved compliance definition and keep its operator-facing policy readable.'
          }
        >
          {editorLoading && !selectedCheck && !isCreateMode ? (
            <div className="empty-state min-h-[460px]">
              <Loader2 size={20} className="animate-spin text-blue-600" />
              <p className="text-sm text-slate-500">Loading Compliance Check details…</p>
            </div>
          ) : checks.length === 0 && !isCreateMode ? (
            <EmptyState
              title="Compliance console starts here"
              description={
                knowledgeBases.length === 0
                  ? 'Create a Knowledge Base first, then define the first Compliance Check against that reusable target.'
                  : 'Create the first Compliance Check for this Workspace to turn compliance logic into a reusable product capability.'
              }
              action={
                knowledgeBases.length === 0 ? (
                  <Link to="/knowledge-bases" className="btn-primary">
                    <ShieldCheck size={16} />
                    <span>Open Knowledge Bases</span>
                  </Link>
                ) : (
                  <button type="button" className="btn-primary" onClick={handleCreateMode}>
                    <ShieldCheck size={16} />
                    <span>Create Check</span>
                  </button>
                )
              }
            />
          ) : isCreateMode || selectedCheck ? (
            <ComplianceCheckEditor
              draft={draft}
              knowledgeBases={knowledgeBases}
              selectedCheck={selectedCheck}
              mode={isCreateMode ? 'create' : 'edit'}
              isDirty={isDirty}
              saveBlocked={saveBlocked}
              savePending={savePending}
              deletePending={deleteMutation.isPending}
              error={editorError}
              savedMessage={savedMessage}
              onChange={stageDraft}
              onSave={handleSave}
              onReset={handleReset}
              onDelete={handleDelete}
            />
          ) : (
            <EmptyState title="Select a Compliance Check" description="Choose a check from the catalog or create a new Knowledge Base-backed definition." />
          )}
        </GlassPanel>
      </div>

      <GlassPanel title="Workspace readiness" subtitle="A quick read on whether current Knowledge Bases are available as compliance targets.">
        {knowledgeBasesLoading ? (
          <div className="empty-state min-h-[220px]">
            <Loader2 size={20} className="animate-spin text-blue-600" />
            <p className="text-sm text-slate-500">Loading Knowledge Bases…</p>
          </div>
        ) : knowledgeBases.length === 0 ? (
          <EmptyState title="No Knowledge Bases yet" description="Create a Knowledge Base on the Knowledge Bases page before defining Compliance Checks." />
        ) : (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {knowledgeBases.map((knowledgeBase) => {
              const boundChecks = checks.filter((check) => check.target.knowledge_base_id === knowledgeBase.id).length;

              return (
                <div key={knowledgeBase.id} className="surface-soft space-y-3 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate font-medium text-slate-900">{knowledgeBase.name}</p>
                      <p className="line-clamp-2 text-sm text-slate-500">{knowledgeBase.description || 'No description yet.'}</p>
                    </div>
                    <span
                      className={`status-badge ${
                        knowledgeBase.status === 'active'
                          ? 'status-success'
                          : knowledgeBase.status === 'disabled'
                            ? 'status-warning'
                            : 'status-default'
                      }`}
                    >
                      {knowledgeBase.status === 'active' ? 'Enabled' : knowledgeBase.status === 'disabled' ? 'Disabled' : knowledgeBase.status}
                    </span>
                  </div>
                  <p className="text-sm text-slate-500">
                    {boundChecks > 0 ? `${boundChecks} Compliance Check${boundChecks > 1 ? 's' : ''} target this Knowledge Base.` : 'No Compliance Checks target this Knowledge Base yet.'}
                  </p>
                  <div className="flex flex-wrap gap-2 text-xs text-slate-500">
                    <span>{knowledgeBase.documents.filter((document) => document.enabled).length} enabled documents</span>
                    <span>{knowledgeBase.documents.length} total members</span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </GlassPanel>
    </div>
  );
};

const validateDraft = (draft: ComplianceCheckDraft, knowledgeBasesById: Map<string, KnowledgeBase>) => {
  if (!draft.name.trim()) return 'Check name is required.';
  if (!draft.knowledge_base_id) return 'Knowledge Base is required.';
  if (!knowledgeBasesById.has(draft.knowledge_base_id)) return 'Selected Knowledge Base is unavailable in the current Workspace.';
  if (!draft.query_template.trim()) return 'Query template is required.';
  if (draft.allowed_values.length === 0) return 'Select at least one allowed verdict.';
  if (!draft.allowed_values.includes(draft.default_on_gap)) return 'Default on gap must be one of the allowed verdicts.';

  const requiredIntegers = [
    ['Per-document top K', draft.per_document_top_k],
    ['Global top K', draft.global_top_k],
  ] as const;

  for (const [label, value] of requiredIntegers) {
    if (!isPositiveIntegerText(value)) {
      return `${label} must be a whole number greater than 0.`;
    }
  }

  const optionalIntegers = [
    ['Max context pages', draft.max_context_pages],
    ['Max context tokens', draft.max_context_tokens],
  ] as const;

  for (const [label, value] of optionalIntegers) {
    if (value.trim() && !isPositiveIntegerText(value)) {
      return `${label} must be a whole number greater than 0.`;
    }
  }

  if (draft.temperature.trim()) {
    const temperature = Number(draft.temperature);
    if (!Number.isFinite(temperature) || temperature < 0) {
      return 'Temperature must be 0 or a positive number.';
    }
  }

  return null;
};

const parseRequiredInteger = (value: string, fallback: number) => {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
};

const parseOptionalInteger = (value: string) => {
  if (!value.trim()) return null;
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
};

const parseOptionalFloat = (value: string) => {
  if (!value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const isPositiveIntegerText = (value: string) => {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0;
};

const resolveDefaultOnGap = (allowedValues: ComplianceVerdict[], currentDefault: ComplianceVerdict) => {
  const sortedAllowedValues = sortVerdicts(allowedValues);
  return sortedAllowedValues.includes(currentDefault) ? currentDefault : sortedAllowedValues[0] || 'inconclusive';
};

const sortVerdicts = (values: ComplianceVerdict[]) => {
  const seen = new Set<ComplianceVerdict>();
  const knownVerdicts = DEFAULT_COMPLIANCE_VERDICTS.filter((verdict) => values.includes(verdict));
  const customVerdicts = values.filter((verdict) => !DEFAULT_COMPLIANCE_VERDICTS.includes(verdict) && !seen.has(verdict));

  knownVerdicts.forEach((verdict) => seen.add(verdict));

  const uniqueCustomVerdicts = customVerdicts.filter((verdict) => {
    if (seen.has(verdict)) return false;
    seen.add(verdict);
    return true;
  });

  return [...knownVerdicts, ...uniqueCustomVerdicts];
};
