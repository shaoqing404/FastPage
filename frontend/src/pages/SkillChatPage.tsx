import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Bot, Loader2, Plus, RefreshCcw, Save, Send, Square, TextQuote, Undo, User } from 'lucide-react';
import { Link, useParams, useSearchParams } from 'react-router-dom';

import { AnswerContent } from '../components/ui/AnswerContent';
import { Field, GlassPanel, InlineAlert, KeyMetric, SectionToolbar, StatusBadge } from '../components/ui/workbench';
import { chatApi } from '../features/chat/api';
import { documentsApi } from '../features/documents/api';
import { knowledgeBasesApi } from '../features/knowledge-bases/api';
import { providersApi } from '../features/providers/api';
import { skillsApi } from '../features/skills/api';
import { isApiClientError, resolveStoredWorkspace } from '../lib/api/client';
import {
  describeProviderScope,
  formatDateTime,
  formatPageRange,
  formatRelativeTime,
  getErrorMessage,
  getProviderModelOptions,
  providerSupportsModel,
  resolveProviderById,
  resolveProviderModelOption,
  resolveWorkspaceDefaultProvider,
} from '../lib/utils';
import type { ChatMessage, ChatRun, ChatSession, ChatSkill, Document, KnowledgeBase, ModelProvider, RunStatus } from '../types';

type HistoryItem = {
  role: 'user' | 'assistant';
  content: string;
  run?: ChatRun;
  createdAt?: string | null;
};

type AlertState = {
  title: string;
  message: string;
  code?: string;
  requestId?: string | null;
  allowRetry?: boolean;
};

type SaveFeedback = {
  tone: 'success' | 'danger';
  title: string;
  message: string;
};

type SkillChatConsoleProps = {
  skillId: string;
  skill: ChatSkill;
  documents: Document[];
  knowledgeBases: KnowledgeBase[];
  providers: ModelProvider[];
};

const DEFAULT_CONVERSATION_CONFIG = {
  query_rewrite_with_history: true,
  include_history: true,
  include_assistant_messages: true,
  history_turn_limit: 4,
  history_token_budget: 1800,
};

const SELECTION_MODE_OPTIONS = [
  { value: 'outline_llm', label: 'Model-guided outline selection' },
  { value: 'lexical_fallback', label: 'Keyword fallback only' },
];

const CUSTOM_MODEL_VALUE = '__custom_model__';

const formatResolutionSource = (source: string | null | undefined) => {
  switch (source) {
    case 'runtime_override':
      return 'Runtime draft override';
    case 'skill_saved_provider':
      return 'Saved skill provider';
    case 'workspace_default_provider':
      return 'Workspace default provider';
    case 'tenant_default_provider':
      return 'Tenant default provider';
    case 'system_default_provider':
      return 'Backend system fallback';
    default:
      return 'Not resolved yet';
  }
};

const syncModelForProvider = (currentModel: string, nextProvider: ModelProvider | null) => {
  const nextDefaultModel = nextProvider?.default_model || '';
  if (!currentModel.trim()) return nextDefaultModel;
  if (!providerSupportsModel(nextProvider, currentModel)) return nextDefaultModel || currentModel;
  return currentModel;
};

const updateSkillListCache = (skills: ChatSkill[] | undefined, nextSkill: ChatSkill) => {
  if (!skills) return [nextSkill];
  const index = skills.findIndex((item) => item.id === nextSkill.id);
  if (index === -1) return [nextSkill, ...skills];
  const nextSkills = [...skills];
  nextSkills[index] = nextSkill;
  return nextSkills;
};

