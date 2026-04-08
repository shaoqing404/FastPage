from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class ChatSkill(Base):
    __tablename__ = "chat_skills"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), nullable=False, index=True)
    owner_user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    document_scope_type: Mapped[str] = mapped_column(String(32), default="explicit", nullable=False)
    provider_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("model_providers.id"), nullable=True, index=True)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    request_config_json: Mapped[str] = mapped_column(Text, nullable=False)
    conversation_config_json: Mapped[str] = mapped_column(Text, nullable=False)
    retrieval_config_json: Mapped[str] = mapped_column(Text, nullable=False)
    generation_config_json: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    documents = relationship("ChatSkillDocument", back_populates="skill", cascade="all, delete-orphan")


class ChatSkillDocument(Base):
    __tablename__ = "chat_skill_documents"

    skill_id: Mapped[str] = mapped_column(String(64), ForeignKey("chat_skills.id"), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(64), ForeignKey("documents.id"), primary_key=True)

    skill = relationship("ChatSkill", back_populates="documents")
