import type { ChatSkill, Document } from '../../types';

export interface KnowledgeBaseDocumentBinding {
  document_id: string;
  pinned_version_id: string | null;
  enabled: boolean;
  label: string | null;
  sort_order: number;
}

export interface KnowledgeBaseSummary {
  id: string;
  tenant_id: string;
  workspace_id: string;
  name: string;
  description: string | null;
  status: string;
  retrieval_profile: Record<string, unknown>;
  created_by: string;
  created_at: string;
  updated_at: string;
  documents: KnowledgeBaseDocumentBinding[];
}

export type SkillConsoleItem = ChatSkill & {
  workspace_id?: string | null;
  knowledge_base_id?: string | null;
  is_active?: boolean;
};

export const getEnabledKnowledgeBaseDocuments = (knowledgeBase?: KnowledgeBaseSummary | null) =>
  (knowledgeBase?.documents || []).filter((document) => document.enabled);

export const getKnowledgeBaseDocumentCount = (knowledgeBase?: KnowledgeBaseSummary | null) =>
  getEnabledKnowledgeBaseDocuments(knowledgeBase).length;

export const resolveDocumentDisplayName = (documentId: string, documentsById: Map<string, Document>) =>
  documentsById.get(documentId)?.display_name || documentId;
