import { apiClient } from '../../lib/api/client';
import type { ChatMessage, ChatRun, ChatSession, RunStatus } from '../../types';

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
  session_id?: string;
  auto_create_session?: boolean;
  session_title?: string;
  stream?: boolean;
  conversation_config?: Record<string, unknown>;
  retrieval_config?: Record<string, unknown>;
  generation_config?: Record<string, unknown>;
}

type SkillRunExecutionContext = ChatRun['execution_context'];

export interface SkillRunStreamHandlers {
  signal?: AbortSignal;
  onRunStarted?: (payload: { run_id: string; session_id: string | null; created_at: string }) => void;
  onStatus?: (payload: { status: RunStatus }) => void;
  onContext?: (payload: { execution_context: SkillRunExecutionContext }) => void;
  onAnswerDelta?: (payload: { delta: string; seq?: number }) => void;
  onCompleted?: (payload: ChatRun) => void;
  onError?: (payload: { code?: string; message?: string; detail?: string }) => void;
}

const redirectToLogin = () => {
  localStorage.removeItem('token');
  localStorage.removeItem('user');
  const basePath = (import.meta.env.BASE_URL || '/').replace(/\/$/, '') || '/';
  const loginPath = `${basePath === '/' ? '' : basePath}/login`;
  if (typeof window !== 'undefined' && window.location.pathname !== loginPath) {
    window.location.href = loginPath;
  }
};

const parseHttpError = async (response: Response) => {
  if (response.status === 401) {
    redirectToLogin();
    throw new Error('Unauthorized');
  }

  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    const data = (await response.json()) as { detail?: unknown };
    if (typeof data.detail === 'string') {
      throw new Error(data.detail);
    }
    if (Array.isArray(data.detail)) {
      const messages = data.detail
        .map((item) => {
          if (typeof item === 'string') return item;
          if (item && typeof item === 'object') {
            const maybeItem = item as { loc?: unknown; msg?: unknown };
            const location = Array.isArray(maybeItem.loc) ? maybeItem.loc.join('.') : null;
            const message = typeof maybeItem.msg === 'string' ? maybeItem.msg : null;
            if (location && message) return `${location}: ${message}`;
            return message;
          }
          return null;
        })
        .filter((value): value is string => Boolean(value));
      if (messages.length > 0) {
        throw new Error(messages.join('; '));
      }
    }
  }

  const text = await response.text();
  throw new Error(text || `Request failed with status ${response.status}`);
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

export const chatApi = {
  ask: async (payload: AskRequest): Promise<ChatRun> => {
    const { data } = await apiClient.post<ChatRun>('/chat/ask', payload);
    return data;
  },
  runSkill: async (skill_id: string, payload: SkillRunRequest): Promise<ChatRun> => {
    const { data } = await apiClient.post<ChatRun>(`/chat/skills/${skill_id}/run`, payload);
    return data;
  },
  streamSkillRun: async (skill_id: string, payload: SkillRunRequest, handlers: SkillRunStreamHandlers = {}): Promise<ChatRun> => {
    const response = await fetch(`${apiClient.defaults.baseURL}/chat/skills/${skill_id}/run`, {
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
      await parseHttpError(response);
    }

    if (!response.body) {
      throw new Error('Streaming response body is not available');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let completedRun: ChatRun | null = null;

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split('\n\n');
        buffer = events.pop() || '';

        for (const rawEvent of events) {
          const parsed = parseSseEvent(rawEvent);
          if (!parsed?.data) continue;

          const payloadData = JSON.parse(parsed.data) as unknown;

          if (parsed.event === 'run_started') {
            handlers.onRunStarted?.(payloadData as { run_id: string; session_id: string | null; created_at: string });
            continue;
          }
          if (parsed.event === 'status') {
            handlers.onStatus?.(payloadData as { status: RunStatus });
            continue;
          }
          if (parsed.event === 'context') {
            handlers.onContext?.(payloadData as { execution_context: SkillRunExecutionContext });
            continue;
          }
          if (parsed.event === 'answer_delta') {
            handlers.onAnswerDelta?.(payloadData as { delta: string; seq?: number });
            continue;
          }
          if (parsed.event === 'run_completed') {
            completedRun = payloadData as ChatRun;
            handlers.onCompleted?.(completedRun);
            continue;
          }
          if (parsed.event === 'error') {
            const errorPayload = payloadData as { code?: string; message?: string; detail?: string };
            handlers.onError?.(errorPayload);
            throw new Error(errorPayload.detail || errorPayload.message || 'Skill stream failed');
          }
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
    const { data } = await apiClient.get<ChatRun[]>('/runs', { params });
    return data;
  },
  getRun: async (id: string): Promise<ChatRun> => {
    const { data } = await apiClient.get<ChatRun>(`/runs/${id}`);
    return data;
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
