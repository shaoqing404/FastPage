from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class KnowledgeBaseDocumentCreate(BaseModel):
    document_id: str
    pinned_version_id: str | None = None
    enabled: bool = True
    label: str | None = None
    sort_order: int = 0


class KnowledgeBaseDocumentUpdate(BaseModel):
    pinned_version_id: str | None = None
    enabled: bool | None = None
    label: str | None = None
    sort_order: int | None = None


class KnowledgeBaseCreate(BaseModel):
    name: str
    description: str | None = None
    status: str = "active"
    retrieval_profile: dict[str, Any] = Field(default_factory=dict)
    documents: list[KnowledgeBaseDocumentCreate] = Field(default_factory=list)


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None
    retrieval_profile: dict[str, Any] | None = None


class KnowledgeBaseDocumentsReplace(BaseModel):
    documents: list[KnowledgeBaseDocumentCreate] = Field(default_factory=list)


class KnowledgeBaseDocumentOut(BaseModel):
    document_id: str
    pinned_version_id: str | None
    enabled: bool
    label: str | None
    sort_order: int


class KnowledgeBaseOut(BaseModel):
    id: str
    tenant_id: str
    workspace_id: str
    name: str
    description: str | None
    status: str
    retrieval_profile: dict[str, Any]
    created_by: str
    created_at: datetime
    updated_at: datetime
    documents: list[KnowledgeBaseDocumentOut]
