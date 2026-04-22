import { apiClient, resolveApiUrl } from '../../lib/api/client';
import type { RunObservationEvent, RunObservationSnapshot } from '../../types';

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

export const runtimeObservationsApi = {
  getSnapshot: async (runKind: 'chat' | 'compliance', runId: string): Promise<RunObservationSnapshot> => {
    const { data } = await apiClient.get<RunObservationSnapshot>(`/runtime-observations/${runKind}/${runId}`);
    return data;
  },
  stream: async (
    runKind: 'chat' | 'compliance',
    runId: string,
    handlers: {
      signal?: AbortSignal;
      onObservation?: (event: RunObservationEvent) => void;
    } = {},
  ): Promise<void> => {
    const response = await fetch(resolveApiUrl(`/runtime-observations/${runKind}/${runId}/stream`), {
      method: 'GET',
      headers: {
        Accept: 'text/event-stream',
        ...(localStorage.getItem('token') ? { Authorization: `Bearer ${localStorage.getItem('token')}` } : {}),
      },
      signal: handlers.signal,
    });
    if (!response.ok || !response.body) {
      throw new Error('Failed to open runtime observation stream');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

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
          if (parsed.event !== 'observation') continue;
          handlers.onObservation?.(JSON.parse(parsed.data) as RunObservationEvent);
        }
      }
    } finally {
      reader.releaseLock();
    }
  },
};
