import uuid
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ChatMessage, ChatSession, ChatSkill


def _validate_skill_scope(db: Session, tenant_id: str, skill_id: str | None) -> ChatSkill | None:
    if not skill_id:
        return None
    skill = db.get(ChatSkill, skill_id)
    if skill is None or skill.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found")
    return skill


def create_session(
    db: Session,
    tenant_id: str,
    user_id: str,
    title: str | None = None,
    *,
    skill_id: str | None = None,
) -> ChatSession:
    _validate_skill_scope(db, tenant_id, skill_id)
    now = datetime.utcnow()
    session = ChatSession(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        user_id=user_id,
        skill_id=skill_id,
        title=(title or "New Chat Session").strip() or "New Chat Session",
        created_at=now,
        updated_at=now,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_session_or_404(db: Session, tenant_id: str, session_id: str) -> ChatSession:
    session = db.get(ChatSession, session_id)
    if session is None or session.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return session


def get_skill_session_or_404(db: Session, tenant_id: str, skill_id: str, session_id: str) -> ChatSession:
    _validate_skill_scope(db, tenant_id, skill_id)
    session = get_session_or_404(db, tenant_id, session_id)
    if session.skill_id != skill_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill session not found")
    return session


def list_sessions(
    db: Session,
    tenant_id: str,
    *,
    skill_id: str | None = None,
) -> list[ChatSession]:
    if skill_id:
        _validate_skill_scope(db, tenant_id, skill_id)
    stmt = select(ChatSession).where(ChatSession.tenant_id == tenant_id)
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
    next_sequence = (db.scalar(select(func.max(ChatMessage.sequence_no)).where(ChatMessage.session_id == session_id)) or 0) + 1
    message = ChatMessage(
        id=str(uuid.uuid4()),
        session_id=session_id,
        tenant_id=tenant_id,
        user_id=user_id,
        run_id=run_id,
        role=role,
        content=content,
        sequence_no=next_sequence,
        created_at=datetime.utcnow(),
    )
    db.add(message)
    session = db.get(ChatSession, session_id)
    if session is not None:
        session.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(message)
    return message


def list_session_messages(
    db: Session,
    *,
    tenant_id: str,
    session_id: str,
    limit: int | None = None,
) -> list[ChatMessage]:
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id, ChatMessage.tenant_id == tenant_id)
        .order_by(ChatMessage.sequence_no.asc())
    )
    messages = db.scalars(stmt).all()
    if limit is not None and limit > 0:
        return messages[-limit:]
    return messages
