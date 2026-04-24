from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from .routing_asset_contract import ROUTING_ASSET_SCHEMA_VERSION, routing_asset_readiness_for_version
from .document_routing_node import DocumentRoutingNode  # noqa: F401


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), nullable=False, index=True)
    workspace_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("workspaces.id"), nullable=True, index=True)
    owner_user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), nullable=False, index=True)
    uploaded_via_kb_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
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
    # Routing asset lifecycle is tracked separately from parse/query eligibility.
    routing_index_status: Mapped[str] = mapped_column(String(32), default="uploaded", nullable=False, index=True)
    routing_index_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    routing_index_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Contract/schema version for routing_index.json. Missing legacy assets should be treated as v1.
    routing_index_version: Mapped[str] = mapped_column(String(32), default="v1", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    document = relationship("Document", back_populates="versions", foreign_keys=[document_id])

    @property
    def routing_asset_schema_version(self) -> str:
        version = str(self.routing_index_version or "").strip()
        return version or ROUTING_ASSET_SCHEMA_VERSION

    @property
    def routing_asset_is_ready(self) -> bool:
        return self.routing_index_status == "index_ready" and bool(self.routing_index_path)

    @property
    def routing_asset_readiness(self) -> dict[str, str]:
        return routing_asset_readiness_for_version(
            routing_index_status=self.routing_index_status,
            routing_index_path=self.routing_index_path,
        )
