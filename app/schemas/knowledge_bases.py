from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

KnowledgeBaseVisibility = Literal["private", "workspace_read", "workspace_edit"]


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
    visibility: KnowledgeBaseVisibility = "private"
    retrieval_profile: dict[str, Any] = Field(default_factory=dict)
    documents: list[KnowledgeBaseDocumentCreate] = Field(default_factory=list)


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None
    visibility: KnowledgeBaseVisibility | None = None
    retrieval_profile: dict[str, Any] | None = None


class KnowledgeBaseDocumentsReplace(BaseModel):
    documents: list[KnowledgeBaseDocumentCreate] = Field(default_factory=list)


class KnowledgeBaseDocumentOut(BaseModel):
    document_id: str
    pinned_version_id: str | None
    enabled: bool
    label: str | None
    sort_order: int
    document_display_name: str | None = None
    document_source_filename: str | None = None
    document_status: str | None = None


class KnowledgeBaseOut(BaseModel):
    id: str
    tenant_id: str
    workspace_id: str
    name: str
    description: str | None
    status: str
    visibility: KnowledgeBaseVisibility
    retrieval_profile: dict[str, Any]
    created_by: str
    created_at: datetime
    updated_at: datetime
    documents: list[KnowledgeBaseDocumentOut]
