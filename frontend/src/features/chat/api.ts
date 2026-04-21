import { ApiClientError, parseApiErrorResponse, resolveApiUrl, apiClient } from '../../lib/api/client';
import type { ApiErrorPayload, ChatMessage, ChatRun, ChatRunExecutionContext, ChatSession, RunStatus, StandardRunStatus } from '../../types';

export interface AskRequest {
  question: string;
  document_id: string;
  version_id?: string;
  model?: string;
  request_config?: Record<string, unknown>;
  provider_id?: string;
  session_id?: string;
  retrieval_config?: Record<string, unknown>;
  generation_config?: Record<string, unknown>;
}

export interface SkillRunRequest {
  question: string;
  document_id?: string;
  provider_id?: string;
  model?: string;
  system_prompt?: string;
  session_id?: string;
  auto_create_session?: boolean;
  session_title?: string;
  stream?: boolean;
  conversation_config?: Record<string, unknown>;
  retrieval_config?: Record<string, unknown>;
  generation_config?: Record<string, unknown>;
}

type SkillRunExecutionContext = ChatRunExecutionContext;
type RawChatRun = Omit<ChatRun, 'status' | 'raw_status'> & { status: string };
type SkillStreamErrorPayload = Partial<ApiErrorPayload> & { detail?: string };

export interface SkillRunStreamHandlers {
  signal?: AbortSignal;
  onRunStarted?: (payload: { run_id: string; session_id: string | null; created_at: string }) => void;
  onStatus?: (payload: { status: RunStatus }) => void;
  onContext?: (payload: { execution_context: SkillRunExecutionContext }) => void;
  onAnswerDelta?: (payload: { delta: string; seq?: number }) => void;
  onCompleted?: (payload: ChatRun) => void;
  onError?: (payload: SkillStreamErrorPayload) => void;
}

const normalizeRunStatus = (status: string): StandardRunStatus => {
  switch (status) {
    case 'accepted':
    case 'queued':
      return 'queued';
    case 'retrieving':
    case 'answering':
    case 'running':
      return 'running';
    case 'completed':
      return 'completed';
    case 'cancelled':
      return 'cancelled';
    case 'failed':
    default:
      return 'failed';
  }
};

const normalizeChatRun = (run: RawChatRun): ChatRun => {
  const rawStatus = typeof run.status === 'string' ? (run.status as RunStatus) : null;
  return {
    ...run,
    status: normalizeRunStatus(run.status),
    raw_status: rawStatus,
  };
};

const parseSseEvent = (chunk: string): { event: string; data: string } | null => {
  const normalized = chunk.replace(/\r\n/g, '\n').trim();
  if (!normalized) return null;

  let event = 'message';
  const dataLines: string[] = [];

  for (const line of normalized.split('\n')) {
    if (line.startsWith('event:')) {
      event = line.slice(6).trim();
      continue;
    }
    if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trimStart());
    }
  }

  return { event, data: dataLines.join('\n') };
};

const buildSkillStreamError = (errorPayload: SkillStreamErrorPayload): ApiClientError =>
  new ApiClientError({
    code: errorPayload.code || 'INTERNAL_ERROR',
    message: errorPayload.detail || errorPayload.message || 'Skill stream failed',
    request_id: errorPayload.request_id ?? null,
    ...(errorPayload.details !== undefined ? { details: errorPayload.details } : {}),
  });

const sleep = (ms: number) => new Promise((resolve) => {
  window.setTimeout(resolve, ms);
});

const recoverSkillRunAfterStreamExit = async (
  runId: string,
  handlers: SkillRunStreamHandlers,
): Promise<ChatRun | null> => {
  for (let attempt = 0; attempt < 5; attempt += 1) {
    try {
      const { data } = await apiClient.get<RawChatRun>(`/runs/${runId}`);
      const run = normalizeChatRun(data);
      if (run.status === 'completed') {
        handlers.onStatus?.({ status: 'completed' });
        handlers.onCompleted?.(run);
        return run;
      }
      if (run.status === 'failed') {
        handlers.onStatus?.({ status: 'failed' });
        const errorPayload: SkillStreamErrorPayload = {
          code: 'skill_stream_failed',
          message: run.last_error || 'Skill run failed',
          detail: run.last_error || 'Skill run failed',
        };
        handlers.onError?.(errorPayload);
        throw buildSkillStreamError(errorPayload);
      }
      if (run.status === 'cancelled') {
        handlers.onStatus?.({ status: 'cancelled' });
        const errorPayload: SkillStreamErrorPayload = {
          code: 'skill_stream_cancelled',
          message: run.cancel_reason || run.last_error || 'Skill run was cancelled',
          detail: run.cancel_reason || run.last_error || 'Skill run was cancelled',
        };
        handlers.onError?.(errorPayload);
        throw buildSkillStreamError(errorPayload);
      }
    } catch (error) {
      if (error instanceof ApiClientError) {
        throw error;
      }
    }

    if (attempt < 4) {
      await sleep(150);
    }
  }

  return null;
};