const SkillChatConsole: React.FC<SkillChatConsoleProps> = ({ skillId, skill, documents, knowledgeBases, providers }) => {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const scrollRef = useRef<HTMLDivElement>(null);
  const streamAbortRef = useRef<AbortController | null>(null);

  const [question, setQuestion] = useState('');
  const [lastQuestion, setLastQuestion] = useState('');
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingAnswer, setStreamingAnswer] = useState('');
  const [streamingRunCreatedAt, setStreamingRunCreatedAt] = useState<string | null>(null);
  const [streamingStatus, setStreamingStatus] = useState<RunStatus | null>(null);
  const [streamingRunId, setStreamingRunId] = useState<string | null>(null);
  const [streamingExecutionContext, setStreamingExecutionContext] = useState<ChatRun['execution_context'] | null>(null);
  const [completedStreamRun, setCompletedStreamRun] = useState<ChatRun | null>(null);
  const [draftName, setDraftName] = useState(skill.name);
  const [draftModel, setDraftModel] = useState(skill.model || '');
  const [draftSystemPrompt, setDraftSystemPrompt] = useState(skill.system_prompt || '');
  const [draftKnowledgeBaseId, setDraftKnowledgeBaseId] = useState<string | null>(skill.knowledge_base_id || null);
  const [draftProviderId, setDraftProviderId] = useState(skill.provider_id || '');
  const [lastRunWasDraft, setLastRunWasDraft] = useState(false);
  const [newSessionTitle, setNewSessionTitle] = useState('');
  const [queryRewriteWithHistory, setQueryRewriteWithHistory] = useState<boolean | null>(null);
  const [includeHistory, setIncludeHistory] = useState<boolean | null>(null);
  const [includeAssistantMessages, setIncludeAssistantMessages] = useState<boolean | null>(null);
  const [historyTurnLimit, setHistoryTurnLimit] = useState('');
  const [historyTokenBudget, setHistoryTokenBudget] = useState('');
  const [topK, setTopK] = useState('');
  const [selectionMode, setSelectionMode] = useState('');
  const [maxContextPages, setMaxContextPages] = useState('');
  const [maxContextTokens, setMaxContextTokens] = useState('');
  const [temperature, setTemperature] = useState('');
  const [chatAlert, setChatAlert] = useState<AlertState | null>(null);
  const [saveFeedback, setSaveFeedback] = useState<SaveFeedback | null>(null);
  const [lastSavedAt, setLastSavedAt] = useState<string | null>(skill.updated_at);
  const storedWorkspace = resolveStoredWorkspace();

  const workspaceDefaultProvider = useMemo(
    () => resolveWorkspaceDefaultProvider(storedWorkspace?.default_provider_id ?? null, providers),
    [providers, storedWorkspace?.default_provider_id],
  );
  const tenantDefaultProvider = useMemo(
    () => providers.find((provider) => provider.enabled && provider.is_default) || providers.find((provider) => provider.is_default) || null,
    [providers],
  );
  const skillProvider = useMemo(
    () => resolveProviderById(skill.provider_id || null, providers),
    [providers, skill.provider_id],
  );
  const draftBoundProvider = useMemo(
    () => resolveProviderById(draftProviderId || null, providers),
    [draftProviderId, providers],
  );
  const draftResolvedProvider = draftBoundProvider || workspaceDefaultProvider || tenantDefaultProvider || null;
  const savedResolvedProvider = skillProvider || workspaceDefaultProvider || tenantDefaultProvider || null;
  const savedRunProvider = skillProvider || workspaceDefaultProvider || tenantDefaultProvider || null;
  const isLegacyUnboundSkill = !skill.provider_id;

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [pendingQuestion, streamingAnswer, completedStreamRun?.id]);

  useEffect(
    () => () => {
      streamAbortRef.current?.abort();
    },
    [],
  );

  const boundKnowledgeBase = useMemo(
    () => knowledgeBases.find((kb) => kb.id === skill.knowledge_base_id) || null,
    [knowledgeBases, skill.knowledge_base_id],
  );
  const skillDocuments = useMemo(
    () => documents.filter((document) => skill.document_ids.includes(document.id)),
    [documents, skill.document_ids],
  );

  const draftModelOptions = useMemo(
    () => getProviderModelOptions(draftResolvedProvider),
    [draftResolvedProvider],
  );
  const draftSelectedModelOption = useMemo(
    () => resolveProviderModelOption(draftResolvedProvider, draftModel),
    [draftModel, draftResolvedProvider],
  );
  const draftModelSelectValue = draftSelectedModelOption || (draftModel.trim() ? CUSTOM_MODEL_VALUE : '');

  const isConfigDirty = (
    draftName !== skill.name ||
    draftSystemPrompt !== (skill.system_prompt || '') ||
    draftModel !== (skill.model || '') ||
    draftKnowledgeBaseId !== (skill.knowledge_base_id || null) ||
    draftProviderId !== (skill.provider_id || '')
  );

  const savedConfigModel = skill.model || savedResolvedProvider?.default_model || '';
  const savedConfigModelMismatch = Boolean(
    savedResolvedProvider &&
    skill.model?.trim() &&
    !providerSupportsModel(savedResolvedProvider, skill.model),
  );
  const savedRunModelMismatch = Boolean(
    savedRunProvider &&
    skill.model?.trim() &&
    !providerSupportsModel(savedRunProvider, skill.model),
  );
  const draftModelMismatch = Boolean(
    draftResolvedProvider &&
    draftModel.trim() &&
    !providerSupportsModel(draftResolvedProvider, draftModel),
  );

  const skillConversationDefaults = {
    ...DEFAULT_CONVERSATION_CONFIG,
    ...((skill.conversation_config || {}) as Record<string, unknown>),
  };
  const skillRetrievalDefaults = (skill.retrieval_config || {}) as Record<string, unknown>;
  const skillGenerationDefaults = (skill.generation_config || {}) as Record<string, unknown>;
  const effectiveQueryRewriteWithHistory = queryRewriteWithHistory ?? (skillConversationDefaults.query_rewrite_with_history !== false);
  const effectiveIncludeHistory = includeHistory ?? (skillConversationDefaults.include_history !== false);
  const effectiveIncludeAssistantMessages = includeAssistantMessages ?? (skillConversationDefaults.include_assistant_messages !== false);
  const effectiveHistoryTurnLimit = historyTurnLimit || String(skillConversationDefaults.history_turn_limit ?? DEFAULT_CONVERSATION_CONFIG.history_turn_limit);
  const effectiveHistoryTokenBudget = historyTokenBudget || String(skillConversationDefaults.history_token_budget ?? DEFAULT_CONVERSATION_CONFIG.history_token_budget);
  const effectiveTopK = topK || String(skillRetrievalDefaults.top_k ?? 5);
  const effectiveSelectionMode = selectionMode || (typeof skillRetrievalDefaults.selection_mode === 'string' ? skillRetrievalDefaults.selection_mode : 'outline_llm');
  const effectiveMaxContextPages = maxContextPages || (skillRetrievalDefaults.max_context_pages ? String(skillRetrievalDefaults.max_context_pages) : '');
  const effectiveMaxContextTokens = maxContextTokens || (skillRetrievalDefaults.max_context_tokens ? String(skillRetrievalDefaults.max_context_tokens) : '');
  const effectiveTemperature = temperature || (
    skillGenerationDefaults.temperature !== undefined && skillGenerationDefaults.temperature !== null
      ? String(skillGenerationDefaults.temperature)
      : '0'
  );

  const { data: sessions = [] } = useQuery({
    queryKey: ['skill-chat-sessions', skillId],
    queryFn: () => chatApi.listSkillSessions(skillId),
    enabled: Boolean(skillId),
  });
  const { data: allSkillRuns = [] } = useQuery({
    queryKey: ['skill-runs-all-sessions', skillId],
    queryFn: () => chatApi.listRuns({ skill_id: skillId }),
    enabled: Boolean(skillId),
  });

  const sessionSummaries = useMemo(() => {
    const summaryMap = new Map<string, { session: ChatSession; latestRun: ChatRun | null; runCount: number }>();
    for (const session of sessions) {
      summaryMap.set(session.id, { session, latestRun: null, runCount: 0 });
    }
    for (const run of allSkillRuns) {
      if (!run.session_id) continue;
      const existing = summaryMap.get(run.session_id);
      if (!existing) continue;
      existing.runCount += 1;
      if (!existing.latestRun || new Date(run.created_at).getTime() > new Date(existing.latestRun.created_at).getTime()) {
        existing.latestRun = run;
      }
    }
    return Array.from(summaryMap.values());
  }, [allSkillRuns, sessions]);

  const effectiveSessionId = searchParams.get('session') || sessionSummaries[0]?.session.id || '';
  const selectedSession = sessionSummaries.find((entry) => entry.session.id === effectiveSessionId)?.session || null;

  useEffect(() => {
    if (!sessionSummaries.length) return;
    if (effectiveSessionId && sessionSummaries.some((entry) => entry.session.id === effectiveSessionId)) return;
    setSearchParams((params) => {
      const next = new URLSearchParams(params);
      next.set('session', sessionSummaries[0].session.id);
      return next;
    }, { replace: true });
  }, [effectiveSessionId, sessionSummaries, setSearchParams]);

  const { data: sessionMessages = [] } = useQuery({
    queryKey: ['skill-session-messages', skillId, effectiveSessionId],
    queryFn: () => chatApi.getSkillSessionMessages(skillId, effectiveSessionId),
    enabled: Boolean(skillId && effectiveSessionId),
  });
  const { data: filteredRuns = [] } = useQuery({
    queryKey: ['skill-session-runs', skillId, effectiveSessionId],
    queryFn: () => chatApi.listRuns({ skill_id: skillId, session_id: effectiveSessionId }),
    enabled: Boolean(skillId && effectiveSessionId),
  });

  const history = useMemo<HistoryItem[]>(() => {
    const runsById = new Map(filteredRuns.map((run) => [run.id, run]));
    const base = sessionMessages.map((message: ChatMessage) => ({
      role: message.role as 'user' | 'assistant',
      content: message.content,
      run: message.run_id ? runsById.get(message.run_id) : undefined,
      createdAt: message.created_at,
    }));
    const withPendingQuestion = pendingQuestion ? [...base, { role: 'user' as const, content: pendingQuestion }] : base;
    return streamingAnswer || isStreaming
      ? [...withPendingQuestion, { role: 'assistant', content: streamingAnswer, createdAt: streamingRunCreatedAt }]
      : withPendingQuestion;
  }, [filteredRuns, isStreaming, pendingQuestion, sessionMessages, streamingAnswer, streamingRunCreatedAt]);

  const activeRun =
    (completedStreamRun && completedStreamRun.session_id === effectiveSessionId ? completedStreamRun : null) ||
    filteredRuns[0] ||
    null;
  const displayRun = isStreaming ? null : activeRun;
  const activeExecutionContext = streamingExecutionContext || activeRun?.execution_context || {};
  const activeStatus = streamingStatus || activeRun?.status || null;

  const createSessionMutation = useMutation({
    mutationFn: (title: string) => chatApi.createSkillSession(skillId, { title }),
    onSuccess: (session) => {
      setNewSessionTitle('');
      setChatAlert(null);
      setSearchParams((params) => {
        const next = new URLSearchParams(params);
        next.set('session', session.id);
        return next;
      });
      queryClient.invalidateQueries({ queryKey: ['skill-chat-sessions', skillId] });
    },
    onError: (error: unknown) => {
      setChatAlert({
        title: 'Failed to create session',
        message: getErrorMessage(error, 'Failed to create session'),
        allowRetry: false,
      });
    },
  });

  const saveSkillMutation = useMutation({
    mutationFn: async () => {
      if (!draftProviderId) {
        throw new Error('Legacy unbound skills must bind a workspace-available provider before they can be saved again.');
      }
      return skillsApi.update(skill.id, {
        name: draftName,
        system_prompt: draftSystemPrompt,
        model: draftModel,
        knowledge_base_id: draftKnowledgeBaseId,
        description: skill.description ?? null,
        provider_id: draftProviderId,
        document_ids: skill.document_ids,
        request_config: skill.request_config || {},
        conversation_config: skill.conversation_config || {},
        retrieval_config: skill.retrieval_config || {},
        generation_config: skill.generation_config || {},
      });
    },
    onSuccess: (updatedSkill) => {
      queryClient.setQueryData(['skill', skillId], updatedSkill);
      queryClient.setQueryData<ChatSkill[] | undefined>(['skills'], (current) => updateSkillListCache(current, updatedSkill));
      queryClient.invalidateQueries({ queryKey: ['skills'] });
      setDraftName(updatedSkill.name);
      setDraftSystemPrompt(updatedSkill.system_prompt || '');
      setDraftModel(updatedSkill.model || '');
      setDraftKnowledgeBaseId(updatedSkill.knowledge_base_id || null);
      setDraftProviderId(updatedSkill.provider_id || '');
      setLastSavedAt(updatedSkill.updated_at);
      setSaveFeedback({
        tone: 'success',
        title: 'Skill saved',
        message: 'Saved defaults updated. New provider/model settings now apply to future saved runs.',
      });
    },
    onError: (error: unknown) => {
      setSaveFeedback({
        tone: 'danger',
        title: 'Save failed',
        message: getErrorMessage(error, 'Failed to save skill'),
      });
    },
  });

  const runSkillMutation = useMutation({
    mutationFn: async ({ q, isDraft }: { q: string; isDraft: boolean }) => {
      const resolvedModel = isDraft ? (draftModel || draftResolvedProvider?.default_model || '') : savedConfigModel;
      if (!resolvedModel) throw new Error('No model resolved for this skill');
      const retrieval_config = {
        top_k: Number(effectiveTopK || 5),
        selection_mode: effectiveSelectionMode,
        ...(effectiveMaxContextPages.trim() ? { max_context_pages: Number(effectiveMaxContextPages) } : {}),
        ...(effectiveMaxContextTokens.trim() ? { max_context_tokens: Number(effectiveMaxContextTokens) } : {}),
      };
      const conversation_config = {
        query_rewrite_with_history: effectiveQueryRewriteWithHistory,
        include_history: effectiveIncludeHistory,
        include_assistant_messages: effectiveIncludeAssistantMessages,
        history_turn_limit: Number(effectiveHistoryTurnLimit || DEFAULT_CONVERSATION_CONFIG.history_turn_limit),
        history_token_budget: Number(effectiveHistoryTokenBudget || DEFAULT_CONVERSATION_CONFIG.history_token_budget),
      };
      const generation_config = { temperature: Number(effectiveTemperature || 0) };
      const controller = new AbortController();
      streamAbortRef.current = controller;

      return chatApi.streamSkillRun(
        skill.id,
        {
          question: q,
          model: isDraft ? (draftModel || draftResolvedProvider?.default_model || undefined) : undefined,
          system_prompt: isDraft ? draftSystemPrompt : undefined,
          provider_id: isDraft ? (draftProviderId || undefined) : undefined,
          session_id: effectiveSessionId || undefined,
          ...(effectiveSessionId
            ? {}
            : {
                auto_create_session: true,
                session_title: newSessionTitle.trim() || skill.name,
              }),
          conversation_config,
          retrieval_config,
          generation_config,
        },
        {
          signal: controller.signal,
          onRunStarted: ({ run_id, created_at }) => {
            setStreamingRunId(run_id);
            setStreamingRunCreatedAt(created_at);
          },
          onStatus: ({ status }) => {
            setStreamingStatus(status);
          },
          onContext: ({ execution_context }) => {
            setStreamingExecutionContext(execution_context);
          },
          onAnswerDelta: ({ delta }) => {
            setStreamingAnswer((current) => `${current}${delta}`);
          },
        },
      );
    },
    onMutate: ({ q }) => {
      setLastQuestion(q);
      setPendingQuestion(q);
      setIsStreaming(true);
      setChatAlert(null);
      setCompletedStreamRun(null);
      setStreamingAnswer('');
      setStreamingRunId(null);
      setStreamingRunCreatedAt(null);
      setStreamingStatus('accepted');
      setStreamingExecutionContext(null);
    },
    onSuccess: (run) => {
      streamAbortRef.current = null;
      setCompletedStreamRun(run);
      setPendingQuestion(null);
      setIsStreaming(false);
      setQuestion('');
      setChatAlert(null);
      if (run.session_id && run.session_id !== effectiveSessionId) {
        setSearchParams((params) => {
          const next = new URLSearchParams(params);
          next.set('session', run.session_id!);
          return next;
        }, { replace: true });
      }
      setNewSessionTitle('');
      setStreamingAnswer('');
      setStreamingRunId(null);
      setStreamingRunCreatedAt(null);
      setStreamingStatus(null);
      setStreamingExecutionContext(run.execution_context || null);
      queryClient.invalidateQueries({ queryKey: ['skill-runs-all-sessions', skillId] });
      queryClient.invalidateQueries({ queryKey: ['skill-session-runs', skillId, effectiveSessionId] });
      queryClient.invalidateQueries({ queryKey: ['skill-session-messages', skillId, effectiveSessionId] });
      queryClient.invalidateQueries({ queryKey: ['skill-chat-sessions', skillId] });
    },
    onError: (error: unknown, { q }) => {
      streamAbortRef.current = null;
      setPendingQuestion(null);
      setIsStreaming(false);
      setQuestion(q);
      setStreamingAnswer('');
      setStreamingRunId(null);
      setStreamingRunCreatedAt(null);
      setStreamingStatus(null);
      setStreamingExecutionContext(null);
      if (error instanceof DOMException && error.name === 'AbortError') {
        setChatAlert(null);
      } else {
        setChatAlert({
          title: 'Skill run failed',
          message: getErrorMessage(error, 'Skill run failed'),
          ...(isApiClientError(error) ? { code: error.code, requestId: error.requestId } : {}),
          allowRetry: true,
        });
      }
      queryClient.invalidateQueries({ queryKey: ['skill-runs-all-sessions', skillId] });
      queryClient.invalidateQueries({ queryKey: ['skill-session-runs', skillId, effectiveSessionId] });
      queryClient.invalidateQueries({ queryKey: ['skill-session-messages', skillId, effectiveSessionId] });
      queryClient.invalidateQueries({ queryKey: ['skill-chat-sessions', skillId] });
    },
  });

  const handleDraftProviderChange = (nextProviderId: string) => {
    const nextProvider = resolveProviderById(nextProviderId || null, providers);
    setDraftProviderId(nextProviderId);
    setDraftModel((current) => syncModelForProvider(current, nextProvider));
    if (saveFeedback?.tone === 'success') setSaveFeedback(null);
  };

  const handleDraftModelSelectChange = (value: string) => {
    if (value === CUSTOM_MODEL_VALUE) {
      if (!draftModel.trim()) {
        setDraftModel(draftResolvedProvider?.default_model || '');
      }
      return;
    }
    setDraftModel(value);
    if (saveFeedback?.tone === 'success') setSaveFeedback(null);
  };

  const markDraftEdited = <T,>(setter: React.Dispatch<React.SetStateAction<T>>) => (value: React.SetStateAction<T>) => {
    setter(value);
    if (saveFeedback?.tone === 'success') setSaveFeedback(null);
  };

  const handleRun = (isDraft: boolean) => {
    const trimmedQuestion = question.trim();
    if (!trimmedQuestion || isStreaming) return;
    if (isDraft && !draftResolvedProvider) return;
    if (isDraft && draftModelMismatch) return;
    if (!isDraft && savedRunModelMismatch) return;
    setLastRunWasDraft(isDraft);
    runSkillMutation.mutate({ q: trimmedQuestion, isDraft });
  };

  return (
    <div className="space-y-8">
      <SectionToolbar
        title={skill.name}
        description={`Skill configuration and test console${boundKnowledgeBase ? ` · ${boundKnowledgeBase.name}` : ''}. Saved defaults on the right, run history in the center.`}
        actions={
          <Link to="/skills" className="btn-secondary">
            <ArrowLeft size={16} />
            <span>Back to skills</span>
          </Link>
        }
      />

      <div className="grid grid-cols-[300px_1fr_360px] gap-6">
        <GlassPanel title="History" subtitle="Sessions and recent questions for this skill only.">
          <div className="scroll-area max-h-[760px] space-y-4 overflow-auto pr-1">
            <div className="space-y-3 rounded-[24px] border border-white/75 bg-white/58 p-4">
              <div className="flex gap-2">
                <input
                  value={newSessionTitle}
                  onChange={(event) => setNewSessionTitle(event.target.value)}
                  className="field flex-1"
                  placeholder="Create skill session"
                />
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => createSessionMutation.mutate(newSessionTitle.trim())}
                  disabled={createSessionMutation.isPending}
                >
                  <Plus size={16} />
                </button>
              </div>
            </div>

            {sessionSummaries.map(({ session, latestRun, runCount }) => {
              const active = session.id === effectiveSessionId;
              return (
                <button
                  key={session.id}
                  type="button"
                  onClick={() => setSearchParams({ session: session.id })}
                  className={`list-row w-full text-left ${active ? 'list-row-active' : ''}`}
                >
                  <div className="space-y-2">
                    <p className="font-medium text-slate-900">{session.title}</p>
                    <p className="line-clamp-2 text-sm text-slate-500">{latestRun?.question || 'No questions yet'}</p>
                  </div>
                  <div className="text-right text-sm text-slate-500">
                    <p>{runCount} runs</p>
                    <p>{formatDateTime(session.updated_at)}</p>
                  </div>
                </button>
              );
            })}

            {sessionSummaries.length === 0 && (
              <div className="empty-state min-h-[220px]">
                <p className="text-base font-medium text-slate-900">No session history for this skill</p>
                <p className="text-sm text-slate-500">Create a new session to keep future runs grouped in the left panel.</p>
              </div>
            )}
          </div>
        </GlassPanel>

        <GlassPanel title={skill.name} subtitle={selectedSession?.title || 'No session selected'}>
          <div className="space-y-4">
            {chatAlert && (
              <InlineAlert
                tone="danger"
                title={chatAlert.title}
                action={
                  chatAlert.allowRetry ? (
                    <button
                      type="button"
                      className="btn-secondary"
                      disabled={!lastQuestion || isStreaming}
                      onClick={() => lastQuestion && runSkillMutation.mutate({ q: lastQuestion, isDraft: lastRunWasDraft })}
                    >
                      <RefreshCcw size={16} />
                      <span>Retry</span>
                    </button>
                  ) : undefined
                }
              >
                <div className="space-y-1">
                  <p>{chatAlert.message}</p>
                  {(chatAlert.code || chatAlert.requestId) && (
                    <p className="text-xs text-slate-400">
                      {chatAlert.code && <span>Code: {chatAlert.code}</span>}
                      {chatAlert.requestId && <span> · Request ID: {chatAlert.requestId}</span>}
                    </p>
                  )}
                  <p className="text-sm text-slate-500">
                    Provider: {activeExecutionContext.provider?.name || savedRunProvider?.name || 'Backend system default'} ·
                    {' '}Model: {activeExecutionContext.model?.resolved_model || savedConfigModel || 'N/A'}
                  </p>
                  <p className="text-sm text-slate-500">
                    Resolved via: {formatResolutionSource(activeExecutionContext.provider?.resolution_source)}
                  </p>
                </div>
              </InlineAlert>
            )}

            <div ref={scrollRef} className="scroll-area max-h-[620px] space-y-4 overflow-auto pr-1">
              {history.length === 0 ? (
                <div className="empty-state min-h-[420px]">
                  <TextQuote size={22} className="text-blue-600" />
                  <p className="text-base font-medium text-slate-900">Start a conversation</p>
                  <p className="text-sm text-slate-500">Create a session on the left, then ask a question against this skill&apos;s saved knowledge context.</p>
                </div>
              ) : (
                history.map((message, index) => (
                  <div
                    key={`${message.role}-${index}`}
                    className={`rounded-[28px] border px-5 py-4 ${message.role === 'assistant' ? 'border-white/85 bg-white/82' : 'border-white/70 bg-white/56'}`}
                  >
                    <div className="mb-3 flex items-center gap-3">
                      <div className="flex h-10 w-10 items-center justify-center rounded-full bg-white/82 text-blue-600">
                        {message.role === 'assistant' ? <Bot size={18} /> : <User size={18} />}
                      </div>
                      <div>
                        <p className="text-sm font-medium text-slate-900">{message.role === 'assistant' ? 'Assistant' : 'Operator'}</p>
                        {(message.run?.created_at || message.createdAt) && <p className="text-sm text-slate-500">{formatDateTime(message.run?.created_at || message.createdAt)}</p>}
                      </div>
                    </div>
                    {message.role === 'assistant' ? (
                      <AnswerContent content={message.content} />
                    ) : (
                      <div className="whitespace-pre-wrap text-sm leading-7 text-slate-700">{message.content}</div>
                    )}
                    {message.role === 'assistant' && message.run?.answer_with_marker && (
                      <details className="mt-4 rounded-[20px] border border-white/70 bg-white/60 p-4">
                        <summary className="cursor-pointer text-sm font-medium text-slate-700">Raw answer with citation marker payload</summary>
                        <pre className="mt-3 overflow-auto whitespace-pre-wrap text-xs leading-6 text-slate-600">{message.run.answer_with_marker}</pre>
                      </details>
                    )}
                  </div>
                ))
              )}

              {isStreaming && !streamingAnswer && (
                <div className="rounded-[28px] border border-white/80 bg-white/80 px-5 py-4">
                  <div className="mb-3 flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-full bg-white text-blue-600">
                      <Bot size={18} />
                    </div>
                    <div>
                      <p className="text-sm font-medium text-slate-900">Assistant</p>
                      <p className="text-sm text-slate-500">
                        {streamingStatus === 'retrieving'
                          ? 'Retrieving from knowledge base…'
                          : streamingStatus === 'answering'
                            ? 'Generating answer…'
                            : streamingStatus === 'queued'
                              ? 'Queued — waiting for execution slot…'
                              : 'Running…'}
                      </p>
                    </div>
                  </div>
                  <div className="space-y-2">
                    <div className="h-3 w-3/4 rounded-full bg-slate-200" />
                    <div className="h-3 w-2/3 rounded-full bg-slate-200" />
                  </div>
                </div>
              )}
            </div>

            <form
              onSubmit={(event) => {
                event.preventDefault();
                handleRun(false);
              }}
              className="rounded-[28px] border border-white/80 bg-white/72 p-4"
            >
              <div className="flex gap-3">
                <textarea
                  value={question}
                  onChange={(event) => setQuestion(event.target.value)}
                  className="field min-h-[108px] flex-1 resize-none border-0 bg-transparent p-0 shadow-none focus:shadow-none"
                  placeholder="Ask a question through this skill…"
                  disabled={isStreaming}
                />
                {isStreaming ? (
                  <button
                    type="button"
                    className="btn-secondary self-end"
                    onClick={() => {
                      streamAbortRef.current?.abort();
                      if (streamingRunId) {
                        chatApi.cancelRun(streamingRunId).catch(() => {});
                      }
                    }}
                  >
                    <Square size={16} />
                    <span>Cancel</span>
                  </button>
                ) : (
                  <div className="flex flex-col gap-2 self-end">
                    {isConfigDirty && (
                      <button
                        type="button"
                        className="btn-secondary"
                        onClick={() => handleRun(true)}
                        disabled={!question.trim() || isStreaming || draftModelMismatch}
                      >
                        <Bot size={16} />
                        <span>Test with draft</span>
                      </button>
                    )}
                    <button
                      type="submit"
                      className="btn-primary w-full justify-center"
                      disabled={!question.trim() || isStreaming || savedRunModelMismatch}
                    >
                      <Send size={16} />
                      <span>{isConfigDirty ? 'Send (Saved config)' : 'Send'}</span>
                    </button>
                  </div>
                )}
              </div>
            </form>
          </div>
        </GlassPanel>

        <div className="space-y-6">
          <GlassPanel title="Settings" subtitle="Saved skill defaults first. Run-only overrides stay separate below.">
            <div className="space-y-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="text-sm font-semibold text-slate-900">Saved skill defaults</h3>
                  <p className="mt-1 text-sm text-slate-500">
                    Provider, model, knowledge base, and system prompt are persisted on the skill. Draft KB changes still apply only after save.
                  </p>
                  {lastSavedAt && (
                    <p className="mt-2 text-xs uppercase tracking-[0.18em] text-slate-400">
                      Last saved {formatRelativeTime(lastSavedAt)} · {formatDateTime(lastSavedAt)}
                    </p>
                  )}
                </div>
                {isConfigDirty && (
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        setDraftName(skill.name);
                        setDraftSystemPrompt(skill.system_prompt || '');
                        setDraftModel(skill.model || '');
                        setDraftKnowledgeBaseId(skill.knowledge_base_id || null);
                        setDraftProviderId(skill.provider_id || '');
                        setSaveFeedback(null);
                      }}
                      className="btn-secondary text-slate-500"
                    >
                      <Undo size={14} />
                      <span>Revert</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => saveSkillMutation.mutate()}
                      disabled={saveSkillMutation.isPending || draftModelMismatch || !draftModel.trim() || !draftProviderId}
                      className="btn-primary"
                    >
                      {saveSkillMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                      <span>{saveSkillMutation.isPending ? 'Saving…' : 'Save skill'}</span>
                    </button>
                  </div>
                )}
              </div>

              {saveFeedback && (
                <InlineAlert tone={saveFeedback.tone} title={saveFeedback.title}>
                  {saveFeedback.message}
                </InlineAlert>
              )}

              <div className="rounded-[24px] border border-white/75 bg-white/58 p-4">
                <p className="text-sm font-medium text-slate-900">Resolved provider chain</p>
                <div className="mt-3 space-y-2 text-sm text-slate-500">
                  <p>Saved skill provider: {skillProvider ? `${skillProvider.name} (${describeProviderScope(skillProvider)})` : 'Not bound on this skill'}</p>
                  <p>Workspace default provider: {workspaceDefaultProvider ? `${workspaceDefaultProvider.name} (${describeProviderScope(workspaceDefaultProvider)})` : 'Not configured'}</p>
                  <p>Tenant default provider: {tenantDefaultProvider ? `${tenantDefaultProvider.name} (${describeProviderScope(tenantDefaultProvider)})` : 'Not configured or not available here'}</p>
                  <p>System default provider: backend-only hidden fallback</p>
                </div>
              </div>

              {isLegacyUnboundSkill && !draftProviderId && (
                <InlineAlert tone="warning" title="Legacy unbound skill">
                  This skill does not have a saved provider yet. You can still inspect and test it, but saving now requires binding one workspace-available provider explicitly.
                </InlineAlert>
              )}

              <Field label="Skill Name">
                <input
                  value={draftName}
                  onChange={(event) => markDraftEdited(setDraftName)(event.target.value)}
                  className="field"
                />
              </Field>

              <Field label="System prompt" required>
                <textarea
                  value={draftSystemPrompt}
                  onChange={(event) => markDraftEdited(setDraftSystemPrompt)(event.target.value)}
                  className="field min-h-[120px]"
                  required
                />
              </Field>

              <Field label="Knowledge Base" hint="Only one knowledge base can be bound today. Draft KB changes do not affect runs until you save.">
                <select
                  value={draftKnowledgeBaseId || ''}
                  onChange={(event) => markDraftEdited(setDraftKnowledgeBaseId)(event.target.value || null)}
                  className="field"
                >
                  <option value="">No Knowledge Base bound</option>
                  {knowledgeBases.map((kb) => (
                    <option key={kb.id} value={kb.id}>
                      {kb.name}
                    </option>
                  ))}
                </select>
                {skill.knowledge_base_id !== draftKnowledgeBaseId && (
                  <p className="mt-1 text-xs text-amber-600">Knowledge Base changes stay draft-only until you save the skill.</p>
                )}
              </Field>

              <Field label="Provider" hint="This is saved on the skill. Only current-workspace bindable providers appear here. System fallback is not selectable.">
                <select value={draftProviderId} onChange={(event) => handleDraftProviderChange(event.target.value)} className="field">
                  <option value="" disabled>
                    {isLegacyUnboundSkill ? 'Select a provider to bind this skill' : 'Select a provider'}
                  </option>
                  {providers.map((provider) => (
                    <option key={provider.id} value={provider.id}>
                      {provider.name}{provider.scope === 'workspace' ? ' (workspace)' : provider.is_default ? ' (tenant default)' : ''}
                    </option>
                  ))}
                </select>
                <p className="mt-1 text-xs text-slate-500">
                  Saved config resolution if left unbound today: {draftResolvedProvider?.name || 'Backend system default'}
                </p>
              </Field>

              <Field
                label="Model"
                hint={draftResolvedProvider ? `Default model: ${draftResolvedProvider.default_model}` : 'Select a provider first to get provider-aware model suggestions.'}
              >
                <div className="space-y-3">
                  {draftModelOptions.length > 0 ? (
                    <select
                      value={draftModelSelectValue}
                      onChange={(event) => handleDraftModelSelectChange(event.target.value)}
                      className="field"
                    >
                      <option value="" disabled>Select a model</option>
                      {draftModelOptions.map((model) => (
                        <option key={model} value={model}>
                          {model}{model === draftResolvedProvider?.default_model ? ' (default)' : ''}
                        </option>
                      ))}
                      <option value={CUSTOM_MODEL_VALUE}>Custom model…</option>
                    </select>
                  ) : null}
                  {(draftModelOptions.length === 0 || draftModelSelectValue === CUSTOM_MODEL_VALUE) && (
                    <input
                      value={draftModel}
                      onChange={(event) => markDraftEdited(setDraftModel)(event.target.value)}
                      className="field"
                      placeholder={draftResolvedProvider?.default_model || 'Enter model name'}
                    />
                  )}
                </div>
              </Field>

              {draftModelMismatch && draftResolvedProvider && (
                <InlineAlert tone="warning" title="Provider-model mismatch">
                  {`Model "${draftModel}" is not in ${draftResolvedProvider.name}'s supported list.`}
                </InlineAlert>
              )}

              {savedConfigModelMismatch && savedResolvedProvider && !isConfigDirty && (
                <InlineAlert tone="warning" title="Saved config needs attention">
                  {`Saved model "${skill.model}" is no longer in ${savedResolvedProvider.name}'s supported list.`}
                </InlineAlert>
              )}

              <div className="rounded-[24px] border border-white/75 bg-white/58 p-4">
                <div className="mb-4">
                  <p className="text-sm font-medium text-slate-900">Run-time controls</p>
                  <p className="mt-1 text-sm text-slate-500">These do not change the saved skill. Provider changes are tested through the draft provider above, not through Send (Saved config).</p>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <label className="flex items-center gap-2 text-sm text-slate-700">
                    <input type="checkbox" checked={effectiveQueryRewriteWithHistory} onChange={(event) => setQueryRewriteWithHistory(event.target.checked)} />
                    <span>Rewrite the search query using recent chat history</span>
                  </label>
                  <label className="flex items-center gap-2 text-sm text-slate-700">
                    <input type="checkbox" checked={effectiveIncludeHistory} onChange={(event) => setIncludeHistory(event.target.checked)} />
                    <span>Include recent chat history in the answer prompt</span>
                  </label>
                  <label className="flex items-center gap-2 text-sm text-slate-700">
                    <input
                      type="checkbox"
                      checked={effectiveIncludeAssistantMessages}
                      onChange={(event) => setIncludeAssistantMessages(event.target.checked)}
                      disabled={!effectiveIncludeHistory}
                    />
                    <span>Include previous assistant replies in that history</span>
                  </label>
                  <Field label="Max user turns from history" hint="Counts recent user turns. Matching assistant replies are included only when enabled above.">
                    <input type="number" min="1" value={effectiveHistoryTurnLimit} onChange={(event) => setHistoryTurnLimit(event.target.value)} className="field" />
                  </Field>
                  <Field label="History token budget" hint="Approximate cap for chat history included in this run.">
                    <input type="number" min="1" value={effectiveHistoryTokenBudget} onChange={(event) => setHistoryTokenBudget(event.target.value)} className="field" />
                  </Field>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <Field label="Sections to retrieve" hint="Maximum outline sections selected before answer generation starts.">
                  <input type="number" min="1" value={effectiveTopK} onChange={(event) => setTopK(event.target.value)} className="field" />
                </Field>
                <Field
                  label="Section selection method"
                  hint="Model-guided asks the model to choose outline sections first. Keyword fallback skips that step and matches section titles lexically."
                >
                  <select value={effectiveSelectionMode} onChange={(event) => setSelectionMode(event.target.value)} className="field">
                    {SELECTION_MODE_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Max PDF pages in answer context" hint="Optional hard cap on the number of PDF pages pulled into the final answer context.">
                  <input type="number" min="1" value={effectiveMaxContextPages} onChange={(event) => setMaxContextPages(event.target.value)} className="field" placeholder="Optional" />
                </Field>
                <Field label="Max excerpt tokens in answer context" hint="Optional approximate cap on excerpt tokens after section selection.">
                  <input type="number" min="1" value={effectiveMaxContextTokens} onChange={(event) => setMaxContextTokens(event.target.value)} className="field" placeholder="Optional" />
                </Field>
              </div>

              <Field label="Answer temperature" hint="0 is most deterministic. Backend accepts values from 0 to 2.">
                <input type="number" min="0" step="0.1" value={effectiveTemperature} onChange={(event) => setTemperature(event.target.value)} className="field" />
              </Field>
            </div>
          </GlassPanel>

          <GlassPanel title="Runtime data" subtitle="Latest run telemetry, knowledge context, citations, and execution details.">
            <div className="space-y-5">
              <div className="grid grid-cols-2 gap-3">
                <KeyMetric label="Session" value={selectedSession?.title || 'No session'} />
                <KeyMetric label="Model" value={activeExecutionContext.model?.resolved_model || savedConfigModel || 'N/A'} />
                <KeyMetric label="Provider" value={activeExecutionContext.provider?.name || savedRunProvider?.name || 'Backend system default'} />
                <KeyMetric label="Provider source" value={formatResolutionSource(activeExecutionContext.provider?.resolution_source)} />
                <KeyMetric label="Citations" value={displayRun?.citations.length ?? 0} />
              </div>

              {boundKnowledgeBase ? (
                <div className="surface-soft p-4">
                  <p className="metric-label">Knowledge Base</p>
                  <p className="mt-2 font-medium text-slate-900">{boundKnowledgeBase.name}</p>
                </div>
              ) : skillDocuments.length > 0 ? (
                <div className="surface-soft p-4">
                  <p className="metric-label">Legacy Target Document</p>
                  <p className="mt-2 font-medium text-slate-900">{skillDocuments.length} document(s) bound</p>
                </div>
              ) : null}

              {(displayRun || activeStatus || activeExecutionContext.retrieval?.query || activeExecutionContext.model?.resolved_model) ? (
                <>
                  <div className="grid grid-cols-2 gap-3">
                    <KeyMetric label="Latency" value={displayRun?.metrics.total_ms ? `${displayRun.metrics.total_ms} ms` : 'N/A'} />
                    <KeyMetric label="Tokens" value={displayRun?.metrics.total_tokens ?? 'N/A'} />
                    <KeyMetric label="Retrieved sections" value={displayRun ? (displayRun.metrics.selected_section_count ?? displayRun.selected_sections.length) : 'Pending'} />
                    <KeyMetric label="History used" value={activeExecutionContext.conversation?.history_used ? 'Yes' : 'No'} />
                  </div>

                  {activeStatus && (
                    <div className="surface-soft p-4">
                      <p className="metric-label">Run status</p>
                      <div className="mt-2 flex items-center gap-2">
                        <StatusBadge tone={activeStatus === 'completed' ? 'success' : activeStatus === 'failed' ? 'danger' : activeStatus === 'cancelled' ? 'warning' : 'accent'}>
                          {activeStatus}
                        </StatusBadge>
                        {displayRun?.raw_status && displayRun.raw_status !== activeStatus && (
                          <span className="text-xs text-slate-400">({displayRun.raw_status})</span>
                        )}
                      </div>
                      {displayRun?.cancel_requested && (
                        <p className="mt-2 text-xs text-amber-600">
                          Cancel requested{displayRun.cancel_reason ? `: ${displayRun.cancel_reason}` : ''}
                        </p>
                      )}
                      {displayRun?.last_error && activeStatus === 'failed' && (
                        <p className="mt-2 text-xs text-red-500">{displayRun.last_error}</p>
                      )}
                    </div>
                  )}

                  {(activeExecutionContext.retrieval?.query || activeExecutionContext.retrieval?.rewritten_query) && (
                    <div className="surface-soft p-4">
                      <p className="metric-label">Retrieval query</p>
                      <p className="mt-2 text-sm text-slate-700">{activeExecutionContext.retrieval?.query || 'N/A'}</p>
                      {activeExecutionContext.retrieval?.rewrite_applied && activeExecutionContext.retrieval?.rewritten_query && (
                        <p className="mt-2 text-xs text-slate-500">Rewritten query: {activeExecutionContext.retrieval.rewritten_query}</p>
                      )}
                    </div>
                  )}

                  {displayRun?.citations.length ? (
                    <div className="space-y-3">
                      <p className="text-sm font-semibold text-slate-900">Citations</p>
                      {displayRun.citations.map((citation, index) => (
                        <div key={`${citation.document_id || 'citation'}-${index}`} className="surface-soft p-4">
                          <p className="font-medium text-slate-900">{citation.title || citation.document_id || 'Untitled citation'}</p>
                          <p className="mt-2 text-sm text-slate-500">
                            {citation.page_start || citation.page_end ? formatPageRange(citation.page_start, citation.page_end) : 'Page range unavailable'}
                          </p>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </>
              ) : (
                <div className="empty-state min-h-[220px]">
                  <p className="text-base font-medium text-slate-900">No runtime telemetry yet</p>
                  <p className="text-sm text-slate-500">Run the skill to see resolved provider/model details and citations here.</p>
                </div>
              )}
            </div>
          </GlassPanel>
        </div>
      </div>
    </div>
  );
};

export const SkillChatPage: React.FC = () => {
  const { skillId = '' } = useParams();
  const skillQuery = useQuery({
    queryKey: ['skill', skillId],
    queryFn: () => skillsApi.get(skillId),
    enabled: Boolean(skillId),
    retry: false,
  });
  const { data: documents = [] } = useQuery({ queryKey: ['documents'], queryFn: () => documentsApi.list() });
  const { data: knowledgeBases = [] } = useQuery({ queryKey: ['knowledge-bases'], queryFn: knowledgeBasesApi.list });
  const { data: providers = [] } = useQuery({ queryKey: ['provider-catalog'], queryFn: providersApi.listCatalog });

  if (skillQuery.isLoading) {
    return (
      <div className="space-y-8">
        <SectionToolbar title="Skill console" description="Loading saved configuration and session history." />
        <GlassPanel title="Loading skill" subtitle="Fetching the current skill configuration.">
          <div className="empty-state min-h-[320px]">
            <Loader2 size={28} className="animate-spin text-blue-600" />
            <p className="text-base font-medium text-slate-900">Loading skill…</p>
          </div>
        </GlassPanel>
      </div>
    );
  }

  if (skillQuery.error || !skillQuery.data) {
    return (
      <div className="space-y-8">
        <SectionToolbar title="Skill console" description="This skill route could not be resolved." />
        <GlassPanel title="Missing skill" subtitle="The requested skill was not found or could not be loaded.">
          <div className="empty-state min-h-[320px]">
            <p className="text-base font-medium text-slate-900">Skill not found</p>
            {skillQuery.error && <p className="text-sm text-slate-500">{getErrorMessage(skillQuery.error, 'Failed to load skill')}</p>}
            <Link to="/skills" className="btn-primary">
              <ArrowLeft size={16} />
              <span>Back to skills</span>
            </Link>
          </div>
        </GlassPanel>
      </div>
    );
  }

  return (
    <SkillChatConsole
      key={skillQuery.data.id}
      skillId={skillId}
      skill={skillQuery.data}
      documents={documents}
      knowledgeBases={knowledgeBases}
      providers={providers}
    />
  );
};
