import { apiClient } from '../../lib/api/client';
import type { Document, DocumentVersion, ParseJob } from '../../types';

export const documentsApi = {
  list: async (): Promise<Document[]> => {
    const { data } = await apiClient.get<Document[]>('/documents');
    return data;
  },
  get: async (id: string): Promise<Document> => {
    const { data } = await apiClient.get<Document>(`/documents/${id}`);
    return data;
  },
  upload: async (file: File, document_id?: string): Promise<{ document_id: string; version_id: string; status: string }> => {
    const formData = new FormData();
    formData.append('file', file);
    if (document_id) formData.append('document_id', document_id);
    const { data } = await apiClient.post('/documents/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return data;
  },
  listVersions: async (id: string): Promise<DocumentVersion[]> => {
    const { data } = await apiClient.get<DocumentVersion[]>(`/documents/${id}/versions`);
    return data;
  },
  parse: async (id: string, version_id?: string, model?: string): Promise<ParseJob> => {
    const { data } = await apiClient.post<ParseJob>(`/documents/${id}/parse`, { version_id, model });
    return data;
  },
  reparse: async (id: string, version_id?: string, model?: string): Promise<ParseJob> => {
    const { data } = await apiClient.post<ParseJob>(`/documents/${id}/reparse`, { version_id, model });
    return data;
  },
  restore: async (id: string, version_id: string): Promise<{ document_id: string; active_version_id: string }> => {
    const { data } = await apiClient.post(`/documents/${id}/versions/${version_id}/restore`);
    return data;
  },
  delete: async (id: string): Promise<void> => {
    await apiClient.delete(`/documents/${id}`);
  },
  getStructure: async (id: string, version_id?: string): Promise<unknown> => {
    const { data } = await apiClient.get(`/documents/${id}/structure`, { params: { version_id } });
    return data;
  },
};
