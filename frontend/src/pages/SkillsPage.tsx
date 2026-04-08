import React, { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Save, Settings2, Trash2, Wand2 } from 'lucide-react';

import { ExpertDrawer, Field, GlassPanel, InlineAlert, SectionToolbar, StatusBadge } from '../components/ui/workbench';
import { documentsApi } from '../features/documents/api';
import { providersApi } from '../features/providers/api';
import { skillsApi } from '../features/skills/api';
import type { ChatSkill } from '../types';
import { getErrorMessage, resolveProviderById } from '../lib/utils';

type EditableSkill = Partial<ChatSkill> & {
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

const normalizeSkill = (skill?: Partial<ChatSkill>, providerDefaultModel?: string): EditableSkill => {
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
    provider_id: skill?.provider_id || null,
    model: skill?.model || providerDefaultModel || '',
    document_ids: skill?.document_ids || [],
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

  const { data: skills = [], isLoading: loadingSkills } = useQuery({ queryKey: ['skills'], queryFn: skillsApi.list });
  const { data: documents = [] } = useQuery({ queryKey: ['documents'], queryFn: documentsApi.list });
  const { data: providers = [] } = useQuery({ queryKey: ['providers'], queryFn: providersApi.list });

  const selectedProvider = useMemo(
    () => resolveProviderById(editingSkill?.provider_id ?? null, providers),
    [editingSkill?.provider_id, providers],
  );
  const providerModelOptions = useMemo(() => {
    if (!selectedProvider) return [];
    return selectedProvider.supported_models?.length ? selectedProvider.supported_models : [selectedProvider.default_model];
  }, [selectedProvider]);

  const saveMutation = useMutation({
    mutationFn: async (skill: EditableSkill) => {
      if (!skill.model?.trim()) {
        throw new Error('Model is required');
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

      const payload = {
        name: skill.name,
        description: skill.description || '',
        system_prompt: skill.system_prompt,
        provider_id: skill.provider_id || null,
        model: skill.model.trim(),
        document_ids: skill.document_ids || [],
        request_config,
        conversation_config,
        retrieval_config,
        generation_config,
      };

      if (skill.id) return skillsApi.update(skill.id, payload);
      return skillsApi.create(payload);
    },
    onSuccess: () => {
      setEditorError('');
      setExpertOpen(false);
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
    },
  });

  const handleSelectSkill = (skill?: ChatSkill) => {
    const providerDefaultModel = skill?.provider_id ? resolveProviderById(skill.provider_id, providers)?.default_model : undefined;
    setEditingSkill(normalizeSkill(skill, providerDefaultModel));
    setModelDirty(Boolean(skill?.model && providerDefaultModel && skill.model !== providerDefaultModel));
    setEditorError('');
  };

  return (
    <div className="space-y-8">
      <SectionToolbar
        title="Skills"
        description="Create provider-aware chat skills without exposing raw JSON to the normal workflow."
        actions={
          <button type="button" className="btn-primary" onClick={() => handleSelectSkill()}>
            <Plus size={16} />
            <span>New skill</span>
          </button>
        }
      />

      <div className="grid grid-cols-[0.86fr_1.14fr] gap-6">
        <GlassPanel title="Skill library" subtitle="Reusable behaviors bound to document sets, prompts, and retrieval policy.">
          <div className="scroll-area max-h-[760px] space-y-3 overflow-auto pr-1">
            {loadingSkills ? (
              <div className="empty-state min-h-[220px]">Loading skills…</div>
            ) : (
              skills.map((skill) => {
                const provider = resolveProviderById(skill.provider_id ?? null, providers);
                return (
                  <button
                    type="button"
                    key={skill.id}
                    onClick={() => handleSelectSkill(skill)}
                    className={`list-row w-full text-left ${editingSkill?.id === skill.id ? 'list-row-active' : ''}`}
                  >
                    <div className="space-y-2">
                      <div className="flex items-center gap-2">
                        <Settings2 size={16} className="text-slate-400" />
                        <p className="font-medium text-slate-900">{skill.name}</p>
                      </div>
                      <p className="line-clamp-2 text-sm text-slate-500">{skill.system_prompt}</p>
                    </div>
                    <div className="text-right">
                      <StatusBadge tone="accent">{provider?.name || 'Tenant default'}</StatusBadge>
                      <p className="mt-2 text-sm text-slate-500">{skill.model}</p>
                    </div>
                  </button>
                );
              })
            )}
            {!loadingSkills && skills.length === 0 && (
              <div className="empty-state min-h-[240px]">
                <p className="text-base font-medium text-slate-900">No skills yet</p>
                <p className="text-sm text-slate-500">Create your first skill to bind prompts, provider choice, and retrieval rules.</p>
              </div>
            )}
          </div>
        </GlassPanel>

        <GlassPanel
          title={editingSkill?.id ? 'Skill editor' : 'New skill'}
          subtitle="Visual configuration first. Expert JSON stays out of the main editing path."
          actions={
            editingSkill ? (
              <div className="flex items-center gap-2">
                <button type="button" className="btn-secondary" onClick={() => setExpertOpen(true)}>
                  <Wand2 size={16} />
                  <span>Expert</span>
                </button>
                {editingSkill.id && (
                  <button type="button" className="btn-ghost text-red-600" onClick={() => deleteMutation.mutate(editingSkill.id!)}>
                    <Trash2 size={16} />
                    <span>Delete</span>
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

                <Field label="Provider">
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

                <Field
                  label="Model"
                  required
                  hint={
                    selectedProvider
                      ? `Defaults to ${selectedProvider.default_model} for ${selectedProvider.name}. ${providerModelOptions.length} provider model candidate${providerModelOptions.length === 1 ? '' : 's'} available, but you can still override manually.`
                      : 'When no provider is selected, this model is used with tenant/system default resolution.'
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
                            className={`rounded-full border px-3 py-1.5 text-xs font-medium transition ${active ? 'border-blue-200 bg-blue-50 text-blue-700' : 'border-white/80 bg-white/70 text-slate-600 hover:border-slate-200 hover:bg-white'}`}
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
                    <p className="mt-1 text-sm text-slate-500">This is the session-memory template for this skill. Chat can override it per run.</p>
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

                <div className="col-span-2">
                  <Field label="Linked documents" hint="Choose the documents this skill should search against.">
                    <div className="grid max-h-[240px] grid-cols-2 gap-3 overflow-auto rounded-[24px] border border-white/80 bg-white/60 p-4">
                      {documents.map((document) => {
                        const checked = editingSkill.document_ids?.includes(document.id) || false;
                        return (
                          <label key={document.id} className="flex items-start gap-3 rounded-2xl border border-white/70 bg-white/70 p-3">
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={(event) => {
                                const currentIds = editingSkill.document_ids || [];
                                const nextIds = event.target.checked
                                  ? [...currentIds, document.id]
                                  : currentIds.filter((id) => id !== document.id);
                                setEditingSkill({ ...editingSkill, document_ids: nextIds });
                              }}
                              className="mt-1"
                            />
                            <div>
                              <p className="text-sm font-medium text-slate-900">{document.display_name}</p>
                              <p className="text-sm text-slate-500">{document.status}</p>
                            </div>
                          </label>
                        );
                      })}
                    </div>
                  </Field>
                </div>
              </div>

              <div className="flex items-center justify-between gap-4 rounded-[24px] border border-white/75 bg-white/58 p-4">
                <div>
                  <p className="font-medium text-slate-900">Provider-aware model selection is active</p>
                  <p className="text-sm text-slate-500">
                    {selectedProvider
                      ? `This skill resolves through ${selectedProvider.name}. The model field is seeded from the provider default but remains overrideable.`
                      : 'No provider binding means the skill will resolve through tenant default, then backend system default.'}
                  </p>
                </div>
                <button type="submit" className="btn-primary" disabled={saveMutation.isPending}>
                  <Save size={16} />
                  <span>{saveMutation.isPending ? 'Saving…' : 'Save skill'}</span>
                </button>
              </div>
            </form>
          ) : (
            <div className="empty-state min-h-[580px]">
              <p className="text-base font-medium text-slate-900">Choose or create a skill</p>
              <p className="text-sm text-slate-500">A skill editor will appear here with provider-aware model defaults and visual retrieval controls.</p>
            </div>
          )}
        </GlassPanel>
      </div>

      <ExpertDrawer
        open={expertOpen}
        onClose={() => setExpertOpen(false)}
        title="Expert configuration"
        description="These fields remain available for advanced adjustments, but they stay out of the main operator workflow."
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
