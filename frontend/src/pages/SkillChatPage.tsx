import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft,
  Bot,
  History,
  Loader2,
  MoreHorizontal,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  Plus,
  RefreshCcw,
  Save,
  Send,
  SlidersHorizontal,
  Square,
  TextQuote,
  Undo,
  User,
} from 'lucide-react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { RunObservationTimeline } from '../components/runtime/RunObservationTimeline';
import { SkillActionsModal } from '../components/skills/SkillActionsModal';
import { AnswerContent } from '../components/ui/AnswerContent';
import { ExpertDrawer, Field, GlassPanel, InlineAlert, KeyMetric, SectionToolbar, SegmentedControl, StatusBadge } from '../components/ui/workbench';
import { chatApi } from '../features/chat/api';
import { documentsApi } from '../features/documents/api';
import { knowledgeBasesApi } from '../features/knowledge-bases/api';
import { providersApi } from '../features/providers/api';
import { runtimeObservationsApi } from '../features/runtime-observations/api';
import { skillsApi } from '../features/skills/api';
import { isApiClientError, resolveStoredWorkspace } from '../lib/api/client';
import {
  describeProviderAvailability,
  describeProviderOwnership,
  formatDateTime,
  formatPageRange,
  formatRelativeTime,
  getErrorMessage,
  getProviderModelOptions,
  humanizeSkillRunError,
  providerSupportsModel,
  resolveProviderById,
  resolveProviderModelOption,
  resolveWorkspaceDefaultProvider,
} from '../lib/utils';
import type { ChatMessage, ChatRun, ChatSession, ChatSkill, Document, KnowledgeBase, ModelProvider, RunObservationEvent, RunObservationSnapshot, RunStatus } from '../types';

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

type SkillConsoleLayoutState = {
  historyOpen: boolean;
  inspectorOpen: boolean;
  inspectorTab: 'settings' | 'runtime';
};

const DEFAULT_CONVERSATION_CONFIG = {
  query_rewrite_with_history: true,
  include_history: true,
  include_assistant_messages: true,
  history_turn_limit: 4,
  history_token_budget: 1800,
};
const FAST_SEARCH_TOP_K_RECOMMENDED = 3;
const FAST_SEARCH_TOP_K_MAX = 10;
const RECOMMENDED_CONTEXT_TOKEN_BUDGET = 131072;
const STREAMING_ANSWER_FLUSH_INTERVAL_MS = 75;

const SELECTION_MODE_OPTIONS = [
  { value: 'outline_llm', label: '模型引导大纲选择' },
  { value: 'lexical_fallback', label: '仅关键词回退' },
];

const CUSTOM_MODEL_VALUE = '__custom_model__';

const formatResolutionSource = (source: string | null | undefined) => {
  switch (source) {
    case 'runtime_override':
      return '运行时草稿覆盖';
    case 'skill_saved_provider':
      return 'Skill 已保存 Provider';
    case 'workspace_default_provider':
      return '工作区默认 Provider';
    case 'tenant_default_provider':
      return '租户默认 Provider';
    case 'system_default_provider':
      return '后端系统回退';
    default:
      return '尚未解析';
  }
};

const formatMillisecondsAsSeconds = (value: unknown) => {
  const milliseconds = Number(value);
  if (!Number.isFinite(milliseconds)) return 'N/A';
  return `${(milliseconds / 1000).toFixed(2)} s`;
};

const formatTokenBreakdown = (metrics: ChatRun['metrics'] | undefined) => {
  if (!metrics) return undefined;
  const input = metrics.input_tokens ?? 'N/A';
  const output = metrics.output_tokens ?? 'N/A';
  return `输入 ${input} · 输出 ${output}；输出可能包含 Provider 统计的隐藏推理/内部 token。`;
};

const normalizeFastSearchTopK = (value: unknown) => {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) return String(FAST_SEARCH_TOP_K_RECOMMENDED);
  return String(Math.min(FAST_SEARCH_TOP_K_MAX, Math.max(1, Math.trunc(parsed))));
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

const SKILL_CONSOLE_LAYOUT_PREFIX = 'pageindex.skillConsole.layout.';

const readSkillConsoleLayoutState = (skillId: string): SkillConsoleLayoutState => {
  if (typeof window === 'undefined') {
    return { historyOpen: true, inspectorOpen: true, inspectorTab: 'settings' };
  }
  try {
    const raw = localStorage.getItem(`${SKILL_CONSOLE_LAYOUT_PREFIX}${skillId}`);
    if (!raw) return { historyOpen: true, inspectorOpen: true, inspectorTab: 'settings' };
    const parsed = JSON.parse(raw) as Partial<SkillConsoleLayoutState>;
    return {
      historyOpen: parsed.historyOpen !== false,
      inspectorOpen: parsed.inspectorOpen !== false,
      inspectorTab: parsed.inspectorTab === 'runtime' ? 'runtime' : 'settings',
    };
  } catch {
    return { historyOpen: true, inspectorOpen: true, inspectorTab: 'settings' };
  }
};

const writeSkillConsoleLayoutState = (skillId: string, value: SkillConsoleLayoutState) => {
  if (typeof window === 'undefined') return;
  localStorage.setItem(`${SKILL_CONSOLE_LAYOUT_PREFIX}${skillId}`, JSON.stringify(value));
};

const resolveHistoryItemTimestamp = (message: HistoryItem) => {
  if (message.createdAt) return message.createdAt;
  if (message.role === 'assistant') return message.run?.finished_at || null;
  return null;
};

