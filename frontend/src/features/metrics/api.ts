import { apiClient } from '../../lib/api/client';
import type { MetricsOverview, ParseJob } from '../../types';

export const metricsApi = {
  overview: async (): Promise<MetricsOverview> => {
    const { data } = await apiClient.get<MetricsOverview>('/metrics/overview');
    return data;
  },
};

export const jobsApi = {
  list: async (document_id?: string): Promise<ParseJob[]> => {
    const { data } = await apiClient.get<ParseJob[]>('/jobs', { params: { document_id } });
    return data;
  },
  get: async (id: string): Promise<ParseJob> => {
    const { data } = await apiClient.get<ParseJob>(`/jobs/${id}`);
    return data;
  },
};
