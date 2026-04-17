import React, { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Save, Trash2, Wand2 } from 'lucide-react';

import { KnowledgeBaseBindingPanel } from '../components/skills/KnowledgeBaseBindingPanel';
import { SkillLibraryCard } from '../components/skills/SkillLibraryCard';
import type { KnowledgeBaseSummary, SkillConsoleItem } from '../components/skills/types';
import { getEnabledKnowledgeBaseDocuments } from '../components/skills/types';
import { EmptyState, ExpertDrawer, Field, GlassPanel, InlineAlert, KeyMetric, SectionToolbar } from '../components/ui/workbench';
import { documentsApi } from '../features/documents/api';
import { providersApi } from '../features/providers/api';
import { skillsApi } from '../features/skills/api';
import { apiClient } from '../lib/api/client';
import { getErrorMessage, resolveProviderById } from '../lib/utils';

type EditableSkill = Partial<SkillConsoleItem> & {
  request_config_text: string;
  conversation_expert_text: string;
  retrieval_expert_text: string;
  generation_expert_text: string;
  query_rewrite_with_history: boolean;
  include_history: boolean;
  include_assistant_messages: boolean;
  history_turn_limit: string;
  history_token_budget: string;
  top_k: string;
  selection_mode: string;
  max_context_pages: string;
  max_context_tokens: string;
  temperature: string;
};

type StoredUserContext = {
  workspace_id?: string | null;
};

const DEFAULT_CONVERSATION_CONFIG = {
  query_rewrite_with_history: true,
  include_history: true,
  include_assistant_messages: true,
  history_turn_limit: 4,
  history_token_budget: 1800,
};

const stringify = (value?: Record<string, unknown>) => JSON.stringify(value || {}, null, 2);

const parseJson = (value: string, label: string) => {
  if (!value.trim()) return {};
  try {
    return JSON.parse(value);
  } catch {
    throw new Error(`${label} must be valid JSON`);
  }
};

const toNumberishText = (value: unknown, fallback = '') => {
  if (typeof value === 'number') return String(value);
  if (typeof value === 'string') return value;
  return fallback;
};

const toOptionalNumber = (value: string) => {
  if (!value.trim()) return undefined;
  return Number(value);
};

const readCurrentWorkspaceId = () => {
  if (typeof window === 'undefined') return null;
  try {
    const raw = localStorage.getItem('user');
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredUserContext;
    return typeof parsed.workspace_id === 'string' && parsed.workspace_id ? parsed.workspace_id : null;
  } catch {
    return null;
  }
};

const listSkills = async (): Promise<SkillConsoleItem[]> => skillsApi.list() as Promise<SkillConsoleItem[]>;

const listKnowledgeBases = async (workspaceId: string): Promise<KnowledgeBaseSummary[]> => {
  const { data } = await apiClient.get<KnowledgeBaseSummary[]>(`/workspaces/${workspaceId}/knowledge-bases`);
  return data;
};

const normalizeSkill = (skill?: Partial<SkillConsoleItem>, providerDefaultModel?: string): EditableSkill => {
  const conversation = {
    ...DEFAULT_CONVERSATION_CONFIG,
    ...((skill?.conversation_config || {}) as Record<string, unknown>),
  };
  const retrieval = (skill?.retrieval_config || {}) as Record<string, unknown>;
  const generation = (skill?.generation_config || {}) as Record<string, unknown>;
  return {
    id: skill?.id,
    name: skill?.name || '',
    description: skill?.description || '',
    system_prompt: skill?.system_prompt || '',
    knowledge_base_id: skill?.knowledge_base_id || null,
    provider_id: skill?.provider_id || null,
    model: skill?.model || providerDefaultModel || '',
    document_ids: skill?.document_ids || [],
    is_active: skill?.is_active ?? true,
    request_config_text: stringify(skill?.request_config),
    conversation_expert_text: stringify(skill?.conversation_config),
    retrieval_expert_text: stringify(skill?.retrieval_config),
    generation_expert_text: stringify(skill?.generation_config),
    query_rewrite_with_history: conversation.query_rewrite_with_history !== false,
    include_history: conversation.include_history !== false,
    include_assistant_messages: conversation.include_assistant_messages !== false,
    history_turn_limit: toNumberishText(conversation.history_turn_limit, String(DEFAULT_CONVERSATION_CONFIG.history_turn_limit)),
    history_token_budget: toNumberishText(conversation.history_token_budget, String(DEFAULT_CONVERSATION_CONFIG.history_token_budget)),
    top_k: toNumberishText(retrieval.top_k, '5'),
    selection_mode: typeof retrieval.selection_mode === 'string' ? retrieval.selection_mode : 'outline_llm',
    max_context_pages: toNumberishText(retrieval.max_context_pages),
    max_context_tokens: toNumberishText(retrieval.max_context_tokens),
    temperature: toNumberishText(generation.temperature, '0'),
  };
};

