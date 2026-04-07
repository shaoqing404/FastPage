from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), nullable=False, index=True)
    owner_user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    active_version_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("document_versions.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="uploaded", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    versions = relationship("DocumentVersion", back_populates="document", foreign_keys="DocumentVersion.document_id")


class DocumentVersion(Base):
    __tablename__ = "document_versions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(64), ForeignKey("documents.id"), nullable=False, index=True)
    version_no: Mapped[int] = mapped_column(nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    parse_status: Mapped[str] = mapped_column(String(32), default="uploaded", nullable=False, index=True)
    parsed_structure_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    document = relationship("Document", back_populates="versions", foreign_keys=[document_id])
