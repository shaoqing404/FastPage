import uuid
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.principal import Principal
from app.models import ChatMessage, ChatSession, Workspace


def _is_default_workspace(db: Session, tenant_id: str, workspace_id: str) -> bool:
    return db.scalar(
        select(Workspace.id).where(
            Workspace.tenant_id == tenant_id,
            Workspace.id == workspace_id,
            Workspace.is_default.is_(True),
        ).limit(1)
    ) is not None


def _session_workspace_filter(db: Session, principal: Principal):
    if _is_default_workspace(db, principal.tenant_id, principal.workspace_id):
        return or_(ChatSession.workspace_id == principal.workspace_id, ChatSession.workspace_id.is_(None))
    return ChatSession.workspace_id == principal.workspace_id


def _message_workspace_filter(db: Session, principal: Principal):
    if _is_default_workspace(db, principal.tenant_id, principal.workspace_id):
        return or_(ChatMessage.workspace_id == principal.workspace_id, ChatMessage.workspace_id.is_(None))
    return ChatMessage.workspace_id == principal.workspace_id


def _validate_skill_scope(db: Session, principal: Principal, skill_id: str | None):
    if not skill_id:
        return None
    from app.services.skill_service import get_skill_or_404

    return get_skill_or_404(db, principal, skill_id)


def create_session(
    db: Session,
    principal: Principal,
    title: str | None = None,
    *,
    skill_id: str | None = None,
) -> ChatSession:
    _validate_skill_scope(db, principal, skill_id)
    now = datetime.utcnow()
    session = ChatSession(
        id=str(uuid.uuid4()),
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        user_id=principal.user_id,
        skill_id=skill_id,
        active_run_id=None,
        title=(title or "New Chat Session").strip() or "New Chat Session",
        created_at=now,
        updated_at=now,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_session_or_404(db: Session, principal: Principal, session_id: str) -> ChatSession:
    session = db.scalar(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.tenant_id == principal.tenant_id,
            _session_workspace_filter(db, principal),
        )
    )
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return session


def get_skill_session_or_404(db: Session, principal: Principal, skill_id: str, session_id: str) -> ChatSession:
    _validate_skill_scope(db, principal, skill_id)
    session = get_session_or_404(db, principal, session_id)
    if session.skill_id != skill_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill session not found")
    return session


def list_sessions(
    db: Session,
    principal: Principal,
    *,
    skill_id: str | None = None,
) -> list[ChatSession]:
    if skill_id:
        _validate_skill_scope(db, principal, skill_id)
    stmt = select(ChatSession).where(
        ChatSession.tenant_id == principal.tenant_id,
        _session_workspace_filter(db, principal),
    )
    if skill_id is None:
        stmt = stmt.where(ChatSession.skill_id.is_(None))
    else:
        stmt = stmt.where(ChatSession.skill_id == skill_id)
    return db.scalars(stmt.order_by(ChatSession.updated_at.desc())).all()


def append_message(
    db: Session,
    *,
    session_id: str,
    tenant_id: str,
    user_id: str,
    role: str,
    content: str,
    run_id: str | None = None,
) -> ChatMessage:
    session = db.get(ChatSession, session_id)
    if session is None or session.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if run_id:
        existing = db.scalar(
            select(ChatMessage).where(
                ChatMessage.session_id == session_id,
                ChatMessage.run_id == run_id,
                ChatMessage.role == role,
            )
        )
        if existing is not None:
            return existing
    next_sequence = (db.scalar(select(func.max(ChatMessage.sequence_no)).where(ChatMessage.session_id == session_id)) or 0) + 1
    message = ChatMessage(
        id=str(uuid.uuid4()),
        session_id=session_id,
        tenant_id=tenant_id,
        workspace_id=session.workspace_id,
        user_id=user_id,
        run_id=run_id,
        role=role,
        content=content,
        sequence_no=next_sequence,
        created_at=datetime.utcnow(),
    )
    db.add(message)
    session.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(message)
    return message


def list_session_messages(
    db: Session,
    *,
    principal: Principal | None = None,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    session_id: str,
    limit: int | None = None,
) -> list[ChatMessage]:
    if principal is not None:
        tenant_clause = ChatMessage.tenant_id == principal.tenant_id
        workspace_clause = _message_workspace_filter(db, principal)
    else:
        if tenant_id is None:
            raise ValueError("tenant_id is required when principal is not provided")
        tenant_clause = ChatMessage.tenant_id == tenant_id
        if workspace_id is None:
            workspace_clause = ChatMessage.workspace_id.is_(None)
        else:
            workspace_clause = ChatMessage.workspace_id == workspace_id
    stmt = select(ChatMessage).where(
        ChatMessage.session_id == session_id,
        tenant_clause,
        workspace_clause,
    ).order_by(ChatMessage.sequence_no.asc())
    messages = db.scalars(stmt).all()
    if limit is not None and limit > 0:
        return messages[-limit:]
    return messages