export const SkillsPage: React.FC = () => {
  const queryClient = useQueryClient();
  const [editingSkill, setEditingSkill] = useState<EditableSkill | null>(null);
  const [editorError, setEditorError] = useState('');
  const [expertOpen, setExpertOpen] = useState(false);
  const [modelDirty, setModelDirty] = useState(false);

  const skillsQuery = useQuery({ queryKey: ['skills'], queryFn: listSkills });
  const documentsQuery = useQuery({ queryKey: ['documents'], queryFn: () => documentsApi.list() });
  const providersQuery = useQuery({ queryKey: ['providers'], queryFn: providersApi.list });

  const workspaceId = useMemo(() => {
    return readCurrentWorkspaceId() || skillsQuery.data?.find((skill) => skill.workspace_id)?.workspace_id || null;
  }, [skillsQuery.data]);

  const knowledgeBasesQuery = useQuery({
    queryKey: ['knowledge-bases', workspaceId],
    queryFn: () => listKnowledgeBases(workspaceId!),
    enabled: Boolean(workspaceId),
  });

  const skills = useMemo(() => skillsQuery.data || [], [skillsQuery.data]);
  const documents = useMemo(() => documentsQuery.data || [], [documentsQuery.data]);
  const providers = useMemo(() => providersQuery.data || [], [providersQuery.data]);
  const knowledgeBases = useMemo(() => knowledgeBasesQuery.data || [], [knowledgeBasesQuery.data]);

  const documentsById = useMemo(() => new Map(documents.map((document) => [document.id, document])), [documents]);
  const knowledgeBasesById = useMemo(() => new Map(knowledgeBases.map((knowledgeBase) => [knowledgeBase.id, knowledgeBase])), [knowledgeBases]);

  const selectedProvider = resolveProviderById(editingSkill?.provider_id ?? null, providers);
  const selectedKnowledgeBase = editingSkill?.knowledge_base_id ? knowledgeBasesById.get(editingSkill.knowledge_base_id) || null : null;

  const providerModelOptions = useMemo(() => {
    if (!selectedProvider) return [];
    return selectedProvider.supported_models?.length ? selectedProvider.supported_models : [selectedProvider.default_model];
  }, [selectedProvider]);

  const activeSkillCount = skills.filter((skill) => skill.is_active !== false).length;
  const kbBackedSkillCount = skills.filter((skill) => Boolean(skill.knowledge_base_id)).length;
  const legacyShimSkillCount = skills.length - kbBackedSkillCount;
  const saveBlocked =
    !editingSkill?.name?.trim() ||
    !editingSkill.system_prompt?.trim() ||
    !editingSkill.model?.trim() ||
    !editingSkill.knowledge_base_id ||
    !workspaceId;

  const saveMutation = useMutation({
    mutationFn: async (skill: EditableSkill): Promise<SkillConsoleItem> => {
      if (!workspaceId) {
        throw new Error('Workspace context is unavailable. Please sign in again.');
      }
      if (!skill.model?.trim()) {
        throw new Error('Model is required');
      }
      if (!skill.knowledge_base_id) {
        throw new Error('Knowledge base is required. document_ids stay compatibility-only in this workflow.');
      }

      const knowledgeBase = knowledgeBasesById.get(skill.knowledge_base_id);
      if (!knowledgeBase) {
        throw new Error('Selected knowledge base is unavailable in the current workspace.');
      }

      const request_config = parseJson(skill.request_config_text, 'Request config');
      const expertConversation = parseJson(skill.conversation_expert_text, 'Conversation expert config');
      const expertRetrieval = parseJson(skill.retrieval_expert_text, 'Retrieval expert config');
      const expertGeneration = parseJson(skill.generation_expert_text, 'Generation expert config');

      const conversation_config = {
        ...expertConversation,
        query_rewrite_with_history: skill.query_rewrite_with_history,
        include_history: skill.include_history,
        include_assistant_messages: skill.include_assistant_messages,
        ...(toOptionalNumber(skill.history_turn_limit) !== undefined ? { history_turn_limit: toOptionalNumber(skill.history_turn_limit) } : {}),
        ...(toOptionalNumber(skill.history_token_budget) !== undefined ? { history_token_budget: toOptionalNumber(skill.history_token_budget) } : {}),
      };

      const retrieval_config = {
        ...expertRetrieval,
        top_k: Number(skill.top_k || 5),
        selection_mode: skill.selection_mode || 'outline_llm',
        ...(toOptionalNumber(skill.max_context_pages) !== undefined ? { max_context_pages: toOptionalNumber(skill.max_context_pages) } : {}),
        ...(toOptionalNumber(skill.max_context_tokens) !== undefined ? { max_context_tokens: toOptionalNumber(skill.max_context_tokens) } : {}),
      };

      const generation_config = {
        ...expertGeneration,
        temperature: Number(skill.temperature || 0),
      };

      const name = skill.name?.trim();
      const systemPrompt = skill.system_prompt?.trim();

      if (!name) {
        throw new Error('Skill name is required');
      }

      if (!systemPrompt) {
        throw new Error('System prompt is required');
      }

      const payload = {
        name,
        description: skill.description || '',
        system_prompt: systemPrompt,
        knowledge_base_id: skill.knowledge_base_id,
        provider_id: skill.provider_id || null,
        model: skill.model.trim(),
        document_ids: getEnabledKnowledgeBaseDocuments(knowledgeBase).map((document) => document.document_id),
        request_config,
        conversation_config,
        retrieval_config,
        generation_config,
        is_active: skill.is_active !== false,
      };

      if (skill.id) {
        return skillsApi.update(skill.id, payload) as Promise<SkillConsoleItem>;
      }
      return skillsApi.create(payload) as Promise<SkillConsoleItem>;
    },
    onSuccess: (skill) => {
      const providerDefaultModel = skill.provider_id ? resolveProviderById(skill.provider_id, providers)?.default_model : undefined;
      setEditorError('');
      setExpertOpen(false);
      setEditingSkill(normalizeSkill(skill, providerDefaultModel));
      setModelDirty(Boolean(skill.model && providerDefaultModel && skill.model !== providerDefaultModel));
      queryClient.invalidateQueries({ queryKey: ['skills'] });
    },
    onError: (error: unknown) => {
      setEditorError(getErrorMessage(error, 'Failed to save skill'));
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => skillsApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['skills'] });
      setEditingSkill(null);
      setEditorError('');
    },
    onError: (error: unknown) => {
      setEditorError(getErrorMessage(error, 'Failed to delete skill'));
    },
  });

  const handleSelectSkill = (skill?: SkillConsoleItem) => {
    const providerDefaultModel = skill?.provider_id ? resolveProviderById(skill.provider_id, providers)?.default_model : undefined;
    setEditingSkill(normalizeSkill(skill, providerDefaultModel));
    setModelDirty(Boolean(skill?.model && providerDefaultModel && skill.model !== providerDefaultModel));
    setEditorError('');
  };

  const handleKnowledgeBaseChange = (knowledgeBaseId: string) => {
    if (!editingSkill) return;
    const knowledgeBase = knowledgeBasesById.get(knowledgeBaseId) || null;
    setEditingSkill({
      ...editingSkill,
      knowledge_base_id: knowledgeBaseId || null,
      document_ids: knowledgeBase ? getEnabledKnowledgeBaseDocuments(knowledgeBase).map((document) => document.document_id) : editingSkill.document_ids || [],
    });
  };

  const providerLoadError = providersQuery.isError ? getErrorMessage(providersQuery.error, 'Failed to load providers') : '';
  const documentLoadError = documentsQuery.isError ? getErrorMessage(documentsQuery.error, 'Failed to load documents') : '';
  const knowledgeBaseLoadError =
    knowledgeBasesQuery.isError ? getErrorMessage(knowledgeBasesQuery.error, 'Failed to load knowledge bases') : '';

  return (
    <div className="space-y-8">
      <SectionToolbar
        title="Skills"
        description="Operate KB-bound chat skills as a product console. Provider and model resolution stay aligned with Phase 2 dynamic provider semantics."
        actions={
          <button type="button" className="btn-primary" onClick={() => handleSelectSkill()}>
            <Plus size={16} />
            <span>New skill</span>
          </button>
        }
      />

      <div className="grid gap-4 md:grid-cols-4">
        <KeyMetric label="Total skills" value={skillsQuery.isLoading ? '...' : skills.length} hint="Workspace skill inventory" />
        <KeyMetric label="KB-backed" value={skillsQuery.isLoading ? '...' : kbBackedSkillCount} hint="Knowledge-base-first bindings" />
        <KeyMetric label="Legacy shim" value={skillsQuery.isLoading ? '...' : legacyShimSkillCount} hint="Still missing a KB binding" />
        <KeyMetric label="Active" value={skillsQuery.isLoading ? '...' : activeSkillCount} hint="Ready for operators" />
      </div>

      {!workspaceId && (
        <InlineAlert tone="danger" title="Workspace context missing">
          The current session has no workspace id, so knowledge-base APIs cannot be resolved. Sign in again before editing skills.
        </InlineAlert>
      )}

      <div className="grid grid-cols-[0.92fr_1.08fr] gap-6">
        <GlassPanel
          title="Skill control console"
          subtitle="Each skill should bind one knowledge base. document_ids remain compatibility-only for current runtime paths."
        >
          <div className="scroll-area max-h-[760px] space-y-3 overflow-auto pr-1">
            {skillsQuery.isLoading ? (
              <div className="empty-state min-h-[220px]">Loading skills…</div>
            ) : skillsQuery.isError ? (
              <InlineAlert
                tone="danger"
                title="Skills failed to load"
                action={
                  <button type="button" className="btn-secondary" onClick={() => skillsQuery.refetch()}>
                    Retry
                  </button>
                }
              >
                {getErrorMessage(skillsQuery.error, 'Failed to load skills')}
              </InlineAlert>
            ) : skills.length === 0 ? (
              <EmptyState
                title="No skills yet"
                description="Create the first KB-bound skill for this workspace. The editor will keep provider/model control while moving document scope to knowledge bases."
                action={
                  <button type="button" className="btn-primary" onClick={() => handleSelectSkill()}>
                    <Plus size={16} />
                    <span>New skill</span>
                  </button>
                }
              />
            ) : (
              skills.map((skill) => {
                const provider = resolveProviderById(skill.provider_id ?? null, providers);
                const knowledgeBase = skill.knowledge_base_id ? knowledgeBasesById.get(skill.knowledge_base_id) || null : null;
                return (
                  <SkillLibraryCard
                    key={skill.id}
                    skill={skill}
                    knowledgeBase={knowledgeBase}
                    providerLabel={provider?.name || 'Tenant default'}
                    selected={editingSkill?.id === skill.id}
                    onSelect={() => handleSelectSkill(skill)}
                  />
                );
              })
            )}
          </div>
        </GlassPanel>

        <GlassPanel
          title={editingSkill?.id ? 'Skill product configuration' : 'New skill'}
          subtitle="Bind the skill to one knowledge base, keep provider/model resolution explicit, and leave raw JSON in expert mode."
          actions={
            editingSkill ? (
              <div className="flex items-center gap-2">
                <button type="button" className="btn-secondary" onClick={() => setExpertOpen(true)}>
                  <Wand2 size={16} />
                  <span>Expert</span>
                </button>
                {editingSkill.id && (
                  <button
                    type="button"
                    className="btn-ghost text-red-600"
                    onClick={() => {
                      if (!editingSkill.id || !window.confirm('Delete this skill and its related sessions/runs?')) return;
                      deleteMutation.mutate(editingSkill.id);
                    }}
                  >
                    <Trash2 size={16} />
                    <span>{deleteMutation.isPending ? 'Deleting…' : 'Delete'}</span>
                  </button>
                )}
              </div>
            ) : null
          }
        >
          {editingSkill ? (
            <form
              className="space-y-6"
              onSubmit={(event) => {
                event.preventDefault();
                saveMutation.mutate(editingSkill);
              }}
            >
              {editorError && <InlineAlert tone="danger" title="Unable to save skill">{editorError}</InlineAlert>}
              {knowledgeBasesQuery.isSuccess && knowledgeBases.length === 0 && (
                <InlineAlert tone="warning" title="No knowledge bases in this workspace">
                  Create a knowledge base first. Skills now bind to KBs, and document_ids are only kept as a backend compatibility shim.
                </InlineAlert>
              )}
              {providerLoadError && (
                <InlineAlert tone="warning" title="Provider data is unavailable">
                  {providerLoadError}
                </InlineAlert>
              )}
              {documentLoadError && (
                <InlineAlert tone="warning" title="Document metadata is unavailable">
                  {documentLoadError}
                </InlineAlert>
              )}

              <div className="grid grid-cols-2 gap-5">
                <Field label="Skill name" required>
                  <input
                    value={editingSkill.name || ''}
                    onChange={(event) => setEditingSkill({ ...editingSkill, name: event.target.value })}
                    className="field"
                    placeholder="Technical manual assistant"
                    required
                  />
                </Field>

                <Field label="Availability" hint="Inactive skills stay configured but are clearly marked offline in the console.">
                  <div className="grid grid-cols-2 gap-3">
                    <button
                      type="button"
                      className={`rounded-[18px] border px-4 py-3 text-sm font-medium transition ${
                        editingSkill.is_active !== false
                          ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                          : 'border-white/80 bg-white/70 text-slate-600'
                      }`}
                      onClick={() => setEditingSkill({ ...editingSkill, is_active: true })}
                    >
                      Active
                    </button>
                    <button
                      type="button"
                      className={`rounded-[18px] border px-4 py-3 text-sm font-medium transition ${
                        editingSkill.is_active === false
                          ? 'border-amber-200 bg-amber-50 text-amber-700'
                          : 'border-white/80 bg-white/70 text-slate-600'
                      }`}
                      onClick={() => setEditingSkill({ ...editingSkill, is_active: false })}
                    >
                      Inactive
                    </button>
                  </div>
                </Field>

                <div className="col-span-2">
                  <Field label="Knowledge base" required hint="This is the primary binding. document_ids are derived only as a compatibility shim.">
                    <select
                      value={editingSkill.knowledge_base_id || ''}
                      onChange={(event) => handleKnowledgeBaseChange(event.target.value)}
                      className="field"
                      required
                    >
                      <option value="">Select a knowledge base</option>
                      {knowledgeBases.map((knowledgeBase) => (
                        <option key={knowledgeBase.id} value={knowledgeBase.id}>
                          {knowledgeBase.name} · {getEnabledKnowledgeBaseDocuments(knowledgeBase).length} docs · {knowledgeBase.status}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <div className="mt-3">
                    <KnowledgeBaseBindingPanel
                      knowledgeBase={selectedKnowledgeBase}
                      knowledgeBasesLoaded={knowledgeBasesQuery.isSuccess}
                      knowledgeBasesError={knowledgeBaseLoadError}
                      onRetry={workspaceId ? () => knowledgeBasesQuery.refetch() : undefined}
                      documentsById={documentsById}
                      legacyDocumentIds={editingSkill.document_ids || []}
                    />
                  </div>
                </div>

                <div className="col-span-2">
                  <Field label="Description">
                    <input
                      value={editingSkill.description || ''}
                      onChange={(event) => setEditingSkill({ ...editingSkill, description: event.target.value })}
                      className="field"
                      placeholder="Optional note for operators"
                    />
                  </Field>
                </div>

                <div className="col-span-2">
                  <Field label="System instruction" required>
                    <textarea
                      value={editingSkill.system_prompt || ''}
                      onChange={(event) => setEditingSkill({ ...editingSkill, system_prompt: event.target.value })}
                      className="field min-h-[150px]"
                      placeholder="Tell the skill how to behave, summarize, cite, and respond."
                      required
                    />
                  </Field>
                </div>

                <Field label="Provider" hint="Phase 2 provider resolution stays intact: explicit provider first, then tenant default, then backend system fallback.">
                  <select
                    value={editingSkill.provider_id || ''}
                    onChange={(event) => {
                      const nextProviderId = event.target.value || null;
                      const previousProvider = resolveProviderById(editingSkill.provider_id ?? null, providers);
                      const previousDefaultModel = previousProvider?.default_model || '';
                      const nextProvider = resolveProviderById(nextProviderId, providers);
                      const shouldSyncModel =
                        !editingSkill.model ||
                        !modelDirty ||
                        (previousDefaultModel && editingSkill.model === previousDefaultModel);

                      setEditingSkill({
                        ...editingSkill,
                        provider_id: nextProviderId,
                        model: shouldSyncModel ? nextProvider?.default_model || editingSkill.model : editingSkill.model,
                      });
                      if (shouldSyncModel) setModelDirty(false);
                    }}
                    className="field"
                  >
                    <option value="">Tenant default provider</option>
                    {providers.map((provider) => (
                      <option key={provider.id} value={provider.id}>
                        {provider.name} ({provider.provider_type})
                      </option>
                    ))}
                  </select>
                </Field>

                <Field
                  label="Model"
                  required
                  hint={
                    selectedProvider
                      ? `Defaults to ${selectedProvider.default_model} for ${selectedProvider.name}. The field remains overrideable and does not revert to a static model table.`
                      : 'Without an explicit provider, this model still participates in tenant/system resolution rather than a static model registry.'
                  }
                >
                  <input
                    list={selectedProvider ? `provider-model-options-${selectedProvider.id}` : undefined}
                    value={editingSkill.model || ''}
                    onChange={(event) => {
                      setEditingSkill({ ...editingSkill, model: event.target.value });
                      setModelDirty(true);
                    }}
                    className="field"
                    placeholder={selectedProvider?.default_model || 'gpt-4o-2024-11-20'}
                    required
                  />
                  {selectedProvider && (
                    <datalist id={`provider-model-options-${selectedProvider.id}`}>
                      {providerModelOptions.map((model) => (
                        <option key={model} value={model} />
                      ))}
                    </datalist>
                  )}
                  {providerModelOptions.length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {providerModelOptions.map((model) => {
                        const active = (editingSkill.model || '') === model;
                        return (
                          <button
                            key={model}
                            type="button"
                            className={`rounded-full border px-3 py-1.5 text-xs font-medium transition ${
                              active
                                ? 'border-blue-200 bg-blue-50 text-blue-700'
                                : 'border-white/80 bg-white/70 text-slate-600 hover:border-slate-200 hover:bg-white'
                            }`}
                            onClick={() => {
                              setEditingSkill({ ...editingSkill, model });
                              setModelDirty(true);
                            }}
                          >
                            {model}
                          </button>
                        );
                      })}
                    </div>
                  )}
                </Field>

                <Field label="Temperature">
                  <input
                    type="number"
                    min="0"
                    step="0.1"
                    value={editingSkill.temperature}
                    onChange={(event) => setEditingSkill({ ...editingSkill, temperature: event.target.value })}
                    className="field"
                  />
                </Field>

                <div className="col-span-2 rounded-[24px] border border-white/75 bg-white/58 p-4">
                  <div className="mb-4">
                    <p className="text-sm font-medium text-slate-900">Conversation strategy</p>
                    <p className="mt-1 text-sm text-slate-500">This remains the skill default for session memory. Runtime chat can still override per run.</p>
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <label className="flex items-center gap-2 text-sm text-slate-700">
                      <input
                        type="checkbox"
                        checked={editingSkill.query_rewrite_with_history}
                        onChange={(event) => setEditingSkill({ ...editingSkill, query_rewrite_with_history: event.target.checked })}
                      />
                      <span>Rewrite retrieval query with history</span>
                    </label>
                    <label className="flex items-center gap-2 text-sm text-slate-700">
                      <input
                        type="checkbox"
                        checked={editingSkill.include_history}
                        onChange={(event) => setEditingSkill({ ...editingSkill, include_history: event.target.checked })}
                      />
                      <span>Include history in generation</span>
                    </label>
                    <label className="flex items-center gap-2 text-sm text-slate-700">
                      <input
                        type="checkbox"
                        checked={editingSkill.include_assistant_messages}
                        onChange={(event) => setEditingSkill({ ...editingSkill, include_assistant_messages: event.target.checked })}
                        disabled={!editingSkill.include_history}
                      />
                      <span>Include assistant messages</span>
                    </label>
                    <Field label="History turn limit">
                      <input
                        type="number"
                        min="1"
                        value={editingSkill.history_turn_limit}
                        onChange={(event) => setEditingSkill({ ...editingSkill, history_turn_limit: event.target.value })}
                        className="field"
                      />
                    </Field>
                    <Field label="History token budget">
                      <input
                        type="number"
                        min="1"
                        value={editingSkill.history_token_budget}
                        onChange={(event) => setEditingSkill({ ...editingSkill, history_token_budget: event.target.value })}
                        className="field"
                      />
                    </Field>
                  </div>
                </div>

                <Field label="Top K">
                  <input
                    type="number"
                    min="1"
                    value={editingSkill.top_k}
                    onChange={(event) => setEditingSkill({ ...editingSkill, top_k: event.target.value })}
                    className="field"
                  />
                </Field>

                <Field label="Selection mode">
                  <select
                    value={editingSkill.selection_mode}
                    onChange={(event) => setEditingSkill({ ...editingSkill, selection_mode: event.target.value })}
                    className="field"
                  >
                    <option value="outline_llm">outline_llm</option>
                    <option value="lexical_fallback">lexical_fallback</option>
                  </select>
                </Field>

                <Field label="Max context pages">
                  <input
                    type="number"
                    min="1"
                    value={editingSkill.max_context_pages}
                    onChange={(event) => setEditingSkill({ ...editingSkill, max_context_pages: event.target.value })}
                    className="field"
                    placeholder="Optional"
                  />
                </Field>

                <Field label="Max context tokens">
                  <input
                    type="number"
                    min="1"
                    value={editingSkill.max_context_tokens}
                    onChange={(event) => setEditingSkill({ ...editingSkill, max_context_tokens: event.target.value })}
                    className="field"
                    placeholder="Optional"
                  />
                </Field>
              </div>

              <div className="flex items-center justify-between gap-4 rounded-[24px] border border-white/75 bg-white/58 p-4">
                <div>
                  <p className="font-medium text-slate-900">KB binding and provider-aware model selection are both active</p>
                  <p className="text-sm text-slate-500">
                    {selectedKnowledgeBase
                      ? `This skill binds to ${selectedKnowledgeBase.name}. Enabled KB documents are mirrored into document_ids only as a runtime shim.`
                      : 'Select a knowledge base to complete the skill binding before saving.'}
                  </p>
                </div>
                <button type="submit" className="btn-primary" disabled={saveMutation.isPending || saveBlocked}>
                  <Save size={16} />
                  <span>{saveMutation.isPending ? 'Saving…' : 'Save skill'}</span>
                </button>
              </div>
            </form>
          ) : (
            <div className="empty-state min-h-[580px]">
              <p className="text-base font-medium text-slate-900">Choose or create a skill</p>
              <p className="text-sm text-slate-500">The editor will center knowledge base binding, provider/model resolution, and clear active state.</p>
            </div>
          )}
        </GlassPanel>
      </div>

      <ExpertDrawer
        open={expertOpen}
        onClose={() => setExpertOpen(false)}
        title="Expert configuration"
        description="Advanced JSON remains available, but the product console keeps KB binding and provider/model selection as the main workflow."
      >
        {editingSkill && (
          <div className="space-y-5">
            <Field label="Request config JSON">
              <textarea
                value={editingSkill.request_config_text}
                onChange={(event) => setEditingSkill({ ...editingSkill, request_config_text: event.target.value })}
                className="field min-h-[160px] font-mono text-xs"
              />
            </Field>
            <Field label="Conversation expert JSON">
              <textarea
                value={editingSkill.conversation_expert_text}
                onChange={(event) => setEditingSkill({ ...editingSkill, conversation_expert_text: event.target.value })}
                className="field min-h-[160px] font-mono text-xs"
              />
            </Field>
            <Field label="Retrieval expert JSON">
              <textarea
                value={editingSkill.retrieval_expert_text}
                onChange={(event) => setEditingSkill({ ...editingSkill, retrieval_expert_text: event.target.value })}
                className="field min-h-[180px] font-mono text-xs"
              />
            </Field>
            <Field label="Generation expert JSON">
              <textarea
                value={editingSkill.generation_expert_text}
                onChange={(event) => setEditingSkill({ ...editingSkill, generation_expert_text: event.target.value })}
                className="field min-h-[180px] font-mono text-xs"
              />
            </Field>
          </div>
        )}
      </ExpertDrawer>
    </div>
  );
};
