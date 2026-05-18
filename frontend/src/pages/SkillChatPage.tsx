import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft,
  Bot,
  Brain,
  Database,
  Gauge,
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
  Settings,
  SlidersHorizontal,
  Square,
  Timer,
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

type SkillConfigTab = 'basic' | 'model' | 'retrieval' | 'generation' | 'advanced';
type ThinkingMode = 'default' | 'off' | 'custom';
type MaxOutputTokenKey = 'max_tokens' | 'max_completion_tokens';

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
const DEFAULT_TEMPERATURE = '0.2';
const DEFAULT_THINKING_BUDGET = '1024';

const SELECTION_MODE_OPTIONS = [
  { value: 'outline_llm', label: '模型引导大纲选择' },
  { value: 'lexical_fallback', label: '仅关键词回退' },
];

const CONFIG_TABS: Array<{ value: SkillConfigTab; label: string }> = [
  { value: 'basic', label: '基础' },
  { value: 'model', label: '模型' },
  { value: 'retrieval', label: '检索' },
  { value: 'generation', label: '生成' },
  { value: 'advanced', label: '高级' },
];

const VENDOR_JSON_FORBIDDEN_FIELDS = new Set([
  'api_key',
  'api_base',
  'base_url',
  'extra_headers',
  'model',
  'messages',
  'stream',
]);

const GENERATION_FORM_FIELDS = new Set([
  'temperature',
  'top_p',
  'top_k',
  'max_tokens',
  'max_completion_tokens',
  'stream_options',
  'enable_thinking',
  'thinking_budget',
]);

const GENERATION_RESERVED_FIELDS = new Set([...VENDOR_JSON_FORBIDDEN_FIELDS]);

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

const isPlainRecord = (value: unknown): value is Record<string, unknown> => (
  typeof value === 'object' &&
  value !== null &&
  !Array.isArray(value)
);

const formatOptionalNumber = (value: unknown) => {
  if (value === undefined || value === null || value === '') return '';
  const parsed = Number(value);
  return Number.isFinite(parsed) ? String(value) : '';
};

const coerceOptionalNumber = (label: string, value: string) => {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  const parsed = Number(trimmed);
  if (!Number.isFinite(parsed)) {
    throw new Error(`${label} 必须是数字。`);
  }
  return parsed;
};

const sanitizeGenerationConfig = (config: Record<string, unknown>) => {
  const next = { ...config };
  for (const field of GENERATION_RESERVED_FIELDS) {
    delete next[field];
  }
  return next;
};

const getSavedTemperature = (config: Record<string, unknown>) => formatOptionalNumber(config.temperature) || DEFAULT_TEMPERATURE;

const getSavedMaxOutputKey = (config: Record<string, unknown>): MaxOutputTokenKey => (
  config.max_completion_tokens !== undefined && config.max_completion_tokens !== null
    ? 'max_completion_tokens'
    : 'max_tokens'
);

const getSavedMaxOutputValue = (config: Record<string, unknown>) => {
  const key = getSavedMaxOutputKey(config);
  return formatOptionalNumber(config[key]);
};

const hasIncludeUsage = (config: Record<string, unknown>) => {
  const streamOptions = config.stream_options;
  return isPlainRecord(streamOptions) && streamOptions.include_usage === true;
};

const inferThinkingMode = (config: Record<string, unknown>): ThinkingMode => {
  if (config.enable_thinking === false) return 'off';
  if (config.enable_thinking === true || config.thinking_budget !== undefined) return 'custom';
  return 'default';
};

const getThinkingBudget = (config: Record<string, unknown>) => (
  formatOptionalNumber(config.thinking_budget) || DEFAULT_THINKING_BUDGET
);

const extractVendorGenerationConfig = (config: Record<string, unknown>) => {
  const vendorConfig: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(config)) {
    if (GENERATION_FORM_FIELDS.has(key) || VENDOR_JSON_FORBIDDEN_FIELDS.has(key)) continue;
    vendorConfig[key] = value;
  }
  return vendorConfig;
};

const stringifyVendorGenerationConfig = (config: Record<string, unknown>) => {
  const vendorConfig = extractVendorGenerationConfig(config);
  return Object.keys(vendorConfig).length ? JSON.stringify(vendorConfig, null, 2) : '{}';
};

const parseVendorGenerationConfig = (text: string) => {
  const trimmed = text.trim();
  if (!trimmed) return {};
  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch (error) {
    throw new Error(`厂商扩展 JSON 解析失败：${error instanceof Error ? error.message : '格式错误'}`);
  }
  if (!isPlainRecord(parsed)) {
    throw new Error('厂商扩展 JSON 必须是 object。');
  }
  const forbidden = Object.keys(parsed).filter((key) => VENDOR_JSON_FORBIDDEN_FIELDS.has(key));
  if (forbidden.length > 0) {
    throw new Error(`厂商扩展 JSON 不能包含运行时或密钥字段：${forbidden.join(', ')}`);
  }
  const conflicts = Object.keys(parsed).filter((key) => GENERATION_FORM_FIELDS.has(key));
  if (conflicts.length > 0) {
    throw new Error(`厂商扩展 JSON 与表单字段冲突：${conflicts.join(', ')}。请使用对应表单项配置。`);
  }
  return parsed;
};

const summarizeThinkingMode = (mode: ThinkingMode) => {
  if (mode === 'off') return '关闭';
  if (mode === 'custom') return '自定义';
  return '默认';
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
  const [temperature, setTemperature] = useState(() => getSavedTemperature((skill.generation_config || {}) as Record<string, unknown>));
  const [topP, setTopP] = useState(() => formatOptionalNumber(((skill.generation_config || {}) as Record<string, unknown>).top_p));
  const [generationTopK, setGenerationTopK] = useState(() => formatOptionalNumber(((skill.generation_config || {}) as Record<string, unknown>).top_k));
  const [maxOutputTokenKey, setMaxOutputTokenKey] = useState<MaxOutputTokenKey>(() => getSavedMaxOutputKey((skill.generation_config || {}) as Record<string, unknown>));
  const [maxOutputTokens, setMaxOutputTokens] = useState(() => getSavedMaxOutputValue((skill.generation_config || {}) as Record<string, unknown>));
  const [includeStreamUsage, setIncludeStreamUsage] = useState(() => hasIncludeUsage((skill.generation_config || {}) as Record<string, unknown>));
  const [thinkingMode, setThinkingMode] = useState<ThinkingMode>(() => inferThinkingMode((skill.generation_config || {}) as Record<string, unknown>));
  const [thinkingBudget, setThinkingBudget] = useState(() => getThinkingBudget((skill.generation_config || {}) as Record<string, unknown>));
  const [vendorJsonText, setVendorJsonText] = useState(() => stringifyVendorGenerationConfig((skill.generation_config || {}) as Record<string, unknown>));
  const [configDrawerOpen, setConfigDrawerOpen] = useState(false);
  const [runtimeDrawerOpen, setRuntimeDrawerOpen] = useState(false);
  const [configTab, setConfigTab] = useState<SkillConfigTab>('basic');
  const [useDraftForNextRun, setUseDraftForNextRun] = useState(false);
  const [streamingObservations, setStreamingObservations] = useState<RunObservationEvent[]>([]);
  const [chatAlert, setChatAlert] = useState<AlertState | null>(null);
  const [saveFeedback, setSaveFeedback] = useState<SaveFeedback | null>(null);
  const [lastSavedAt, setLastSavedAt] = useState<string | null>(skill.updated_at);

  const [searchMode, setSearchMode] = useState<'deep_research' | 'fast_search'>(() => (
    ((skill.retrieval_config || {}) as Record<string, unknown>).retrieval_mode === 'fast'
      ? 'fast_search'
      : 'deep_research'
  ));
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

  const resetSavedConfigOverrides = (nextSkill: ChatSkill = skill) => {
    const nextRetrievalDefaults = (nextSkill.retrieval_config || {}) as Record<string, unknown>;
    const nextGenerationDefaults = (nextSkill.generation_config || {}) as Record<string, unknown>;
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
    setSearchMode(nextRetrievalDefaults.retrieval_mode === 'fast' ? 'fast_search' : 'deep_research');
    setTemperature(getSavedTemperature(nextGenerationDefaults));
    setTopP(formatOptionalNumber(nextGenerationDefaults.top_p));
    setGenerationTopK(formatOptionalNumber(nextGenerationDefaults.top_k));
    setMaxOutputTokenKey(getSavedMaxOutputKey(nextGenerationDefaults));
    setMaxOutputTokens(getSavedMaxOutputValue(nextGenerationDefaults));
    setIncludeStreamUsage(hasIncludeUsage(nextGenerationDefaults));
    setThinkingMode(inferThinkingMode(nextGenerationDefaults));
    setThinkingBudget(getThinkingBudget(nextGenerationDefaults));
    setVendorJsonText(stringifyVendorGenerationConfig(nextGenerationDefaults));
    setUseDraftForNextRun(false);
  };

  const applySavedSkillState = (nextSkill: ChatSkill) => {
    setDraftName(nextSkill.name);
    setDraftSystemPrompt(nextSkill.system_prompt || '');
    setDraftModel(nextSkill.model || '');
    setDraftKnowledgeBaseId(nextSkill.knowledge_base_id || null);
    setDraftProviderId(nextSkill.provider_id || '');
    setLastSavedAt(nextSkill.updated_at);
    resetSavedConfigOverrides(nextSkill);
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
  const draftModelSelectValue = draftSelectedModelOption || '';

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
  const skillGenerationDefaults = sanitizeGenerationConfig((skill.generation_config || {}) as Record<string, unknown>);
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
  const effectiveTemperature = temperature || getSavedTemperature(skillGenerationDefaults);
  const effectiveTopP = topP;
  const effectiveGenerationTopK = generationTopK;
  const effectiveMaxOutputTokens = maxOutputTokens;
  const effectiveThinkingMode = thinkingMode;
  const effectiveThinkingBudget = thinkingBudget;
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
  const savedSearchMode = skillRetrievalDefaults.retrieval_mode === 'fast' ? 'fast_search' : 'deep_research';
  const savedTemperature = getSavedTemperature(skillGenerationDefaults);
  const savedTopP = formatOptionalNumber(skillGenerationDefaults.top_p);
  const savedGenerationTopK = formatOptionalNumber(skillGenerationDefaults.top_k);
  const savedMaxOutputKey = getSavedMaxOutputKey(skillGenerationDefaults);
  const savedMaxOutputTokens = getSavedMaxOutputValue(skillGenerationDefaults);
  const savedIncludeStreamUsage = hasIncludeUsage(skillGenerationDefaults);
  const savedThinkingMode = inferThinkingMode(skillGenerationDefaults);
  const savedThinkingBudget = getThinkingBudget(skillGenerationDefaults);
  const savedVendorJsonText = stringifyVendorGenerationConfig(skillGenerationDefaults);
  const vendorJsonValidation = useMemo(() => {
    try {
      return { config: parseVendorGenerationConfig(vendorJsonText), error: '' };
    } catch (error) {
      return { config: {}, error: error instanceof Error ? error.message : '厂商扩展 JSON 解析失败。' };
    }
  }, [vendorJsonText]);

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
    searchMode !== savedSearchMode ||
    effectiveTemperature !== savedTemperature ||
    effectiveTopP !== savedTopP ||
    effectiveGenerationTopK !== savedGenerationTopK ||
    maxOutputTokenKey !== savedMaxOutputKey ||
    effectiveMaxOutputTokens !== savedMaxOutputTokens ||
    includeStreamUsage !== savedIncludeStreamUsage ||
    effectiveThinkingMode !== savedThinkingMode ||
    effectiveThinkingBudget !== savedThinkingBudget ||
    vendorJsonText.trim() !== savedVendorJsonText.trim()
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

  const buildDraftConversationConfig = () => ({
    query_rewrite_with_history: effectiveQueryRewriteWithHistory,
    include_history: effectiveIncludeHistory,
    include_assistant_messages: effectiveIncludeAssistantMessages,
    history_turn_limit: Number(effectiveHistoryTurnLimit || DEFAULT_CONVERSATION_CONFIG.history_turn_limit),
    history_token_budget: Number(effectiveHistoryTokenBudget || DEFAULT_CONVERSATION_CONFIG.history_token_budget),
  });

  const buildSavedConversationConfig = () => ({
    query_rewrite_with_history: savedQueryRewriteWithHistory,
    include_history: savedIncludeHistory,
    include_assistant_messages: savedIncludeAssistantMessages,
    history_turn_limit: Number(savedHistoryTurnLimit || DEFAULT_CONVERSATION_CONFIG.history_turn_limit),
    history_token_budget: Number(savedHistoryTokenBudget || DEFAULT_CONVERSATION_CONFIG.history_token_budget),
  });

  const buildDraftRetrievalConfig = () => ({
    top_k: Number(effectiveTopK || 5),
    selection_mode: effectiveSelectionMode,
    rerank_mode: effectiveRerankMode,
    retrieval_mode: searchMode === 'fast_search' ? 'fast' : 'deep_research',
    node_top_k: Number(effectiveFastSearchTopK || FAST_SEARCH_TOP_K_RECOMMENDED),
    ...(effectiveMaxContextPages.trim() ? { max_context_pages: Number(effectiveMaxContextPages) } : {}),
    ...(effectiveMaxContextTokens.trim() ? { max_context_tokens: Number(effectiveMaxContextTokens) } : {}),
  });

  const buildSavedRetrievalConfig = () => ({
    top_k: Number(savedTopK || 5),
    selection_mode: savedSelectionMode,
    rerank_mode: savedRerankMode,
    retrieval_mode: searchMode === 'fast_search' ? 'fast' : 'deep_research',
    node_top_k: Number(savedFastSearchTopK || FAST_SEARCH_TOP_K_RECOMMENDED),
    ...(savedMaxContextPages.trim() ? { max_context_pages: Number(savedMaxContextPages) } : {}),
    ...(savedMaxContextTokens.trim() ? { max_context_tokens: Number(savedMaxContextTokens) } : {}),
  });

  const buildDraftGenerationConfig = () => {
    if (vendorJsonValidation.error) {
      throw new Error(vendorJsonValidation.error);
    }
    const next: Record<string, unknown> = {};
    const temperatureValue = coerceOptionalNumber('temperature', effectiveTemperature);
    if (temperatureValue !== undefined) next.temperature = temperatureValue;
    const topPValue = coerceOptionalNumber('top_p', effectiveTopP);
    if (topPValue !== undefined) next.top_p = topPValue;
    const topKValue = coerceOptionalNumber('top_k', effectiveGenerationTopK);
    if (topKValue !== undefined) next.top_k = topKValue;
    const maxOutputValue = coerceOptionalNumber(maxOutputTokenKey, effectiveMaxOutputTokens);
    if (maxOutputValue !== undefined) next[maxOutputTokenKey] = maxOutputValue;
    if (includeStreamUsage) {
      next.stream_options = { include_usage: true };
    }
    if (effectiveThinkingMode === 'off') {
      next.enable_thinking = false;
      next.thinking_budget = 0;
    } else if (effectiveThinkingMode === 'custom') {
      const budget = coerceOptionalNumber('thinking_budget', effectiveThinkingBudget);
      if (budget === undefined) {
        throw new Error('自定义 Thinking 需要填写 thinking_budget。');
      }
      next.enable_thinking = true;
      next.thinking_budget = budget;
    }
    return sanitizeGenerationConfig({ ...next, ...vendorJsonValidation.config });
  };

  const buildSavedGenerationConfig = () => sanitizeGenerationConfig(skillGenerationDefaults);

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
        conversation_config: buildDraftConversationConfig(),
        retrieval_config: buildDraftRetrievalConfig(),
        generation_config: buildDraftGenerationConfig(),
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
      const retrieval_config = isDraft ? buildDraftRetrievalConfig() : buildSavedRetrievalConfig();
      const conversation_config = isDraft ? buildDraftConversationConfig() : buildSavedConversationConfig();
      const generation_config = isDraft ? buildDraftGenerationConfig() : buildSavedGenerationConfig();
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

    const shouldUseDraft = isDraft || useDraftForNextRun;
    if (shouldUseDraft && !draftResolvedProvider) return;
    if (shouldUseDraft && draftModelMismatch) return;
    if (!shouldUseDraft && savedRunModelMismatch) return;
    if (shouldUseDraft) {
      try {
        buildDraftGenerationConfig();
      } catch (error) {
        setSaveFeedback({
          tone: 'danger',
          title: '本次运行配置无效',
          message: error instanceof Error ? error.message : '请检查生成配置。',
        });
        setConfigDrawerOpen(true);
        setConfigTab('advanced');
        return;
      }
    }
    setUseDraftForNextRun(false);
    setLastRunWasDraft(shouldUseDraft);
    runSkillMutation.mutate({ q: trimmedQuestion, isDraft: shouldUseDraft });
  };

  const handleUseDraftForNextRun = () => {
    if (!draftResolvedProvider || draftModelMismatch) return;
    try {
      buildDraftGenerationConfig();
    } catch (error) {
      setSaveFeedback({
        tone: 'danger',
        title: '草稿配置无效',
        message: error instanceof Error ? error.message : '请检查生成配置。',
      });
      setConfigTab('advanced');
      return;
    }
    setUseDraftForNextRun(true);
    setConfigDrawerOpen(false);
    setSaveFeedback({
      tone: 'success',
      title: '已设为本次运行草稿',
      message: '下一次发送会使用当前抽屉里的草稿配置，不会保存到 Skill 或 Provider Center。',
    });
  };

  const buildDraftRequestPreview = () => {
    if (vendorJsonValidation.error) return '修复厂商扩展 JSON 后可预览请求。';
    try {
      return JSON.stringify({
        model: draftModel || draftResolvedProvider?.default_model || '<resolved model>',
        messages: [{ role: 'user', content: '<redacted prompt>' }],
        stream: true,
        ...buildDraftGenerationConfig(),
      }, null, 2);
    } catch (error) {
      return error instanceof Error ? error.message : '请求预览不可用。';
    }
  };

  const generationSummary = [
    `temp ${effectiveTemperature || '默认'}`,
    effectiveMaxOutputTokens ? `${maxOutputTokenKey} ${effectiveMaxOutputTokens}` : 'max output 默认',
    `thinking ${summarizeThinkingMode(effectiveThinkingMode)}`,
  ].join(' · ');

  const savedGenerationSummary = [
    `temp ${savedTemperature || '默认'}`,
    savedMaxOutputTokens ? `${savedMaxOutputKey} ${savedMaxOutputTokens}` : 'max output 默认',
    `thinking ${summarizeThinkingMode(savedThinkingMode)}`,
  ].join(' · ');

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

  const skillConfigDrawerContent = (
    <div className="flex min-h-[calc(100vh-9rem)] flex-col">
      <div className="sticky top-0 z-10 space-y-4 bg-white/70 pb-4 backdrop-blur">
        <SegmentedControl
          value={configTab}
          onChange={(value) => setConfigTab(value as SkillConfigTab)}
          items={CONFIG_TABS}
        />
        {saveFeedback && (
          <InlineAlert tone={saveFeedback.tone} title={saveFeedback.title}>
            {saveFeedback.message}
          </InlineAlert>
        )}
      </div>

      <div className="scroll-area flex-1 space-y-5 overflow-auto pb-6 pr-1">
        {configTab === 'basic' && (
          <div className="grid gap-5 xl:grid-cols-2">
            <Field label="Skill 名称">
              <input value={draftName} onChange={(event) => markDraftEdited(setDraftName)(event.target.value)} className="field" />
            </Field>
            <Field label="知识库" hint="SkillChat 只绑定知识库；embedding 继承知识库/工作区配置。">
              <select value={draftKnowledgeBaseId || ''} onChange={(event) => markDraftEdited(setDraftKnowledgeBaseId)(event.target.value || null)} className="field">
                <option value="">未绑定知识库</option>
                {knowledgeBases.map((kb) => (
                  <option key={kb.id} value={kb.id}>{kb.name}</option>
                ))}
              </select>
            </Field>
            <div className="xl:col-span-2">
              <Field label="系统提示词" required>
                <textarea
                  value={draftSystemPrompt}
                  onChange={(event) => markDraftEdited(setDraftSystemPrompt)(event.target.value)}
                  className="field min-h-[180px]"
                  required
                />
              </Field>
            </div>
          </div>
        )}

        {configTab === 'model' && (
          <div className="space-y-5">
            <div className="grid gap-4 xl:grid-cols-2">
              <div className="surface-soft p-4">
                <p className="metric-label">解析链路</p>
                <div className="mt-3 space-y-2 text-sm text-slate-600">
                  <p>Skill：{skillProvider ? `${skillProvider.name} · ${describeProviderOwnership(skillProvider)}` : '未绑定'}</p>
                  <p>Workspace：{workspaceDefaultProvider ? workspaceDefaultProvider.name : '未配置'}</p>
                  <p>共享默认：{tenantDefaultProvider ? tenantDefaultProvider.name : '未配置或不可用'}</p>
                </div>
              </div>
              <div className="surface-soft p-4">
                <p className="metric-label">当前草稿</p>
                <p className="mt-3 text-sm font-medium text-slate-900">{draftResolvedProvider?.name || '未解析 Provider'}</p>
                <p className="mt-1 text-sm text-slate-500">{draftResolvedProvider ? `${describeProviderOwnership(draftResolvedProvider)} · ${describeProviderAvailability(draftResolvedProvider)}` : '需要先选择可用 Provider'}</p>
              </div>
            </div>

            {isLegacyUnboundSkill && !draftProviderId && (
              <InlineAlert tone="warning" title="旧版未绑定 Skill">
                保存前必须显式绑定一个当前工作区可用的 Provider。
              </InlineAlert>
            )}

            {providers.length === 0 && (
              <InlineAlert tone="warning" title="当前工作区没有可用 Provider">
                请先在 Provider Center 导入或共享 Provider。
              </InlineAlert>
            )}

            <div className="grid gap-5 xl:grid-cols-2">
              <Field label="Provider" hint="只显示当前工作区可绑定的 Provider。">
                <select value={draftProviderId} onChange={(event) => handleDraftProviderChange(event.target.value)} className="field">
                  <option value="" disabled>{isLegacyUnboundSkill ? '选择 Provider 并绑定到 Skill' : '选择 Provider'}</option>
                  {selectableProviders.map((provider) => (
                    <option key={provider.id} value={provider.id}>
                      {provider.name} · {provider.scope === 'workspace' ? '工作区自有' : provider.is_default ? '共享默认' : '共享'}
                    </option>
                  ))}
                </select>
              </Field>
              <Field
                label="模型"
                hint={draftModelOptions.length > 0 ? '只能选择 Provider 已探测或声明的模型。' : 'Provider 没有可用模型列表时，只能使用默认模型。'}
              >
                {draftModelOptions.length > 0 ? (
                  <select value={draftModelSelectValue} onChange={(event) => handleDraftModelSelectChange(event.target.value)} className="field">
                    <option value="" disabled>选择模型</option>
                    {draftModelOptions.map((model) => (
                      <option key={model} value={model}>{model}{model === draftResolvedProvider?.default_model ? '（默认）' : ''}</option>
                    ))}
                  </select>
                ) : (
                  <input value={draftResolvedProvider?.default_model || ''} className="field" disabled placeholder="Provider 未声明默认模型" />
                )}
              </Field>
            </div>

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
          </div>
        )}

        {configTab === 'retrieval' && (
          <div className="space-y-5">
            <SegmentedControl
              value={searchMode}
              onChange={(value) => setSearchMode(value as 'deep_research' | 'fast_search')}
              items={[
                { value: 'deep_research', label: 'DeepResearch' },
                { value: 'fast_search', label: 'Fast Search' },
              ]}
            />
            <div className="grid gap-4 xl:grid-cols-2">
              <label className="flex items-center gap-2 text-sm text-slate-700">
                <input type="checkbox" checked={effectiveQueryRewriteWithHistory} onChange={(event) => setQueryRewriteWithHistory(event.target.checked)} />
                <span>按最近历史改写检索问题</span>
              </label>
              <label className="flex items-center gap-2 text-sm text-slate-700">
                <input type="checkbox" checked={effectiveIncludeHistory} onChange={(event) => setIncludeHistory(event.target.checked)} />
                <span>回答阶段带入最近历史</span>
              </label>
              <label className="flex items-center gap-2 text-sm text-slate-700">
                <input type="checkbox" checked={effectiveIncludeAssistantMessages} onChange={(event) => setIncludeAssistantMessages(event.target.checked)} disabled={!effectiveIncludeHistory} />
                <span>历史中包含助手最终回复</span>
              </label>
              <Field label="历史最大用户轮数">
                <input type="number" min="1" value={effectiveHistoryTurnLimit} onChange={(event) => setHistoryTurnLimit(event.target.value)} className="field" />
              </Field>
              <Field label="历史 Token 预算">
                <input type="number" min="1" value={effectiveHistoryTokenBudget} onChange={(event) => setHistoryTokenBudget(event.target.value)} className="field" />
              </Field>
              <Field label="DeepResearch 段落数">
                <input type="number" min="1" value={effectiveTopK} onChange={(event) => setTopK(event.target.value)} className="field" />
              </Field>
              <Field label="Fast Search 节点数" hint={`推荐 ${FAST_SEARCH_TOP_K_RECOMMENDED}，最大 ${FAST_SEARCH_TOP_K_MAX}。`}>
                <input type="number" min="1" max={FAST_SEARCH_TOP_K_MAX} value={effectiveFastSearchTopK} onChange={(event) => markDraftEdited(setFastSearchTopK)(normalizeFastSearchTopK(event.target.value))} className="field" />
              </Field>
              <Field label="段落选择方式">
                <select value={effectiveSelectionMode} onChange={(event) => setSelectionMode(event.target.value)} className="field">
                  {SELECTION_MODE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </Field>
              <Field label="回答上下文最大 PDF 页数">
                <input type="number" min="1" value={effectiveMaxContextPages} onChange={(event) => setMaxContextPages(event.target.value)} className="field" placeholder="可选" />
              </Field>
              <Field label="回答上下文最大摘录 Token 数" hint={`可选，推荐 ${RECOMMENDED_CONTEXT_TOKEN_BUDGET}。`}>
                <input type="number" min="1" value={effectiveMaxContextTokens} onChange={(event) => setMaxContextTokens(event.target.value)} className="field" placeholder="可选" />
              </Field>
              <Field label="Rerank 模式">
                <select value={effectiveRerankMode} onChange={(event) => setRerankMode(event.target.value)} className="field">
                  <option value="auto">自动</option>
                  <option value="off">关闭</option>
                  <option value="provider">Provider 重排</option>
                  <option value="system">系统重排</option>
                </select>
              </Field>
            </div>
          </div>
        )}

        {configTab === 'generation' && (
          <div className="grid gap-5 xl:grid-cols-2">
            <Field label="Temperature" hint="0 最稳定；2 最发散。">
              <input type="number" min="0" max="2" step="0.1" value={effectiveTemperature} onChange={(event) => setTemperature(event.target.value)} className="field" />
            </Field>
            <Field label="Top P">
              <input type="number" min="0" max="1" step="0.01" value={effectiveTopP} onChange={(event) => setTopP(event.target.value)} className="field" placeholder="默认" />
            </Field>
            <Field label="Top K">
              <input type="number" min="1" value={effectiveGenerationTopK} onChange={(event) => setGenerationTopK(event.target.value)} className="field" placeholder="默认" />
            </Field>
            <Field label="Max output 参数名">
              <select value={maxOutputTokenKey} onChange={(event) => setMaxOutputTokenKey(event.target.value as MaxOutputTokenKey)} className="field">
                <option value="max_tokens">max_tokens</option>
                <option value="max_completion_tokens">max_completion_tokens</option>
              </select>
            </Field>
            <Field label="Max output tokens">
              <input type="number" min="1" value={effectiveMaxOutputTokens} onChange={(event) => setMaxOutputTokens(event.target.value)} className="field" placeholder="默认" />
            </Field>
            <label className="flex items-center gap-2 self-end rounded-2xl border border-white/70 bg-white/60 px-4 py-3 text-sm text-slate-700">
              <input type="checkbox" checked={includeStreamUsage} onChange={(event) => setIncludeStreamUsage(event.target.checked)} />
              <span>透传 stream_options.include_usage</span>
            </label>
          </div>
        )}

        {configTab === 'advanced' && (
          <div className="space-y-5">
            <div className="grid gap-5 xl:grid-cols-2">
              <Field label="Thinking 模式" hint="字段是否生效取决于 endpoint。">
                <select value={thinkingMode} onChange={(event) => setThinkingMode(event.target.value as ThinkingMode)} className="field">
                  <option value="default">Default：不发送 thinking 字段</option>
                  <option value="off">Off：enable_thinking=false</option>
                  <option value="custom">Custom：设置 thinking_budget</option>
                </select>
              </Field>
              <Field label="Thinking budget">
                <input type="number" min="0" value={effectiveThinkingBudget} onChange={(event) => setThinkingBudget(event.target.value)} className="field" disabled={thinkingMode !== 'custom'} />
              </Field>
            </div>
            <Field label="厂商扩展 JSON" hint="只允许顶层 object；禁止 api_key/api_base/base_url/extra_headers/model/messages/stream。">
              <textarea value={vendorJsonText} onChange={(event) => setVendorJsonText(event.target.value)} className="field min-h-[170px] font-mono text-xs" spellCheck={false} />
            </Field>
            {vendorJsonValidation.error && (
              <InlineAlert tone="danger" title="厂商扩展 JSON 无效">{vendorJsonValidation.error}</InlineAlert>
            )}
            <Field label="请求预览" hint="Prompt 内容已脱敏；密钥和运行时字段不会出现在 payload。">
              <textarea readOnly value={buildDraftRequestPreview()} className="field min-h-[190px] font-mono text-xs" />
            </Field>
          </div>
        )}
      </div>

      <div className="sticky bottom-0 z-10 flex flex-wrap items-center justify-between gap-3 border-t border-slate-200/70 bg-white/82 pt-4 backdrop-blur">
        <div className="text-xs uppercase tracking-[0.16em] text-slate-400">
          {lastSavedAt ? `Saved ${formatRelativeTime(lastSavedAt)}` : 'Not saved yet'}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            className="btn-secondary"
            onClick={() => {
              applySavedSkillState(skill);
              setSaveFeedback(null);
            }}
          >
            <Undo size={14} />
            <span>重置为已保存</span>
          </button>
          <button type="button" className="btn-secondary" onClick={handleUseDraftForNextRun} disabled={draftModelMismatch || !draftModel.trim() || !draftProviderId}>
            <Bot size={14} />
            <span>仅用于本次运行</span>
          </button>
          <button type="button" className="btn-secondary" onClick={() => setConfigDrawerOpen(false)}>
            <span>取消</span>
          </button>
          <button
            type="button"
            onClick={() => saveSkillMutation.mutate()}
            disabled={saveSkillMutation.isPending || draftModelMismatch || !draftModel.trim() || !draftProviderId || Boolean(vendorJsonValidation.error)}
            className="btn-primary"
          >
            {saveSkillMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            <span>{saveSkillMutation.isPending ? '保存中…' : '保存默认配置'}</span>
          </button>
        </div>
      </div>
    </div>
  );

  const summaryPanelContent = (
    <div className="space-y-4">
      {saveFeedback && (
        <InlineAlert tone={saveFeedback.tone} title={saveFeedback.title}>
          {saveFeedback.message}
        </InlineAlert>
      )}
      {useDraftForNextRun && (
        <InlineAlert tone="success" title="下一次运行使用草稿">
          发送后会自动回到已保存默认配置。
        </InlineAlert>
      )}
      <div className="surface-soft space-y-3 p-4">
        <div className="flex items-center gap-2 text-blue-600">
          <Settings size={16} />
          <p className="metric-label">Skill</p>
        </div>
        <p className="text-lg font-semibold text-slate-900">{skill.name}</p>
        <p className="text-sm text-slate-500">{isConfigDirty ? '存在未保存草稿' : '已保存配置'}</p>
      </div>
      <div className="grid gap-3">
        <div className="surface-soft p-4">
          <div className="flex items-center gap-2 text-slate-500"><Gauge size={15} /><span className="metric-label">Provider / Model</span></div>
          <p className="mt-2 break-words text-sm font-medium text-slate-900">{savedRunProvider?.name || '后端系统默认'}</p>
          <p className="mt-1 break-words text-sm text-slate-500">{savedConfigModel || '未解析模型'}</p>
        </div>
        <div className="surface-soft p-4">
          <div className="flex items-center gap-2 text-slate-500"><Database size={15} /><span className="metric-label">Knowledge Base</span></div>
          <p className="mt-2 break-words text-sm font-medium text-slate-900">{boundKnowledgeBase?.name || (skillDocuments.length ? `旧版文档 ${skillDocuments.length} 份` : '未绑定')}</p>
        </div>
        <div className="surface-soft p-4">
          <div className="flex items-center gap-2 text-slate-500"><Brain size={15} /><span className="metric-label">Generation</span></div>
          <p className="mt-2 text-sm text-slate-700">{savedGenerationSummary}</p>
          {isConfigDirty && <p className="mt-1 text-xs text-amber-600">草稿：{generationSummary}</p>}
        </div>
        <div className="surface-soft p-4">
          <div className="flex items-center gap-2 text-slate-500"><Timer size={15} /><span className="metric-label">最近运行</span></div>
          <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
            <p><span className="text-slate-500">总耗时</span><br /><span className="font-semibold text-slate-900">{formatMillisecondsAsSeconds(displayRun?.metrics.total_ms)}</span></p>
            <p><span className="text-slate-500">检索</span><br /><span className="font-semibold text-slate-900">{formatMillisecondsAsSeconds(displayRun?.metrics.retrieve_ms)}</span></p>
            <p><span className="text-slate-500">首 token</span><br /><span className="font-semibold text-slate-900">{formatMillisecondsAsSeconds(displayRun?.metrics.ttft_ms)}</span></p>
            <p><span className="text-slate-500">引用</span><br /><span className="font-semibold text-slate-900">{displayRun?.citations.length ?? 0}</span></p>
          </div>
        </div>
      </div>
      <div className="grid gap-2">
        <button type="button" className="btn-primary justify-center" onClick={() => setConfigDrawerOpen(true)}>
          <SlidersHorizontal size={16} />
          <span>配置 Skill</span>
        </button>
        <button type="button" className="btn-secondary justify-center" onClick={() => setRuntimeDrawerOpen(true)}>
          <Gauge size={16} />
          <span>运行详情</span>
        </button>
      </div>
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
                ? setConfigDrawerOpen(true)
                : updateLayoutState({ inspectorOpen: !layoutState.inspectorOpen })
            )}
          >
            {isCompactLayout || !layoutState.inspectorOpen ? <PanelRightOpen size={16} /> : <PanelRightClose size={16} />}
            <span>配置</span>
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
                      {isConfigDirty && (
                        <button
                          type="button"
                          className="btn-secondary"
                          onClick={() => setUseDraftForNextRun(true)}
                          disabled={!question.trim() || isStreaming || draftModelMismatch}
                        >
                          <Bot size={16} />
                          <span>本次草稿</span>
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
                        <span>{useDraftForNextRun ? '发送（本次草稿）' : '发送'}</span>
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
              title="配置摘要"
              subtitle="完整配置在抽屉中编辑，运行详情单独查看。"
            >
              {summaryPanelContent}
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
                  <p className="text-xs font-medium text-slate-500">配置摘要</p>
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
        open={configDrawerOpen}
        onClose={() => setConfigDrawerOpen(false)}
        side="right"
        widthClassName="w-[920px] max-w-[calc(100vw-3rem)]"
        title="配置 Skill"
        description="保存默认配置，或把当前草稿仅用于下一次运行。"
      >
        {skillConfigDrawerContent}
      </ExpertDrawer>

      <ExpertDrawer
        open={runtimeDrawerOpen}
        onClose={() => setRuntimeDrawerOpen(false)}
        side="right"
        widthClassName="w-[760px] max-w-[calc(100vw-3rem)]"
        title="运行详情"
        description="检索、生成和 Provider 首 token 指标分开查看。"
      >
        {runtimeTabContent}
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
