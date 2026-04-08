import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Bot, Plus, RefreshCcw, Send, Square, TextQuote, User } from 'lucide-react';
import { Link, useParams, useSearchParams } from 'react-router-dom';

import { AnswerContent } from '../components/ui/AnswerContent';
import { Field, GlassPanel, InlineAlert, KeyMetric, SectionToolbar, StatusBadge } from '../components/ui/workbench';
import { chatApi } from '../features/chat/api';
import { documentsApi } from '../features/documents/api';
import { providersApi } from '../features/providers/api';
import { skillsApi } from '../features/skills/api';
import type { ChatMessage, ChatRun, ChatSession, Document, RunStatus } from '../types';
import { formatDateTime, formatPageRange, getErrorMessage, resolveProviderById } from '../lib/utils';

type HistoryItem = {
  role: 'user' | 'assistant';
  content: string;
  run?: ChatRun;
  createdAt?: string | null;
};

const DEFAULT_CONVERSATION_CONFIG = {
  query_rewrite_with_history: true,
  include_history: true,
  include_assistant_messages: true,
  history_turn_limit: 4,
  history_token_budget: 1800,
};

export const SkillChatPage: React.FC = () => {
  const { skillId = '' } = useParams();
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
  const [streamingExecutionContext, setStreamingExecutionContext] = useState<ChatRun['execution_context'] | null>(null);
  const [completedStreamRun, setCompletedStreamRun] = useState<ChatRun | null>(null);
  const [selectedDocId, setSelectedDocId] = useState('');
  const [selectedProviderId, setSelectedProviderId] = useState('');
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
  const [chatError, setChatError] = useState('');

  const { data: skills = [] } = useQuery({ queryKey: ['skills'], queryFn: skillsApi.list });
  const { data: documents = [] } = useQuery({ queryKey: ['documents'], queryFn: documentsApi.list });
  const { data: providers = [] } = useQuery({ queryKey: ['providers'], queryFn: providersApi.list });
  const { data: sessions = [] } = useQuery({
    queryKey: ['skill-chat-sessions', skillId],
    queryFn: () => chatApi.listSkillSessions(skillId),
    enabled: Boolean(skillId),
  });

  const skill = skills.find((item) => item.id === skillId) || null;
  const skillDocumentIds = skill?.document_ids || [];
  const skillDocuments = documents.filter((document) => skillDocumentIds.includes(document.id));
  const effectiveDocumentId = selectedDocId && skillDocumentIds.includes(selectedDocId) ? selectedDocId : skillDocumentIds[0] || '';
  const selectedDocument = skillDocuments.find((document) => document.id === effectiveDocumentId) || null;
  const skillProvider = skill?.provider_id ? resolveProviderById(skill.provider_id, providers) : null;
  const requestProvider = !skill?.provider_id ? resolveProviderById(selectedProviderId || null, providers) : null;
  const tenantDefaultProvider = providers.find((provider) => provider.is_default) || null;
  const resolvedProvider = skillProvider || requestProvider || tenantDefaultProvider || null;
  const resolvedModel = skill?.model || resolvedProvider?.default_model || '';
  const skillConversationDefaults = {
    ...DEFAULT_CONVERSATION_CONFIG,
    ...((skill?.conversation_config || {}) as Record<string, unknown>),
  };
  const skillRetrievalDefaults = (skill?.retrieval_config || {}) as Record<string, unknown>;
  const skillGenerationDefaults = (skill?.generation_config || {}) as Record<string, unknown>;
  const effectiveQueryRewriteWithHistory = queryRewriteWithHistory ?? (skillConversationDefaults.query_rewrite_with_history !== false);
  const effectiveIncludeHistory = includeHistory ?? (skillConversationDefaults.include_history !== false);
  const effectiveIncludeAssistantMessages = includeAssistantMessages ?? (skillConversationDefaults.include_assistant_messages !== false);
  const effectiveHistoryTurnLimit = historyTurnLimit || String(skillConversationDefaults.history_turn_limit ?? DEFAULT_CONVERSATION_CONFIG.history_turn_limit);
  const effectiveHistoryTokenBudget = historyTokenBudget || String(skillConversationDefaults.history_token_budget ?? DEFAULT_CONVERSATION_CONFIG.history_token_budget);
  const effectiveTopK = topK || String(skillRetrievalDefaults.top_k ?? 5);
  const effectiveSelectionMode = selectionMode || (typeof skillRetrievalDefaults.selection_mode === 'string' ? skillRetrievalDefaults.selection_mode : 'outline_llm');
  const effectiveMaxContextPages = maxContextPages || (skillRetrievalDefaults.max_context_pages ? String(skillRetrievalDefaults.max_context_pages) : '');
  const effectiveMaxContextTokens = maxContextTokens || (skillRetrievalDefaults.max_context_tokens ? String(skillRetrievalDefaults.max_context_tokens) : '');
  const effectiveTemperature = temperature || (skillGenerationDefaults.temperature !== undefined && skillGenerationDefaults.temperature !== null ? String(skillGenerationDefaults.temperature) : '0');

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
      if (!existing.latestRun) existing.latestRun = run;
    }
    return Array.from(summaryMap.values());
  }, [allSkillRuns, sessions]);

  const effectiveSessionId = searchParams.get('session') || sessionSummaries[0]?.session.id || '';
  const selectedSession = sessionSummaries.find((entry) => entry.session.id === effectiveSessionId)?.session || null;
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

  useEffect(() => {
    if (!sessionSummaries.length) return;
    if (effectiveSessionId && sessionSummaries.some((entry) => entry.session.id === effectiveSessionId)) return;
    setSearchParams((params) => {
      const next = new URLSearchParams(params);
      next.set('session', sessionSummaries[0].session.id);
      return next;
    }, { replace: true });
  }, [effectiveSessionId, sessionSummaries, setSearchParams]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [history]);

  useEffect(
    () => () => {
      streamAbortRef.current?.abort();
    },
    []
  );

  const createSessionMutation = useMutation({
    mutationFn: (title: string) => chatApi.createSkillSession(skillId, { title }),
    onSuccess: (session) => {
      setNewSessionTitle('');
      setSearchParams((params) => {
        const next = new URLSearchParams(params);
        next.set('session', session.id);
        return next;
      });
      queryClient.invalidateQueries({ queryKey: ['skill-chat-sessions', skillId] });
    },
    onError: (error: unknown) => setChatError(getErrorMessage(error, 'Failed to create session')),
  });

  const runSkillMutation = useMutation({
    mutationFn: async (q: string) => {
      if (!skill) throw new Error('Skill not found');
      if (!effectiveDocumentId) throw new Error('This skill has no linked document');
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

      return chatApi.streamSkillRun(skill.id, {
        question: q,
        document_id: effectiveDocumentId,
        provider_id: !skill.provider_id ? selectedProviderId || undefined : undefined,
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
      }, {
        signal: controller.signal,
        onRunStarted: ({ created_at }) => {
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
      });
    },
    onMutate: (q) => {
      setLastQuestion(q);
      setPendingQuestion(q);
      setIsStreaming(true);
      setChatError('');
      setCompletedStreamRun(null);
      setStreamingAnswer('');
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
      if (run.session_id && run.session_id !== effectiveSessionId) {
        setSearchParams((params) => {
          const next = new URLSearchParams(params);
          next.set('session', run.session_id!);
          return next;
        }, { replace: true });
      }
      setNewSessionTitle('');
      setStreamingAnswer('');
      setStreamingRunCreatedAt(null);
      setStreamingStatus(null);
      setStreamingExecutionContext(run.execution_context || null);
      queryClient.invalidateQueries({ queryKey: ['skill-runs-all-sessions', skillId] });
      queryClient.invalidateQueries({ queryKey: ['skill-session-runs', skillId, effectiveSessionId] });
      queryClient.invalidateQueries({ queryKey: ['skill-session-messages', skillId, effectiveSessionId] });
      queryClient.invalidateQueries({ queryKey: ['skill-chat-sessions', skillId] });
    },
    onError: (error: unknown, q: string) => {
      streamAbortRef.current = null;
      setPendingQuestion(null);
      setIsStreaming(false);
      setQuestion(q);
      setStreamingAnswer('');
      setStreamingRunCreatedAt(null);
      setStreamingStatus(null);
      setStreamingExecutionContext(null);
      setChatError(error instanceof DOMException && error.name === 'AbortError' ? 'Streaming cancelled. The backend marks the run as failed if execution had already started.' : getErrorMessage(error, 'Skill chat failed'));
      queryClient.invalidateQueries({ queryKey: ['skill-runs-all-sessions', skillId] });
      queryClient.invalidateQueries({ queryKey: ['skill-session-runs', skillId, effectiveSessionId] });
      queryClient.invalidateQueries({ queryKey: ['skill-session-messages', skillId, effectiveSessionId] });
      queryClient.invalidateQueries({ queryKey: ['skill-chat-sessions', skillId] });
    },
  });

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!question.trim() || isStreaming) return;
    runSkillMutation.mutate(question.trim());
  };

  if (!skill) {
    return (
      <div className="space-y-8">
        <SectionToolbar title="Skill chat" description="This skill route could not be resolved." />
        <GlassPanel title="Missing skill" subtitle="The requested skill was not found.">
          <div className="empty-state min-h-[320px]">
            <p className="text-base font-medium text-slate-900">Skill not found</p>
            <Link to="/chat" className="btn-primary">
              <ArrowLeft size={16} />
              <span>Back to skills</span>
            </Link>
          </div>
        </GlassPanel>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <SectionToolbar
        title={skill.name}
        description="This route is now skill-specific. Left side is session history, center is the conversation, right side is settings and runtime data."
        actions={
          <Link to="/chat" className="btn-secondary">
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
                <input value={newSessionTitle} onChange={(event) => setNewSessionTitle(event.target.value)} className="field flex-1" placeholder="Create skill session" />
                <button type="button" className="btn-secondary" onClick={() => createSessionMutation.mutate(newSessionTitle.trim())} disabled={createSessionMutation.isPending}>
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

        <GlassPanel title={`Skill chat · ${skill.name}`} subtitle={selectedSession?.title || 'No session selected'}>
          <div className="space-y-4">
            {chatError && (
              <InlineAlert
                tone="danger"
                title="Skill chat failed"
                action={
                  <button type="button" className="btn-secondary" disabled={!lastQuestion || isStreaming} onClick={() => lastQuestion && runSkillMutation.mutate(lastQuestion)}>
                    <RefreshCcw size={16} />
                    <span>Retry</span>
                  </button>
                }
              >
                <div className="space-y-1">
                  <p>{chatError}</p>
                  <p className="text-sm text-slate-500">Provider: {activeExecutionContext.provider?.name || resolvedProvider?.name || 'Backend system default'} · Model: {activeExecutionContext.model?.resolved_model || resolvedModel || 'N/A'}</p>
                </div>
              </InlineAlert>
            )}

            <div ref={scrollRef} className="scroll-area max-h-[620px] space-y-4 overflow-auto pr-1">
              {history.length === 0 ? (
                <div className="empty-state min-h-[420px]">
                  <TextQuote size={22} className="text-blue-600" />
                  <p className="text-base font-medium text-slate-900">Start chatting with this skill</p>
                  <p className="text-sm text-slate-500">Choose or create a skill session on the left, then ask a question in the center.</p>
                </div>
              ) : (
                history.map((message, index) => (
                  <div key={`${message.role}-${index}`} className={`rounded-[28px] border px-5 py-4 ${message.role === 'assistant' ? 'border-white/85 bg-white/82' : 'border-white/70 bg-white/56'}`}>
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
                          ? 'Retrieving context…'
                          : streamingStatus === 'answering'
                            ? 'Streaming answer…'
                            : 'Generating answer…'}
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

            <form onSubmit={handleSubmit} className="rounded-[28px] border border-white/80 bg-white/72 p-4">
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
                    onClick={() => streamAbortRef.current?.abort()}
                  >
                    <Square size={16} />
                    <span>Stop</span>
                  </button>
                ) : (
                  <button type="submit" className="btn-primary self-end" disabled={!question.trim() || isStreaming}>
                    <Send size={16} />
                    <span>Send</span>
                  </button>
                )}
              </div>
            </form>
          </div>
        </GlassPanel>

        <div className="space-y-6">
          <GlassPanel title="Settings" subtitle="Skill-scoped execution settings and document choice.">
            <div className="space-y-4">
              <Field label="Document">
                <select value={effectiveDocumentId} onChange={(event) => setSelectedDocId(event.target.value)} className="field">
                  {skillDocuments.map((document: Document) => (
                    <option key={document.id} value={document.id}>
                      {document.display_name}
                    </option>
                  ))}
                </select>
              </Field>

              <Field label="Provider override" hint={skill.provider_id ? 'This skill is provider-bound. Request override is ignored by the backend.' : 'Optional override when the skill itself does not bind a provider.'}>
                <select value={skill.provider_id || selectedProviderId} onChange={(event) => setSelectedProviderId(event.target.value)} className="field" disabled={Boolean(skill.provider_id)}>
                  <option value="">Use resolved provider</option>
                  {providers.map((provider) => (
                    <option key={provider.id} value={provider.id}>
                      {provider.name}
                    </option>
                  ))}
                </select>
              </Field>

              <div className="rounded-[24px] border border-white/75 bg-white/58 p-4">
                <div className="mb-4">
                  <p className="text-sm font-medium text-slate-900">Conversation override</p>
                  <p className="mt-1 text-sm text-slate-500">These values start from the skill template and only affect this run.</p>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <label className="flex items-center gap-2 text-sm text-slate-700">
                    <input type="checkbox" checked={effectiveQueryRewriteWithHistory} onChange={(event) => setQueryRewriteWithHistory(event.target.checked)} />
                    <span>Rewrite retrieval query with history</span>
                  </label>
                  <label className="flex items-center gap-2 text-sm text-slate-700">
                    <input type="checkbox" checked={effectiveIncludeHistory} onChange={(event) => setIncludeHistory(event.target.checked)} />
                    <span>Include history in generation</span>
                  </label>
                  <label className="flex items-center gap-2 text-sm text-slate-700">
                    <input
                      type="checkbox"
                      checked={effectiveIncludeAssistantMessages}
                      onChange={(event) => setIncludeAssistantMessages(event.target.checked)}
                      disabled={!effectiveIncludeHistory}
                    />
                    <span>Include assistant messages</span>
                  </label>
                  <Field label="History turn limit">
                    <input type="number" min="1" value={effectiveHistoryTurnLimit} onChange={(event) => setHistoryTurnLimit(event.target.value)} className="field" />
                  </Field>
                  <Field label="History token budget">
                    <input type="number" min="1" value={effectiveHistoryTokenBudget} onChange={(event) => setHistoryTokenBudget(event.target.value)} className="field" />
                  </Field>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <Field label="Top K">
                  <input type="number" min="1" value={effectiveTopK} onChange={(event) => setTopK(event.target.value)} className="field" />
                </Field>
                <Field label="Selection mode">
                  <select value={effectiveSelectionMode} onChange={(event) => setSelectionMode(event.target.value)} className="field">
                    <option value="outline_llm">outline_llm</option>
                    <option value="lexical_fallback">lexical_fallback</option>
                  </select>
                </Field>
                <Field label="Max context pages">
                  <input type="number" min="1" value={effectiveMaxContextPages} onChange={(event) => setMaxContextPages(event.target.value)} className="field" placeholder="Optional" />
                </Field>
                <Field label="Max context tokens">
                  <input type="number" min="1" value={effectiveMaxContextTokens} onChange={(event) => setMaxContextTokens(event.target.value)} className="field" placeholder="Optional" />
                </Field>
              </div>

              <Field label="Temperature">
                <input type="number" min="0" step="0.1" value={effectiveTemperature} onChange={(event) => setTemperature(event.target.value)} className="field" />
              </Field>
            </div>
          </GlassPanel>

          <GlassPanel title="Runtime data" subtitle="Latest run telemetry, citations, and resolved execution details.">
            <div className="space-y-5">
              <div className="grid grid-cols-2 gap-3">
                <KeyMetric label="Session" value={selectedSession?.title || 'No session'} />
                <KeyMetric label="Model" value={activeExecutionContext.model?.resolved_model || resolvedModel || 'N/A'} />
                <KeyMetric label="Provider" value={activeExecutionContext.provider?.name || resolvedProvider?.name || 'Backend system default'} />
                <KeyMetric label="Citations" value={displayRun?.citations.length ?? 0} />
              </div>

              {selectedDocument && (
                <div className="surface-soft p-4">
                  <p className="metric-label">Target document</p>
                  <p className="mt-2 font-medium text-slate-900">{selectedDocument.display_name}</p>
                  <p className="mt-1 text-sm text-slate-500">{selectedDocument.status}</p>
                </div>
              )}

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
                      <p className="mt-2 font-medium text-slate-900">{activeStatus}</p>
                    </div>
                  )}

                  <div className="surface-soft p-4">
                    <p className="metric-label">Execution context</p>
                    <dl className="mt-3 space-y-2 text-sm text-slate-600">
                      <div className="flex items-start justify-between gap-4">
                        <dt>History messages</dt>
                        <dd>{activeExecutionContext.conversation?.history_messages_used ?? 0}</dd>
                      </div>
                      <div className="flex items-start justify-between gap-4">
                        <dt>History turns</dt>
                        <dd>{activeExecutionContext.conversation?.history_turns_used ?? 0}</dd>
                      </div>
                      <div className="flex items-start justify-between gap-4">
                        <dt>History token estimate</dt>
                        <dd>{activeExecutionContext.conversation?.history_token_estimate ?? 0}</dd>
                      </div>
                      <div className="flex items-start justify-between gap-4">
                        <dt>Retrieval query</dt>
                        <dd className="max-w-[60%] text-right break-all">{activeExecutionContext.retrieval?.query || 'N/A'}</dd>
                      </div>
                      <div className="flex items-start justify-between gap-4">
                        <dt>Rewrite applied</dt>
                        <dd>{activeExecutionContext.retrieval?.rewrite_applied ? 'Yes' : 'No'}</dd>
                      </div>
                      {activeExecutionContext.retrieval?.rewritten_query && (
                        <div className="flex items-start justify-between gap-4">
                          <dt>Rewritten query</dt>
                          <dd className="max-w-[60%] text-right break-all">{activeExecutionContext.retrieval.rewritten_query}</dd>
                        </div>
                      )}
                    </dl>
                  </div>

                  {isStreaming && (
                    <div className="surface-soft p-4">
                      <p className="metric-label">Streaming</p>
                      <p className="mt-2 text-sm text-slate-600">Answer deltas are rendering live. Final citations, selected sections, and metrics arrive with the `run_completed` event.</p>
                    </div>
                  )}

                  {displayRun && (
                    <div className="space-y-3">
                      <p className="metric-label">Citations</p>
                      {displayRun.citations.length > 0 ? (
                        <div className="space-y-2">
                          {displayRun.citations.map((citation, index) => (
                            <div key={`${citation.snippet_id || citation.node_id || index}`} className="surface-soft p-4">
                              <div className="flex items-center justify-between gap-3">
                                <div className="min-w-0">
                                  <p className="truncate font-medium text-slate-900">{citation.title || 'Untitled citation'}</p>
                                  <p className="text-sm text-slate-500">{citation.snippet_id || citation.node_id || 'citation'}</p>
                                </div>
                                <StatusBadge tone="accent">{formatPageRange(citation.page_start, citation.page_end)}</StatusBadge>
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="text-sm text-slate-500">No citations returned yet.</p>
                      )}
                    </div>
                  )}
                </>
              ) : (
                <div className="empty-state min-h-[220px]">
                  <TextQuote size={20} className="text-blue-600" />
                  <p className="text-base font-medium text-slate-900">No run data yet</p>
                  <p className="text-sm text-slate-500">Ask a question in this skill route to populate runtime metrics and citations.</p>
                </div>
              )}
            </div>
          </GlassPanel>
        </div>
      </div>
    </div>
  );
};
