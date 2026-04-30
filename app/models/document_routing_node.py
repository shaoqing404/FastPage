from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class DocumentRoutingNode(Base):
    """Portable base-node rows for the routing asset v1 contract."""

    __tablename__ = "document_routing_nodes"
    __table_args__ = (
        UniqueConstraint("version_id", "node_id", name="uq_document_routing_nodes_version_node"),
        Index("ix_document_routing_nodes_document_version", "document_id", "version_id"),
        Index("ix_document_routing_nodes_version_parent_node", "version_id", "parent_node_id"),
        Index("ix_document_routing_nodes_version_depth", "version_id", "depth"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(64), ForeignKey("documents.id"), nullable=False)
    version_id: Mapped[str] = mapped_column(String(64), ForeignKey("document_versions.id"), nullable=False)
    node_id: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_node_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    depth: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    breadcrumb: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    route_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Keep future-router fields portable: nullable Text avoids JSON/vector dialect coupling.
    contrastive_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    aliases_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    keywords_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    manual_profile_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
