from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str
    document_id: str
    version_id: str | None = None
    model: str | None = None
    provider_id: str | None = None
    session_id: str | None = None
    request_config: dict[str, Any] = Field(default_factory=dict)
    retrieval_config: dict[str, Any] = Field(default_factory=dict)
    generation_config: dict[str, Any] = Field(default_factory=dict)


class SkillRunRequest(BaseModel):
    question: str
    document_id: str | None = None
    provider_id: str | None = None
    session_id: str | None = None
    auto_create_session: bool = False
    session_title: str | None = None
    stream: bool = False
    conversation_config: dict[str, Any] = Field(default_factory=dict)
    retrieval_config: dict[str, Any] = Field(default_factory=dict)
    generation_config: dict[str, Any] = Field(default_factory=dict)


class ChatSessionCreateRequest(BaseModel):
    title: str | None = None
    skill_id: str | None = None


class ChatSessionOut(BaseModel):
    id: str
    tenant_id: str
    user_id: str
    skill_id: str | None
    title: str
    created_at: datetime
    updated_at: datetime


class ChatMessageOut(BaseModel):
    id: str
    session_id: str
    tenant_id: str
    user_id: str
    run_id: str | None
    role: str
    content: str
    sequence_no: int
    created_at: datetime


class ChatRunOut(BaseModel):
    id: str
    tenant_id: str
    user_id: str
    session_id: str | None
    document_id: str | None
    version_id: str | None
    skill_id: str | None
    provider_id: str | None
    model: str
    question: str
    answer: str | None
    answer_text: str | None
    answer_with_marker: str | None
    status: str
    cancel_requested: bool
    cancel_reason: str | None
    execution_context: dict[str, Any]
    selected_sections: list[dict[str, Any]]
    citations: list[dict[str, Any]]
    metrics: dict[str, Any]
    last_error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
