"""Audit event model — append-only log of security-sensitive actions."""

from sqlalchemy import Column, DateTime, Index, String, Text

from app.core.db import Base


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(String(64), primary_key=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    tenant_id = Column(String(64), nullable=False, index=True)

    # Actor
    actor_type = Column(String(32), nullable=False)   # user | api_key | system
    actor_id = Column(String(64), nullable=False)

    # Action
    action = Column(String(64), nullable=False)        # e.g. provider.create, document.upload

    # Target
    target_type = Column(String(64), nullable=True)
    target_id = Column(String(64), nullable=True)

    # Outcome
    result = Column(String(32), nullable=False)        # success | failure

    # Correlation
    request_id = Column(String(64), nullable=True)

    # Optional extra context (JSON string)
    meta_json = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_audit_events_tenant_action", "tenant_id", "action"),
    )
