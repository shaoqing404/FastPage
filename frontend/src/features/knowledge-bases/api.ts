import { apiClient, resolveActiveWorkspaceId } from '../../lib/api/client';

import type {
  KnowledgeBase,
  KnowledgeBaseDocumentBindingInput,
  KnowledgeBaseDocumentBindingUpdate,
  KnowledgeBaseMutationPayload,
  KnowledgeBaseUpdateInput,
} from './types';

const workspacePath = () => `/workspaces/${resolveActiveWorkspaceId()}/knowledge-bases`;

export const knowledgeBasesApi = {
  list: async (): Promise<KnowledgeBase[]> => {
    const { data } = await apiClient.get<KnowledgeBase[]>(workspacePath());
    return data;
  },
  get: async (knowledgeBaseId: string): Promise<KnowledgeBase> => {
    const { data } = await apiClient.get<KnowledgeBase>(`${workspacePath()}/${knowledgeBaseId}`);
    return data;
  },
  create: async (payload: KnowledgeBaseMutationPayload): Promise<KnowledgeBase> => {
    const { data } = await apiClient.post<KnowledgeBase>(workspacePath(), payload);
    return data;
  },
  update: async (knowledgeBaseId: string, payload: KnowledgeBaseUpdateInput): Promise<KnowledgeBase> => {
    const { data } = await apiClient.patch<KnowledgeBase>(`${workspacePath()}/${knowledgeBaseId}`, payload);
    return data;
  },
  replaceDocuments: async (knowledgeBaseId: string, documents: KnowledgeBaseDocumentBindingInput[]): Promise<KnowledgeBase> => {
    const { data } = await apiClient.put<KnowledgeBase>(`${workspacePath()}/${knowledgeBaseId}/documents`, { documents });
    return data;
  },
  addDocument: async (knowledgeBaseId: string, payload: KnowledgeBaseDocumentBindingInput): Promise<KnowledgeBase> => {
    const { data } = await apiClient.post<KnowledgeBase>(`${workspacePath()}/${knowledgeBaseId}/documents`, payload);
    return data;
  },
  updateDocument: async (knowledgeBaseId: string, documentId: string, payload: KnowledgeBaseDocumentBindingUpdate): Promise<KnowledgeBase> => {
    const { data } = await apiClient.patch<KnowledgeBase>(
      `${workspacePath()}/${knowledgeBaseId}/documents/${documentId}`,
      payload,
    );
    return data;
  },
  deleteDocument: async (knowledgeBaseId: string, documentId: string): Promise<void> => {
    await apiClient.delete(`${workspacePath()}/${knowledgeBaseId}/documents/${documentId}`);
  },
  delete: async (knowledgeBaseId: string): Promise<void> => {
    await apiClient.delete(`${workspacePath()}/${knowledgeBaseId}`);
  },
};