export const chatApi = {
  ask: async (payload: AskRequest): Promise<ChatRun> => {
    const { data } = await apiClient.post<RawChatRun>('/chat/ask', payload);
    return normalizeChatRun(data);
  },
  runSkill: async (skill_id: string, payload: SkillRunRequest): Promise<ChatRun> => {
    const { data } = await apiClient.post<RawChatRun>(`/chat/skills/${skill_id}/run`, payload);
    return normalizeChatRun(data);
  },
  streamSkillRun: async (skill_id: string, payload: SkillRunRequest, handlers: SkillRunStreamHandlers = {}): Promise<ChatRun> => {
    const response = await fetch(resolveApiUrl(`/chat/skills/${skill_id}/run`), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        ...(localStorage.getItem('token') ? { Authorization: `Bearer ${localStorage.getItem('token')}` } : {}),
      },
      body: JSON.stringify({ ...payload, stream: true }),
      signal: handlers.signal,
    });

    if (!response.ok) {
      throw await parseApiErrorResponse(response);
    }

    if (!response.body) {
      throw new Error('Streaming response body is not available');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let completedRun: ChatRun | null = null;
    let startedRunId: string | null = null;

    const processRawEvent = (rawEvent: string) => {
      const parsed = parseSseEvent(rawEvent);
      if (!parsed?.data) return;

      const payloadData = JSON.parse(parsed.data) as unknown;

      if (parsed.event === 'run_started') {
        const runStartedPayload = payloadData as { run_id: string; session_id: string | null; created_at: string };
        startedRunId = runStartedPayload.run_id;
        handlers.onRunStarted?.(runStartedPayload);
        return;
      }
      if (parsed.event === 'status') {
        const statusPayload = payloadData as { status?: string };
        handlers.onStatus?.({ status: normalizeRunStatus(statusPayload.status || 'failed') });
        return;
      }
      if (parsed.event === 'context') {
        handlers.onContext?.(payloadData as { execution_context: SkillRunExecutionContext });
        return;
      }
      if (parsed.event === 'answer_delta') {
        handlers.onAnswerDelta?.(payloadData as { delta: string; seq?: number });
        return;
      }
      if (parsed.event === 'run_completed') {
        completedRun = normalizeChatRun(payloadData as RawChatRun);
        handlers.onCompleted?.(completedRun);
        return;
      }
      if (parsed.event === 'error') {
        const errorPayload = payloadData as SkillStreamErrorPayload;
        handlers.onError?.(errorPayload);
        throw buildSkillStreamError(errorPayload);
      }
    };

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split('\n\n');
        buffer = events.pop() || '';

        for (const rawEvent of events) {
          processRawEvent(rawEvent);
        }
      }

      if (buffer.trim()) {
        processRawEvent(buffer);
      }

      if (!completedRun && startedRunId) {
        const recoveredRun = await recoverSkillRunAfterStreamExit(startedRunId, handlers);
        if (recoveredRun) {
          return recoveredRun;
        }
      }

      if (!completedRun) {
        throw new Error('Stream ended before run_completed was received');
      }

      return completedRun;
    } finally {
      reader.releaseLock();
    }
  },
  listRuns: async (params?: { skill_id?: string; document_id?: string; session_id?: string }): Promise<ChatRun[]> => {
    const { data } = await apiClient.get<RawChatRun[]>('/runs', { params });
    return data.map(normalizeChatRun);
  },
  getRun: async (id: string): Promise<ChatRun> => {
    const { data } = await apiClient.get<RawChatRun>(`/runs/${id}`);
    return normalizeChatRun(data);
  },
  cancelRun: async (id: string): Promise<ChatRun> => {
    const { data } = await apiClient.post<RawChatRun>(`/runs/${id}/cancel`);
    return normalizeChatRun(data);
  },
  listSessions: async (params?: { skill_id?: string }): Promise<ChatSession[]> => {
    const { data } = await apiClient.get<ChatSession[]>('/chat/sessions', { params });
    return data;
  },
  createSession: async (payload: { title: string; skill_id?: string }): Promise<ChatSession> => {
    const { data } = await apiClient.post<ChatSession>('/chat/sessions', payload);
    return data;
  },
  getSessionMessages: async (sessionId: string): Promise<ChatMessage[]> => {
    const { data } = await apiClient.get<ChatMessage[]>(`/chat/sessions/${sessionId}/messages`);
    return data;
  },
  listSkillSessions: async (skillId: string): Promise<ChatSession[]> => {
    const { data } = await apiClient.get<ChatSession[]>(`/chat/skills/${skillId}/sessions`);
    return data;
  },
  createSkillSession: async (skillId: string, payload: { title: string }): Promise<ChatSession> => {
    const { data } = await apiClient.post<ChatSession>(`/chat/skills/${skillId}/sessions`, payload);
    return data;
  },
  getSkillSessionMessages: async (skillId: string, sessionId: string): Promise<ChatMessage[]> => {
    const { data } = await apiClient.get<ChatMessage[]>(`/chat/skills/${skillId}/sessions/${sessionId}/messages`);
    return data;
  },
};
