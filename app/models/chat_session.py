from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), nullable=False, index=True)
    workspace_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("workspaces.id"), nullable=True, index=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), nullable=False, index=True)
    skill_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("chat_skills.id"), nullable=True, index=True)
    active_run_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("chat_runs.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), ForeignKey("chat_sessions.id"), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), nullable=False, index=True)
    workspace_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("workspaces.id"), nullable=True, index=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), nullable=False, index=True)
    run_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("chat_runs.id"), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
