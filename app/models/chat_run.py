from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ChatRun(Base):
    __tablename__ = "chat_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), nullable=False, index=True)
    workspace_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("workspaces.id"), nullable=True, index=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), nullable=False, index=True)
    session_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("chat_sessions.id"), nullable=True, index=True)
    document_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("documents.id"), nullable=True, index=True)
    version_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("document_versions.id"), nullable=True, index=True)
    skill_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("chat_skills.id"), nullable=True, index=True)
    provider_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("model_providers.id"), nullable=True, index=True)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_with_marker: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="accepted", nullable=False, index=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_config_json: Mapped[str] = mapped_column(Text, nullable=False)
    conversation_config_json: Mapped[str] = mapped_column(Text, nullable=False)
    retrieval_config_json: Mapped[str] = mapped_column(Text, nullable=False)
    generation_config_json: Mapped[str] = mapped_column(Text, nullable=False)
    selected_sections_json: Mapped[str] = mapped_column(Text, nullable=False)
    citations_json: Mapped[str] = mapped_column(Text, nullable=False)
    execution_context_json: Mapped[str] = mapped_column(Text, nullable=False)
    metrics_json: Mapped[str] = mapped_column(Text, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    worker_node_code: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