const SkillChatConsole: React.FC<SkillChatConsoleProps> = ({ skillId, skill, documents, knowledgeBases, providers }) => {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const scrollRef = useRef<HTMLDivElement>(null);
  const streamAbortRef = useRef<AbortController | null>(null);
  const streamingAnswerBufferRef = useRef('');
  const streamingAnswerFlushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [layoutState, setLayoutState] = useState<SkillConsoleLayoutState>(() => readSkillConsoleLayoutState(skillId));
  const [isCompactLayout, setIsCompactLayout] = useState(() => (
    typeof window !== 'undefined' ? window.matchMedia('(max-width: 900px)').matches : false
  ));
  const [actionsOpen, setActionsOpen] = useState(false);
  const [historyDrawerOpen, setHistoryDrawerOpen] = useState(false);
  const [inspectorDrawerOpen, setInspectorDrawerOpen] = useState(false);
  const [question, setQuestion] = useState('');
  const [lastQuestion, setLastQuestion] = useState('');
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingAnswer, setStreamingAnswer] = useState('');
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
  const [rerankMode, setRerankMode] = useState('');
  const [temperature, setTemperature] = useState('');
  const [streamingObservations, setStreamingObservations] = useState<RunObservationEvent[]>([]);
  const [chatAlert, setChatAlert] = useState<AlertState | null>(null);
  const [saveFeedback, setSaveFeedback] = useState<SaveFeedback | null>(null);
  const [lastSavedAt, setLastSavedAt] = useState<string | null>(skill.updated_at);

  const [searchMode, setSearchMode] = useState<'deep_research' | 'fast_search'>('deep_research');
  const [fastSearchTopK, setFastSearchTopK] = useState('');

  const storedWorkspace = resolveStoredWorkspace();

  const clearStreamingAnswerFlushTimer = useCallback(() => {
    if (streamingAnswerFlushTimerRef.current === null) return;
    clearTimeout(streamingAnswerFlushTimerRef.current);
    streamingAnswerFlushTimerRef.current = null;
  }, []);

  const flushStreamingAnswerBuffer = useCallback(() => {
    clearStreamingAnswerFlushTimer();
    const bufferedDelta = streamingAnswerBufferRef.current;
    if (!bufferedDelta) return;
    streamingAnswerBufferRef.current = '';
    setStreamingAnswer((current) => `${current}${bufferedDelta}`);
  }, [clearStreamingAnswerFlushTimer]);

  const scheduleStreamingAnswerFlush = useCallback(() => {
    if (streamingAnswerFlushTimerRef.current !== null) return;
    streamingAnswerFlushTimerRef.current = setTimeout(() => {
      streamingAnswerFlushTimerRef.current = null;
      flushStreamingAnswerBuffer();
    }, STREAMING_ANSWER_FLUSH_INTERVAL_MS);
  }, [flushStreamingAnswerBuffer]);

  const enqueueStreamingAnswerDelta = useCallback((delta: string) => {
    if (!delta) return;
    streamingAnswerBufferRef.current += delta;
    scheduleStreamingAnswerFlush();
  }, [scheduleStreamingAnswerFlush]);

  const resetStreamingAnswerBuffer = useCallback(() => {
    clearStreamingAnswerFlushTimer();
    streamingAnswerBufferRef.current = '';
  }, [clearStreamingAnswerFlushTimer]);

  const updateLayoutState = (nextValue: Partial<SkillConsoleLayoutState>) => {
    setLayoutState((current) => ({ ...current, ...nextValue }));
  };

  const resetSavedConfigOverrides = () => {
    setQueryRewriteWithHistory(null);
    setIncludeHistory(null);
    setIncludeAssistantMessages(null);
    setHistoryTurnLimit('');
    setHistoryTokenBudget('');
    setTopK('');
    setSelectionMode('');
    setMaxContextPages('');
    setMaxContextTokens('');
    setRerankMode('');
    setFastSearchTopK('');
    setTemperature('');
  };

  const applySavedSkillState = (nextSkill: ChatSkill) => {
    setDraftName(nextSkill.name);
    setDraftSystemPrompt(nextSkill.system_prompt || '');
    setDraftModel(nextSkill.model || '');
    setDraftKnowledgeBaseId(nextSkill.knowledge_base_id || null);
    setDraftProviderId(nextSkill.provider_id || '');
    setLastSavedAt(nextSkill.updated_at);
    resetSavedConfigOverrides();
  };

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
  const selectableProviders = useMemo(
    () => [...providers].sort((left, right) => {
      if (left.scope !== right.scope) {
        if (left.scope === 'workspace') return -1;
        if (right.scope === 'workspace') return 1;
      }
      return left.name.localeCompare(right.name);
    }),
    [providers],
  );

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [pendingQuestion, streamingAnswer, completedStreamRun?.id]);

  useEffect(
    () => () => {
      flushStreamingAnswerBuffer();
      streamAbortRef.current?.abort();
    },
    [flushStreamingAnswerBuffer],
  );

  useEffect(() => {
    setLayoutState(readSkillConsoleLayoutState(skillId));
  }, [skillId]);

  useEffect(() => {
    writeSkillConsoleLayoutState(skillId, layoutState);
  }, [layoutState, skillId]);

  useEffect(() => {
    if (typeof window === 'undefined') return undefined;
    const media = window.matchMedia('(max-width: 900px)');
    const handleChange = (event: MediaQueryListEvent) => {
      setIsCompactLayout(event.matches);
    };
    setIsCompactLayout(media.matches);
    media.addEventListener('change', handleChange);
    return () => media.removeEventListener('change', handleChange);
  }, []);

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
  const effectiveRerankMode = rerankMode || (typeof skillRetrievalDefaults.rerank_mode === 'string' ? skillRetrievalDefaults.rerank_mode : 'auto');
  const effectiveFastSearchTopK = fastSearchTopK || normalizeFastSearchTopK(skillRetrievalDefaults.node_top_k);
  const effectiveTemperature = temperature || (
    skillGenerationDefaults.temperature !== undefined && skillGenerationDefaults.temperature !== null
      ? String(skillGenerationDefaults.temperature)
      : '0'
  );
  const savedQueryRewriteWithHistory = skillConversationDefaults.query_rewrite_with_history !== false;
  const savedIncludeHistory = skillConversationDefaults.include_history !== false;
  const savedIncludeAssistantMessages = skillConversationDefaults.include_assistant_messages !== false;
  const savedHistoryTurnLimit = String(skillConversationDefaults.history_turn_limit ?? DEFAULT_CONVERSATION_CONFIG.history_turn_limit);
  const savedHistoryTokenBudget = String(skillConversationDefaults.history_token_budget ?? DEFAULT_CONVERSATION_CONFIG.history_token_budget);
  const savedTopK = String(skillRetrievalDefaults.top_k ?? 5);
  const savedSelectionMode = typeof skillRetrievalDefaults.selection_mode === 'string' ? skillRetrievalDefaults.selection_mode : 'outline_llm';
  const savedMaxContextPages = skillRetrievalDefaults.max_context_pages ? String(skillRetrievalDefaults.max_context_pages) : '';
  const savedMaxContextTokens = skillRetrievalDefaults.max_context_tokens ? String(skillRetrievalDefaults.max_context_tokens) : '';
  const savedRerankMode = typeof skillRetrievalDefaults.rerank_mode === 'string' ? skillRetrievalDefaults.rerank_mode : 'auto';
  const savedFastSearchTopK = normalizeFastSearchTopK(skillRetrievalDefaults.node_top_k);
  const savedTemperature = (
    skillGenerationDefaults.temperature !== undefined && skillGenerationDefaults.temperature !== null
      ? String(skillGenerationDefaults.temperature)
      : '0'
  );

  const isConfigDirty = (
    draftName !== skill.name ||
    draftSystemPrompt !== (skill.system_prompt || '') ||
    draftModel !== (skill.model || '') ||
    draftKnowledgeBaseId !== (skill.knowledge_base_id || null) ||
    draftProviderId !== (skill.provider_id || '') ||
    effectiveQueryRewriteWithHistory !== savedQueryRewriteWithHistory ||
    effectiveIncludeHistory !== savedIncludeHistory ||
    effectiveIncludeAssistantMessages !== savedIncludeAssistantMessages ||
    effectiveHistoryTurnLimit !== savedHistoryTurnLimit ||
    effectiveHistoryTokenBudget !== savedHistoryTokenBudget ||
    effectiveTopK !== savedTopK ||
    effectiveSelectionMode !== savedSelectionMode ||
    effectiveMaxContextPages !== savedMaxContextPages ||
    effectiveMaxContextTokens !== savedMaxContextTokens ||
    effectiveRerankMode !== savedRerankMode ||
    effectiveFastSearchTopK !== savedFastSearchTopK ||
    effectiveTemperature !== savedTemperature
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

  useEffect(() => {
    if (!completedStreamRun || isStreaming) return;
    const hasPersistedAssistantMessage = sessionMessages.some((message) => (
      message.role === 'assistant' &&
      (message.run_id === completedStreamRun.id || message.content === completedStreamRun.answer)
    ));
    if (!hasPersistedAssistantMessage) return;
    setPendingQuestion(null);
    if (streamingAnswer) setStreamingAnswer('');
  }, [completedStreamRun, isStreaming, sessionMessages, streamingAnswer]);

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
      ? [...withPendingQuestion, { role: 'assistant', content: streamingAnswer }]
      : withPendingQuestion;
  }, [filteredRuns, isStreaming, pendingQuestion, sessionMessages, streamingAnswer]);

  const activeRun =
    (completedStreamRun && completedStreamRun.session_id === effectiveSessionId ? completedStreamRun : null) ||
    filteredRuns[0] ||
    null;
  const displayRun = isStreaming ? null : activeRun;
  const activeExecutionContext = streamingExecutionContext || activeRun?.execution_context || {};
  const activeStatus = streamingStatus || activeRun?.status || null;
  const activeObservationRunId = streamingRunId || displayRun?.id || activeRun?.id || null;
  const { data: observationSnapshotData } = useQuery({
    queryKey: ['runtime-observation', 'chat', activeObservationRunId],
    queryFn: () => runtimeObservationsApi.getSnapshot('chat', activeObservationRunId!),
    enabled: Boolean(activeObservationRunId),
    refetchInterval: activeStatus === 'running' || activeStatus === 'queued' ? 3000 : false,
  });
  const activeObservationSnapshot = useMemo<RunObservationSnapshot | null>(() => {
    if (!observationSnapshotData && streamingObservations.length === 0) return null;
    if (streamingObservations.length === 0) return observationSnapshotData || null;
    const lastEvent = streamingObservations[streamingObservations.length - 1] || null;
    return {
      run_kind: 'chat',
      run_id: activeObservationRunId || observationSnapshotData?.run_id || '',
      status: activeStatus || observationSnapshotData?.status || 'queued',
      current_step: lastEvent?.step || observationSnapshotData?.current_step || null,
      worker_node_code: observationSnapshotData?.worker_node_code || null,
      queue: observationSnapshotData?.queue || {},
      timings: observationSnapshotData?.timings || {},
      execution_context: (activeExecutionContext || observationSnapshotData?.execution_context || {}) as Record<string, unknown>,
      partial_answer: streamingAnswer || observationSnapshotData?.partial_answer || null,
      events: streamingObservations,
    };
  }, [activeExecutionContext, activeObservationRunId, activeStatus, observationSnapshotData, streamingAnswer, streamingObservations]);

  const conversationHistoryContent = useMemo(() => (
    <>
      {history.length === 0 ? (
        <div className="empty-state min-h-[420px]">
          <TextQuote size={22} className="text-blue-600" />
          <p className="text-base font-medium text-slate-900">开始对话</p>
          <p className="text-sm text-slate-500">先从历史栏创建会话，再基于此 Skill 保存的知识上下文提问。</p>
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
                <p className="text-sm font-medium text-slate-900">{message.role === 'assistant' ? '助手' : '用户'}</p>
                {resolveHistoryItemTimestamp(message) && <p className="text-sm text-slate-500">{formatDateTime(resolveHistoryItemTimestamp(message))}</p>}
              </div>
            </div>
            {message.role === 'assistant' ? (
              <AnswerContent content={message.content} />
            ) : (
              <div className="whitespace-pre-wrap text-sm leading-7 text-slate-700">{message.content}</div>
            )}
            {message.role === 'assistant' && message.run?.answer_with_marker && (
              <details className="mt-4 rounded-[20px] border border-white/70 bg-white/60 p-4">
                <summary className="cursor-pointer text-sm font-medium text-slate-700">带引用标记的原始回答</summary>
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
              <p className="text-sm font-medium text-slate-900">助手</p>
              <p className="text-sm text-slate-500">
                {streamingStatus === 'retrieving'
                  ? '正在从知识库检索…'
                  : streamingStatus === 'answering'
                    ? '正在生成回答…'
                    : streamingStatus === 'queued'
                      ? '已排队，等待执行资源…'
                      : '运行中…'}
              </p>
            </div>
          </div>
          <div className="space-y-2">
            <div className="h-3 w-3/4 rounded-full bg-slate-200" />
            <div className="h-3 w-2/3 rounded-full bg-slate-200" />
          </div>
        </div>
      )}
    </>
  ), [history, isStreaming, streamingAnswer, streamingStatus]);

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
        title: '创建会话失败',
        message: getErrorMessage(error, '创建会话失败'),
        allowRetry: false,
      });
    },
  });

  const saveSkillMutation = useMutation({
    mutationFn: async () => {
      if (!draftProviderId) {
        throw new Error('旧版未绑定 Skill 必须先绑定一个当前工作区可用的 Provider，才能再次保存。');
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
        conversation_config: {
          query_rewrite_with_history: effectiveQueryRewriteWithHistory,
          include_history: effectiveIncludeHistory,
          include_assistant_messages: effectiveIncludeAssistantMessages,
          history_turn_limit: Number(effectiveHistoryTurnLimit || DEFAULT_CONVERSATION_CONFIG.history_turn_limit),
          history_token_budget: Number(effectiveHistoryTokenBudget || DEFAULT_CONVERSATION_CONFIG.history_token_budget),
        },
        retrieval_config: {
          top_k: Number(effectiveTopK || 5),
          selection_mode: effectiveSelectionMode,
          rerank_mode: effectiveRerankMode,
          node_top_k: Number(effectiveFastSearchTopK || FAST_SEARCH_TOP_K_RECOMMENDED),
          ...(effectiveMaxContextPages.trim() ? { max_context_pages: Number(effectiveMaxContextPages) } : {}),
          ...(effectiveMaxContextTokens.trim() ? { max_context_tokens: Number(effectiveMaxContextTokens) } : {}),
        },
        generation_config: { temperature: Number(effectiveTemperature || 0) },
      });
    },
    onSuccess: (updatedSkill) => {
      queryClient.setQueryData(['skill', skillId], updatedSkill);
      queryClient.setQueryData<ChatSkill[] | undefined>(['skills'], (current) => updateSkillListCache(current, updatedSkill));
      queryClient.invalidateQueries({ queryKey: ['skills'] });
      applySavedSkillState(updatedSkill);
      setSaveFeedback({
        tone: 'success',
        title: 'Skill 已保存',
        message: '默认配置已更新。新的 Provider、模型和检索设置会用于后续已保存配置运行。',
      });
    },
    onError: (error: unknown) => {
      setSaveFeedback({
        tone: 'danger',
        title: '保存失败',
        message: getErrorMessage(error, '保存 Skill 失败'),
      });
    },
  });

  const runSkillMutation = useMutation({
    mutationFn: async ({ q, isDraft }: { q: string; isDraft: boolean }) => {
      const resolvedModel = isDraft ? (draftModel || draftResolvedProvider?.default_model || '') : savedConfigModel;
      if (!resolvedModel) throw new Error('该 Skill 未解析到可用模型');
      const retrieval_config = {
        top_k: Number(effectiveTopK || 5),
        selection_mode: effectiveSelectionMode,
        rerank_mode: effectiveRerankMode,
        retrieval_mode: searchMode === 'fast_search' ? 'fast' : 'deep_research',
        ...(searchMode === 'fast_search' ? { node_top_k: Number(effectiveFastSearchTopK || FAST_SEARCH_TOP_K_RECOMMENDED) } : {}),
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
          onRunStarted: ({ run_id }) => {
            setStreamingRunId(run_id);
          },
          onStatus: ({ status }) => {
            setStreamingStatus(status);
          },
          onContext: ({ execution_context }) => {
            setStreamingExecutionContext(execution_context);
          },
          onObservation: (event) => {
            setStreamingObservations((current) => (
              current.some((item) => item.id === event.id) ? current : [...current, event]
            ));
          },
          onAnswerDelta: ({ delta }) => {
            enqueueStreamingAnswerDelta(delta);
          },
        },
      );
    },
    onMutate: ({ q }) => {
      resetStreamingAnswerBuffer();
      setLastQuestion(q);
      setPendingQuestion(q);
      setIsStreaming(true);
      setChatAlert(null);
      setCompletedStreamRun(null);
      setStreamingAnswer('');
      setStreamingRunId(null);
      setStreamingStatus('accepted');
      setStreamingExecutionContext(null);
      setStreamingObservations([]);
    },
    onSuccess: (run) => {
      flushStreamingAnswerBuffer();
      streamAbortRef.current = null;
      setCompletedStreamRun(run);
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
      setStreamingRunId(null);
      setStreamingStatus(null);
      setStreamingExecutionContext(run.execution_context || null);
      setStreamingObservations([]);
      queryClient.invalidateQueries({ queryKey: ['skill-runs-all-sessions', skillId] });
      queryClient.invalidateQueries({ queryKey: ['skill-session-runs', skillId, effectiveSessionId] });
      queryClient.invalidateQueries({ queryKey: ['skill-session-messages', skillId, effectiveSessionId] });
      queryClient.invalidateQueries({ queryKey: ['skill-chat-sessions', skillId] });
    },
    onError: (error: unknown, { q }) => {
      flushStreamingAnswerBuffer();
      const isAbortError = error instanceof DOMException && error.name === 'AbortError';
      streamAbortRef.current = null;
      setPendingQuestion(null);
      setIsStreaming(false);
      setQuestion(q);
      if (isAbortError) setStreamingAnswer('');
      setStreamingRunId(null);
      setStreamingStatus(null);
      setStreamingExecutionContext(null);
      setStreamingObservations([]);
      if (isAbortError) {
        setChatAlert(null);
      } else {
        setChatAlert({
          title: 'Skill 运行失败',
          message: humanizeSkillRunError(getErrorMessage(error, 'Skill 运行失败')),
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

  const historyPanelContent = (
    <div className="scroll-area max-h-[760px] space-y-4 overflow-auto pr-1">
      <div className="space-y-3 rounded-[24px] border border-white/75 bg-white/58 p-4">
        <div className="flex gap-2">
          <input
            value={newSessionTitle}
            onChange={(event) => setNewSessionTitle(event.target.value)}
            className="field flex-1"
            placeholder="创建 Skill 会话"
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
            onClick={() => {
              setSearchParams({ session: session.id });
              setHistoryDrawerOpen(false);
            }}
            className={`list-row w-full text-left ${active ? 'list-row-active' : ''}`}
          >
            <div className="space-y-2">
              <p className="font-medium text-slate-900">{session.title}</p>
              <p className="line-clamp-2 text-sm text-slate-500">{latestRun?.question || '还没有问题'}</p>
            </div>
            <div className="text-right text-sm text-slate-500">
              <p>{runCount} 次运行</p>
              <p>{formatDateTime(session.updated_at)}</p>
            </div>
          </button>
        );
      })}

      {sessionSummaries.length === 0 && (
        <div className="empty-state min-h-[220px]">
          <p className="text-base font-medium text-slate-900">此 Skill 暂无会话历史</p>
          <p className="text-sm text-slate-500">新建会话后，后续运行会按会话归档到左侧历史栏。</p>
        </div>
      )}
    </div>
  );

  const settingsTabContent = (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">Skill 默认配置</h3>
          <p className="mt-1 text-sm text-slate-500">
            Provider、模型、知识库和系统提示词会保存到 Skill。知识库草稿变更需要保存后才会生效。
          </p>
          {lastSavedAt && (
            <p className="mt-2 text-xs uppercase tracking-[0.18em] text-slate-400">
              上次保存 {formatRelativeTime(lastSavedAt)} · {formatDateTime(lastSavedAt)}
            </p>
          )}
        </div>
        {isConfigDirty && (
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                applySavedSkillState(skill);
                setSaveFeedback(null);
              }}
              className="btn-secondary text-slate-500"
            >
              <Undo size={14} />
              <span>还原</span>
            </button>
            <button
              type="button"
              onClick={() => saveSkillMutation.mutate()}
              disabled={saveSkillMutation.isPending || draftModelMismatch || !draftModel.trim() || !draftProviderId}
              className="btn-primary"
            >
              {saveSkillMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
              <span>{saveSkillMutation.isPending ? '保存中…' : '保存 Skill'}</span>
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
        <p className="text-sm font-medium text-slate-900">Provider 解析链路</p>
        <div className="mt-3 space-y-2 text-sm text-slate-500">
          <p>Skill 已保存 Provider：{skillProvider ? `${skillProvider.name} (${describeProviderOwnership(skillProvider)})` : '此 Skill 未绑定'}</p>
          <p>工作区默认 Provider：{workspaceDefaultProvider ? `${workspaceDefaultProvider.name} (${describeProviderOwnership(workspaceDefaultProvider)})` : '未配置'}</p>
          <p>共享默认 Provider：{tenantDefaultProvider ? `${tenantDefaultProvider.name} (${describeProviderOwnership(tenantDefaultProvider)})` : '未配置或当前不可用'}</p>
          <p>系统默认 Provider：仅后端可见的隐藏回退</p>
        </div>
      </div>

      {isLegacyUnboundSkill && !draftProviderId && (
        <InlineAlert tone="warning" title="旧版未绑定 Skill">
          这个 Skill 还没有保存 Provider。你仍然可以查看和测试它，但现在保存时必须显式绑定一个当前工作区可用的 Provider。
        </InlineAlert>
      )}

      {providers.length === 0 && (
        <InlineAlert
          tone="warning"
          title="当前工作区没有可用 Provider"
          action={(
            <div className="flex gap-2">
              <Link to="/workspace" className="btn-secondary">
                <span>工作区设置</span>
              </Link>
              <Link to="/providers" className="btn-secondary">
                <span>Provider 管理</span>
              </Link>
            </div>
          )}
        >
          保存 Skill 前，请先把租户 Provider 共享到当前工作区、导入共享 Provider，或设置工作区默认 Provider。
        </InlineAlert>
      )}

      <Field label="Skill 名称">
        <input
          value={draftName}
          onChange={(event) => markDraftEdited(setDraftName)(event.target.value)}
          className="field"
        />
      </Field>

      <Field label="系统提示词" required>
        <textarea
          value={draftSystemPrompt}
          onChange={(event) => markDraftEdited(setDraftSystemPrompt)(event.target.value)}
          className="field min-h-[120px]"
          required
        />
      </Field>

      <Field label="知识库" hint="当前只能绑定一个知识库。知识库草稿变更需要保存后才会影响运行。">
        <select
          value={draftKnowledgeBaseId || ''}
          onChange={(event) => markDraftEdited(setDraftKnowledgeBaseId)(event.target.value || null)}
          className="field"
        >
          <option value="">未绑定知识库</option>
          {knowledgeBases.map((kb) => (
            <option key={kb.id} value={kb.id}>
              {kb.name}
            </option>
          ))}
        </select>
        {skill.knowledge_base_id !== draftKnowledgeBaseId && (
          <p className="mt-1 text-xs text-amber-600">知识库变更在保存 Skill 前只作为草稿保留。</p>
        )}
      </Field>

      <Field label="Provider" hint="该配置会保存到 Skill。这里只显示当前工作区可用的 Provider；系统回退不可手动选择。">
        <select value={draftProviderId} onChange={(event) => handleDraftProviderChange(event.target.value)} className="field">
          <option value="" disabled>
            {isLegacyUnboundSkill ? '选择 Provider 并绑定到 Skill' : '选择 Provider'}
          </option>
          {selectableProviders.map((provider) => (
            <option key={provider.id} value={provider.id}>
              {provider.name} · {provider.scope === 'workspace' ? '工作区自有' : provider.is_default ? '共享默认' : '共享'}
            </option>
          ))}
        </select>
        <p className="mt-1 text-xs text-slate-500">
          如今天仍未绑定，已保存配置会解析为：{draftResolvedProvider?.name || '后端系统默认'}
        </p>
        {draftResolvedProvider && (
          <p className="mt-1 text-xs text-slate-500">
            当前 Provider：{describeProviderOwnership(draftResolvedProvider)} · {describeProviderAvailability(draftResolvedProvider)}
          </p>
        )}
        {!selectableProviders.length && (
          <p className="mt-1 text-xs text-amber-600">
            当前工作区还没有可用 Provider，所以列表为空。
          </p>
        )}
      </Field>

      <Field
        label="模型"
        hint={draftResolvedProvider ? `默认模型：${draftResolvedProvider.default_model}` : '请先选择 Provider，系统会根据 Provider 给出可用模型建议。'}
      >
        <div className="space-y-3">
          {draftModelOptions.length > 0 ? (
            <select
              value={draftModelSelectValue}
              onChange={(event) => handleDraftModelSelectChange(event.target.value)}
              className="field"
            >
              <option value="" disabled>选择模型</option>
              {draftModelOptions.map((model) => (
                <option key={model} value={model}>
                  {model}{model === draftResolvedProvider?.default_model ? '（默认）' : ''}
                </option>
              ))}
              <option value={CUSTOM_MODEL_VALUE}>自定义模型…</option>
            </select>
          ) : null}
          {(draftModelOptions.length === 0 || draftModelSelectValue === CUSTOM_MODEL_VALUE) && (
            <input
              value={draftModel}
              onChange={(event) => markDraftEdited(setDraftModel)(event.target.value)}
              className="field"
              placeholder={draftResolvedProvider?.default_model || '输入模型名称'}
            />
          )}
        </div>
      </Field>

      {draftModelMismatch && draftResolvedProvider && (
        <InlineAlert tone="warning" title="Provider 与模型不匹配">
          {`模型“${draftModel}”不在 ${draftResolvedProvider.name} 的支持列表中。`}
        </InlineAlert>
      )}

      {savedConfigModelMismatch && savedResolvedProvider && !isConfigDirty && (
        <InlineAlert tone="warning" title="已保存配置需要检查">
          {`已保存的模型“${skill.model}”已不在 ${savedResolvedProvider.name} 的支持列表中。`}
        </InlineAlert>
      )}

      <div className="rounded-[24px] border border-white/75 bg-white/58 p-4">
        <div className="mb-4">
          <p className="text-sm font-medium text-slate-900">检索与生成默认配置</p>
          <p className="mt-1 text-sm text-slate-500">这里的值会立即用于下一次运行；点击“保存 Skill”后，这些值也会保存为该 Skill 的默认配置。Provider 仍然通过上面的已保存 Provider 管理。</p>
        </div>

        <div className="grid gap-4 xl:grid-cols-2">
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" checked={effectiveQueryRewriteWithHistory} onChange={(event) => setQueryRewriteWithHistory(event.target.checked)} />
            <span>根据最近聊天历史改写检索问题</span>
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" checked={effectiveIncludeHistory} onChange={(event) => setIncludeHistory(event.target.checked)} />
            <span>在回答提示词中带入最近聊天历史</span>
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={effectiveIncludeAssistantMessages}
              onChange={(event) => setIncludeAssistantMessages(event.target.checked)}
              disabled={!effectiveIncludeHistory}
            />
            <span>在上述历史中包含之前的最终模型回复</span>
          </label>
          <Field label="历史最大用户轮数" hint="按最近的用户轮次统计。只有用户问题和最终模型回复会进入下一轮上下文，中间检索过程和遥测不会带入。">
            <input type="number" min="1" value={effectiveHistoryTurnLimit} onChange={(event) => setHistoryTurnLimit(event.target.value)} className="field" />
          </Field>
          <Field label="历史 Token 预算" hint="本次运行中可带入聊天历史的大致 token 上限。">
            <input type="number" min="1" value={effectiveHistoryTokenBudget} onChange={(event) => setHistoryTokenBudget(event.target.value)} className="field" />
          </Field>
          <Field label="检索段落数" hint="在生成答案前，最多从目录/大纲中选出的候选段落数量。">
            <input type="number" min="1" value={effectiveTopK} onChange={(event) => setTopK(event.target.value)} className="field" />
          </Field>
          <Field label="Fast Search 节点数" hint="Fast Search 模式下召回的正文节点数。推荐 3，最大 10；每个节点可能对应一整个章节正文。">
            <input
              type="number"
              min="1"
              max={FAST_SEARCH_TOP_K_MAX}
              value={effectiveFastSearchTopK}
              onChange={(event) => markDraftEdited(setFastSearchTopK)(normalizeFastSearchTopK(event.target.value))}
              className="field"
            />
          </Field>
          <Field
            label="段落选择方式"
            hint="模型引导模式会先让模型选择目录段落；关键词回退模式会跳过这一步，直接按标题做词法匹配。"
          >
            <select value={effectiveSelectionMode} onChange={(event) => setSelectionMode(event.target.value)} className="field">
              {SELECTION_MODE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="回答上下文最大 PDF 页数" hint="可选。限制最终回答阶段最多带入多少页 PDF 内容。">
            <input type="number" min="1" value={effectiveMaxContextPages} onChange={(event) => setMaxContextPages(event.target.value)} className="field" placeholder="可选" />
          </Field>
          <Field label="回答上下文最大摘录 Token 数" hint={`可选。留空表示不设上限；如需限制，推荐 ${RECOMMENDED_CONTEXT_TOKEN_BUDGET}。`}>
            <input type="number" min="1" value={effectiveMaxContextTokens} onChange={(event) => setMaxContextTokens(event.target.value)} className="field" placeholder={`可选，推荐 ${RECOMMENDED_CONTEXT_TOKEN_BUDGET}`} />
          </Field>
          <Field
            label="Rerank 模式"
            hint={
              draftResolvedProvider?.capabilities?.rerank_models?.length
                ? `当前 Provider 可用的 rerank 模型：${draftResolvedProvider.capabilities.rerank_models.join(', ')}`
                : 'Auto 会优先使用可用的 rerank；如果系统未配置可用 rerank，则回退为原始检索顺序。'
            }
          >
            <select value={effectiveRerankMode} onChange={(event) => setRerankMode(event.target.value)} className="field">
              <option value="auto">自动</option>
              <option value="off">关闭</option>
              <option value="provider">Provider 重排</option>
              <option value="system">系统重排</option>
            </select>
          </Field>
        </div>
      </div>

      <Field label="回答温度" hint="0 最稳定。后端接受 0 到 2 之间的数值。">
        <input type="number" min="0" step="0.1" value={effectiveTemperature} onChange={(event) => setTemperature(event.target.value)} className="field" />
      </Field>
    </div>
  );

  const runtimeTabContent = (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3">
        <KeyMetric label="会话" value={selectedSession?.title || '未选择会话'} />
        <KeyMetric label="模型" value={activeExecutionContext.model?.resolved_model || savedConfigModel || 'N/A'} />
        <KeyMetric label="Provider" value={activeExecutionContext.provider?.name || savedRunProvider?.name || '后端系统默认'} />
        <KeyMetric label="Provider 来源" value={formatResolutionSource(activeExecutionContext.provider?.resolution_source)} />
        <KeyMetric label="引用" value={displayRun?.citations.length ?? 0} />
      </div>

      {boundKnowledgeBase ? (
        <div className="surface-soft p-4">
          <p className="metric-label">知识库</p>
          <p className="mt-2 font-medium text-slate-900">{boundKnowledgeBase.name}</p>
        </div>
      ) : skillDocuments.length > 0 ? (
        <div className="surface-soft p-4">
          <p className="metric-label">旧版目标文档</p>
          <p className="mt-2 font-medium text-slate-900">已绑定 {skillDocuments.length} 份文档</p>
        </div>
      ) : null}

      {(displayRun || activeStatus || activeExecutionContext.retrieval?.query || activeExecutionContext.model?.resolved_model) ? (
        <>
          <div className="grid grid-cols-2 gap-3">
            <KeyMetric
              label="总耗时"
              value={formatMillisecondsAsSeconds(displayRun?.metrics.total_ms)}
              hint="后端口径：检索耗时 + 回答生成阶段，不含排队。"
            />
            <KeyMetric
              label="首 token 等待"
              value={formatMillisecondsAsSeconds(displayRun?.metrics.ttft_ms)}
              hint="从进入回答生成阶段到收到首个可见 token；不是从 run 开始计时。"
            />
            <KeyMetric label="检索耗时" value={formatMillisecondsAsSeconds(displayRun?.metrics.retrieve_ms)} />
            <KeyMetric
              label="生成阶段耗时"
              value={formatMillisecondsAsSeconds(displayRun?.metrics.answer_ms)}
              hint="从进入回答阶段到流式回答结束；首 token 等待包含在这里。"
            />
            <KeyMetric
              label="Provider 首 token"
              value={formatMillisecondsAsSeconds(displayRun?.metrics.provider_ttft_ms)}
              hint="从实际发起 Provider stream 请求到首个可见 token。"
            />
            <KeyMetric
              label="调用前开销"
              value={formatMillisecondsAsSeconds(displayRun?.metrics.answer_pre_provider_ms)}
              hint="进入回答阶段后、本地构造并发起 Provider 请求前的开销。"
            />
            <KeyMetric label="Token 用量" value={displayRun?.metrics.total_tokens ?? 'N/A'} hint={formatTokenBreakdown(displayRun?.metrics)} />
            <KeyMetric label="已选段落" value={displayRun ? (displayRun.metrics.selected_section_count ?? displayRun.selected_sections.length) : '等待中'} />
            <KeyMetric label="使用历史" value={activeExecutionContext.conversation?.history_used ? '是' : '否'} />
          </div>

          {activeStatus && (
            <div className="surface-soft p-4">
              <p className="metric-label">运行状态</p>
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
                  已请求取消{displayRun.cancel_reason ? `：${displayRun.cancel_reason}` : ''}
                </p>
              )}
              {displayRun?.last_error && activeStatus === 'failed' && (
                <p className="mt-2 whitespace-pre-wrap text-xs text-red-500">{humanizeSkillRunError(displayRun.last_error)}</p>
              )}
            </div>
          )}

          {activeExecutionContext.retrieval?.warnings && activeExecutionContext.retrieval.warnings.length > 0 && (
            <InlineAlert tone="warning" title="运行中已调整检索">
              <div className="space-y-1">
                {activeExecutionContext.retrieval.warnings.map((warning, index) => (
                  <p key={`${warning}-${index}`}>{warning}</p>
                ))}
              </div>
            </InlineAlert>
          )}

          {(activeExecutionContext.retrieval?.query || activeExecutionContext.retrieval?.rewritten_query) && (
            <div className="surface-soft p-4">
              <p className="metric-label">检索问题</p>
              <p className="mt-2 text-sm text-slate-700">{activeExecutionContext.retrieval?.query || 'N/A'}</p>
              {activeExecutionContext.retrieval?.rewrite_applied && activeExecutionContext.retrieval?.rewritten_query && (
                <p className="mt-2 text-xs text-slate-500">改写后问题：{activeExecutionContext.retrieval.rewritten_query}</p>
              )}
            </div>
          )}

          {displayRun?.citations.length ? (
            <div className="space-y-3">
              <p className="text-sm font-semibold text-slate-900">引用</p>
              {displayRun.citations.map((citation, index) => (
                <div key={`${citation.document_id || 'citation'}-${index}`} className="surface-soft p-4">
                  <p className="font-medium text-slate-900">{citation.title || citation.document_id || '未命名引用'}</p>
                  <p className="mt-2 text-sm text-slate-500">
                    {citation.page_start || citation.page_end ? formatPageRange(citation.page_start, citation.page_end) : '页码范围不可用'}
                  </p>
                </div>
              ))}
            </div>
          ) : null}

          <RunObservationTimeline
            snapshot={activeObservationSnapshot}
            title="执行时间线"
            emptyTitle="暂无运行遥测"
            emptyDescription="运行 Skill 后，这里会显示后端步骤、重排决策和模型输入输出。"
          />
        </>
      ) : (
        <div className="empty-state min-h-[220px]">
          <p className="text-base font-medium text-slate-900">暂无运行遥测</p>
          <p className="text-sm text-slate-500">运行 Skill 后，这里会显示解析后的 Provider、模型和引用信息。</p>
        </div>
      )}
    </div>
  );

  return (
    <div className="space-y-6">
      <div className="skill-console-header">
        <div className="flex min-w-0 items-center gap-3">
          <Link to="/skills" className="btn-secondary">
            <ArrowLeft size={16} />
            <span>返回 Skills</span>
          </Link>
          <div className="min-w-0">
            <h2 className="truncate text-[28px] font-semibold tracking-[-0.03em] text-slate-900">{skill.name}</h2>
            <p className="truncate text-sm text-slate-500">
              {selectedSession?.title || '未选择会话'}
              {boundKnowledgeBase ? ` · ${boundKnowledgeBase.name}` : ''}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="btn-secondary"
            onClick={() => (
              isCompactLayout
                ? setHistoryDrawerOpen(true)
                : updateLayoutState({ historyOpen: !layoutState.historyOpen })
            )}
          >
            {isCompactLayout || !layoutState.historyOpen ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
            <span>历史</span>
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => (
              isCompactLayout
                ? setInspectorDrawerOpen(true)
                : updateLayoutState({ inspectorOpen: !layoutState.inspectorOpen })
            )}
          >
            {isCompactLayout || !layoutState.inspectorOpen ? <PanelRightOpen size={16} /> : <PanelRightClose size={16} />}
            <span>设置</span>
          </button>
          <button type="button" className="icon-button" onClick={() => setActionsOpen(true)} aria-label="打开 Skill 操作">
            <MoreHorizontal size={16} />
          </button>
        </div>
      </div>

      <div className="skill-console-shell">
        {!isCompactLayout && (
          layoutState.historyOpen ? (
            <GlassPanel className="skill-console-rail" title="历史" subtitle="仅显示此 Skill 的会话和最近问题。">
              {historyPanelContent}
            </GlassPanel>
          ) : (
            <div className="skill-console-rail skill-console-rail-collapsed">
              <button
                type="button"
                className="skill-console-rail-trigger"
                onClick={() => updateLayoutState({ historyOpen: true })}
                aria-label="展开历史"
              >
                <div className="flex h-12 w-12 items-center justify-center rounded-[22px] bg-white/82 text-blue-600">
                  <History size={18} />
                </div>
                <div className="space-y-4">
                  <p className="skill-console-rail-label">历史</p>
                  <p className="text-xs font-medium text-slate-500">{sessionSummaries.length} 个会话</p>
                </div>
                <PanelLeftOpen size={18} className="text-slate-400" />
              </button>
            </div>
          )
        )}

        <div className="skill-console-stage">
          <GlassPanel title="对话" subtitle={selectedSession?.title || '创建或选择一个会话，将本 Skill 的运行归档到同一组。'}>
            <div className="space-y-4">
              <div className="flex items-center gap-4 border-b border-slate-200/60 pb-4 mb-2">
                <SegmentedControl
                  value={searchMode}
                  onChange={(value) => setSearchMode(value as 'deep_research' | 'fast_search')}
                  items={[
                    { value: 'deep_research', label: 'DeepResearch' },
                    { value: 'fast_search', label: 'Fast Search' },
                  ]}
                />
              </div>

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
                        <span>重试</span>
                      </button>
                    ) : undefined
                  }
                >
                  <div className="space-y-1">
                    <p>{chatAlert.message}</p>
                    {(chatAlert.code || chatAlert.requestId) && (
                      <p className="text-xs text-slate-400">
                        {chatAlert.code && <span>错误码：{chatAlert.code}</span>}
                        {chatAlert.requestId && <span> · 请求 ID：{chatAlert.requestId}</span>}
                      </p>
                    )}
                    <p className="text-sm text-slate-500">
                      Provider：{activeExecutionContext.provider?.name || savedRunProvider?.name || '后端系统默认'} ·
                      {' '}模型：{activeExecutionContext.model?.resolved_model || savedConfigModel || 'N/A'}
                    </p>
                    <p className="text-sm text-slate-500">
                      解析来源：{formatResolutionSource(activeExecutionContext.provider?.resolution_source)}
                    </p>
                  </div>
                </InlineAlert>
              )}

              <div ref={scrollRef} className="scroll-area max-h-[620px] space-y-4 overflow-auto pr-1">
                {conversationHistoryContent}
              </div>

              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  handleRun(false);
                }}
                className="skill-console-composer"
              >
                <div className="flex gap-3 max-md:flex-col">
                  <textarea
                    value={question}
                    onChange={(event) => setQuestion(event.target.value)}
                    className="field min-h-[108px] flex-1 resize-none border-0 bg-transparent p-0 shadow-none focus:shadow-none"
                    placeholder={searchMode === 'fast_search' ? '输入一个需要快速正文召回的问题…' : '通过此 Skill 提问…'}
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
                      <span>取消</span>
                    </button>
                  ) : (
                    <div className="flex flex-col gap-2 self-end max-md:self-stretch">
                      {isConfigDirty && searchMode === 'deep_research' && (
                        <button
                          type="button"
                          className="btn-secondary"
                          onClick={() => handleRun(true)}
                          disabled={!question.trim() || isStreaming || draftModelMismatch}
                        >
                          <Bot size={16} />
                          <span>用草稿测试</span>
                        </button>
                      )}
                      <button
                        type="submit"
                        className="btn-primary w-full justify-center"
                        disabled={
                          !question.trim() ||
                          isStreaming ||
                          savedRunModelMismatch
                        }
                      >
                        <Send size={16} />
                        <span>{isConfigDirty ? '发送（已保存配置）' : '发送'}</span>
                      </button>
                    </div>
                  )}
                </div>
              </form>
            </div>
          </GlassPanel>
        </div>

        {!isCompactLayout && (
          layoutState.inspectorOpen ? (
            <GlassPanel
              className="skill-console-rail skill-console-rail-right"
              title="设置"
              subtitle="已保存默认配置和运行数据分开查看。"
              actions={(
                <SegmentedControl
                  value={layoutState.inspectorTab}
                  onChange={(value) => updateLayoutState({ inspectorTab: value as SkillConsoleLayoutState['inspectorTab'] })}
                  items={[
                    { value: 'settings', label: '设置' },
                    { value: 'runtime', label: '运行' },
                  ]}
                />
              )}
            >
              {layoutState.inspectorTab === 'settings' ? settingsTabContent : runtimeTabContent}
            </GlassPanel>
          ) : (
            <div className="skill-console-rail skill-console-rail-right skill-console-rail-collapsed">
              <button
                type="button"
                className="skill-console-rail-trigger"
                onClick={() => updateLayoutState({ inspectorOpen: true })}
                aria-label="展开设置"
              >
                <div className="flex h-12 w-12 items-center justify-center rounded-[22px] bg-white/82 text-blue-600">
                  <SlidersHorizontal size={18} />
                </div>
                <div className="space-y-4">
                  <p className="skill-console-rail-label">设置</p>
                  <p className="text-xs font-medium text-slate-500">{layoutState.inspectorTab === 'settings' ? '已保存配置' : '运行数据'}</p>
                </div>
                <PanelRightOpen size={18} className="text-slate-400" />
              </button>
            </div>
          )
        )}
      </div>

      <ExpertDrawer
        open={isCompactLayout && historyDrawerOpen}
        onClose={() => setHistoryDrawerOpen(false)}
        side="left"
        widthClassName="w-[520px]"
        title="历史"
        description="仅显示此 Skill 的会话和最近问题。"
      >
        {historyPanelContent}
      </ExpertDrawer>

      <ExpertDrawer
        open={isCompactLayout && inspectorDrawerOpen}
        onClose={() => setInspectorDrawerOpen(false)}
        side="right"
        widthClassName="w-[560px]"
        title="设置"
        description="已保存默认配置和运行数据分开查看。"
      >
        <div className="space-y-4">
          <SegmentedControl
            value={layoutState.inspectorTab}
            onChange={(value) => updateLayoutState({ inspectorTab: value as SkillConsoleLayoutState['inspectorTab'] })}
            items={[
              { value: 'settings', label: '设置' },
              { value: 'runtime', label: '运行' },
            ]}
          />
          {layoutState.inspectorTab === 'settings' ? settingsTabContent : runtimeTabContent}
        </div>
      </ExpertDrawer>

      {actionsOpen && (
        <SkillActionsModal
          key={skill.id}
          open={actionsOpen}
          skill={skill}
          onClose={() => setActionsOpen(false)}
          onUpdated={(updatedSkill) => {
            setDraftName(updatedSkill.name);
            setLastSavedAt(updatedSkill.updated_at);
            setSaveFeedback({
              tone: 'success',
              title: 'Skill 已更新',
              message: 'Skill 元数据已变更。',
            });
          }}
          onDeleted={() => navigate('/skills')}
        />
      )}
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
        <SectionToolbar title="Skill 控制台" description="正在加载已保存配置和会话历史。" />
        <GlassPanel title="正在加载 Skill" subtitle="正在获取当前 Skill 配置。">
          <div className="empty-state min-h-[320px]">
            <Loader2 size={28} className="animate-spin text-blue-600" />
            <p className="text-base font-medium text-slate-900">正在加载 Skill…</p>
          </div>
        </GlassPanel>
      </div>
    );
  }

  if (skillQuery.error || !skillQuery.data) {
    return (
      <div className="space-y-8">
        <SectionToolbar title="Skill 控制台" description="无法解析这个 Skill 路由。" />
        <GlassPanel title="Skill 不存在" subtitle="请求的 Skill 不存在或加载失败。">
          <div className="empty-state min-h-[320px]">
            <p className="text-base font-medium text-slate-900">未找到 Skill</p>
            {skillQuery.error && <p className="text-sm text-slate-500">{getErrorMessage(skillQuery.error, '加载 Skill 失败')}</p>}
            <Link to="/skills" className="btn-primary">
              <ArrowLeft size={16} />
              <span>返回 Skills</span>
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
