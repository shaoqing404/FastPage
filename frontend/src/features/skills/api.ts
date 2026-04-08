import { apiClient } from '../../lib/api/client';
import type { ChatSkill } from '../../types';

export const skillsApi = {
  list: async (): Promise<ChatSkill[]> => {
    const { data } = await apiClient.get<ChatSkill[]>('/skills');
    return data;
  },
  get: async (id: string): Promise<ChatSkill> => {
    const { data } = await apiClient.get<ChatSkill>(`/skills/${id}`);
    return data;
  },
  create: async (skill: Partial<ChatSkill>): Promise<ChatSkill> => {
    const { data } = await apiClient.post<ChatSkill>('/skills', skill);
    return data;
  },
  update: async (id: string, skill: Partial<ChatSkill>): Promise<ChatSkill> => {
    const { data } = await apiClient.patch<ChatSkill>(`/skills/${id}`, skill);
    return data;
  },
  delete: async (id: string): Promise<void> => {
    await apiClient.delete(`/skills/${id}`);
  },
};
