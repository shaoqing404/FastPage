"""Minimal audit event write path.

All writes are append-only.  No update or delete operations are provided.
Sensitive material (tokens, API keys, secrets) must NEVER be logged.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.request_context import get_request_id
from app.models.audit_event import AuditEvent


def emit_audit_event(
    db: Session,
    *,
    tenant_id: str,
    actor_type: str,
    actor_id: str,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    result: str = "success",
    request_id: str | None = None,
    meta: dict[str, Any] | None = None,
) -> AuditEvent:
    """Insert a single audit event row.  Commits within the caller's session."""
    event = AuditEvent(
        id=str(uuid.uuid4()),
        timestamp=datetime.utcnow(),
        tenant_id=tenant_id,
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        result=result,
        request_id=request_id or get_request_id(),
        meta_json=json.dumps(meta, ensure_ascii=False) if meta else None,
    )
    db.add(event)
    # Flush to ensure the row is visible within the current transaction,
    # but let the caller commit (or the surrounding service function commit).
    db.flush()
    return event


def audit_from_principal(
    db: Session,
    principal,
    action: str,
    *,
    target_type: str | None = None,
    target_id: str | None = None,
    result: str = "success",
    meta: dict[str, Any] | None = None,
) -> AuditEvent:
    """Convenience wrapper that extracts actor info from a ``Principal``."""
    return emit_audit_event(
        db,
        tenant_id=principal.tenant_id,
        actor_type=principal.kind,
        actor_id=principal.user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        result=result,
        meta=meta,
    )
