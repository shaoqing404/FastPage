from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ChatSkillCreate(BaseModel):
    name: str
    description: str | None = None
    system_prompt: str
    document_ids: list[str] = Field(default_factory=list)
    knowledge_base_id: str | None = None
    provider_id: str | None = None
    model: str
    request_config: dict[str, Any] = Field(default_factory=dict)
    conversation_config: dict[str, Any] = Field(default_factory=dict)
    retrieval_config: dict[str, Any] = Field(default_factory=dict)
    generation_config: dict[str, Any] = Field(default_factory=dict)
    document_scope_type: str = "explicit"


class ChatSkillUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    document_ids: list[str] | None = None
    knowledge_base_id: str | None = None
    provider_id: str | None = None
    model: str | None = None
    request_config: dict[str, Any] | None = None
    conversation_config: dict[str, Any] | None = None
    retrieval_config: dict[str, Any] | None = None
    generation_config: dict[str, Any] | None = None
    document_scope_type: str | None = None
    is_active: bool | None = None


class ChatSkillOut(BaseModel):
    id: str
    tenant_id: str
    workspace_id: str | None
    owner_user_id: str
    name: str
    description: str | None
    system_prompt: str
    document_scope_type: str
    knowledge_base_id: str | None
    provider_id: str | None
    model: str
    request_config: dict[str, Any]
    conversation_config: dict[str, Any]
    retrieval_config: dict[str, Any]
    generation_config: dict[str, Any]
    document_ids: list[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime
