import json
import uuid
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import ChatMessage, ChatRun, ChatSession, ChatSkill, ChatSkillDocument, Document, ModelProvider, User
from app.services.storage_service import delete_skill_trace_tree


def serialize_skill(skill: ChatSkill) -> dict:
    return {
        "id": skill.id,
        "tenant_id": skill.tenant_id,
        "owner_user_id": skill.owner_user_id,
        "name": skill.name,
        "description": skill.description,
        "system_prompt": skill.system_prompt,
        "document_scope_type": skill.document_scope_type,
        "provider_id": skill.provider_id,
        "model": skill.model,
        "request_config": json.loads(skill.request_config_json or "{}"),
        "conversation_config": json.loads(skill.conversation_config_json or "{}"),
        "retrieval_config": json.loads(skill.retrieval_config_json or "{}"),
        "generation_config": json.loads(skill.generation_config_json or "{}"),
        "document_ids": [link.document_id for link in skill.documents],
        "is_active": skill.is_active,
        "created_at": skill.created_at,
        "updated_at": skill.updated_at,
    }


def get_skill_or_404(db: Session, user: User, skill_id: str) -> ChatSkill:
    skill = db.get(ChatSkill, skill_id)
    if skill is None or skill.tenant_id != user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found")
    return skill


def validate_document_ids(db: Session, user: User, document_ids: list[str]) -> None:
    if not document_ids:
        return
    docs = db.scalars(select(Document).where(Document.id.in_(document_ids), Document.tenant_id == user.tenant_id)).all()
    if len(docs) != len(set(document_ids)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="One or more document_ids are invalid")


def replace_skill_documents(skill: ChatSkill, document_ids: list[str]) -> None:
    skill.documents[:] = [ChatSkillDocument(skill_id=skill.id, document_id=document_id) for document_id in document_ids]


def validate_provider_id(db: Session, user: User, provider_id: str | None) -> None:
    if not provider_id:
        return
    provider = db.get(ModelProvider, provider_id)
    if provider is None or provider.tenant_id != user.tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="provider_id is invalid")


def create_skill(db: Session, user: User, payload) -> ChatSkill:
    validate_document_ids(db, user, payload.document_ids)
    validate_provider_id(db, user, payload.provider_id)
    now = datetime.utcnow()
    skill = ChatSkill(
        id=str(uuid.uuid4()),
        tenant_id=user.tenant_id,
        owner_user_id=user.id,
        name=payload.name,
        description=payload.description,
        system_prompt=payload.system_prompt,
        document_scope_type=payload.document_scope_type,
        provider_id=payload.provider_id,
        model=payload.model,
        request_config_json=json.dumps(payload.request_config, ensure_ascii=False),
        conversation_config_json=json.dumps(payload.conversation_config, ensure_ascii=False),
        retrieval_config_json=json.dumps(payload.retrieval_config, ensure_ascii=False),
        generation_config_json=json.dumps(payload.generation_config, ensure_ascii=False),
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    replace_skill_documents(skill, payload.document_ids)
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill


def update_skill(db: Session, user: User, skill_id: str, payload) -> ChatSkill:
    skill = get_skill_or_404(db, user, skill_id)
    update_dict = payload.model_dump(exclude_unset=True)
    if "document_ids" in update_dict:
        validate_document_ids(db, user, update_dict["document_ids"])
        replace_skill_documents(skill, update_dict.pop("document_ids"))
    if "provider_id" in update_dict:
        validate_provider_id(db, user, update_dict["provider_id"])
    if "request_config" in update_dict:
        skill.request_config_json = json.dumps(update_dict.pop("request_config"), ensure_ascii=False)
    if "conversation_config" in update_dict:
        skill.conversation_config_json = json.dumps(update_dict.pop("conversation_config"), ensure_ascii=False)
    if "retrieval_config" in update_dict:
        skill.retrieval_config_json = json.dumps(update_dict.pop("retrieval_config"), ensure_ascii=False)
    if "generation_config" in update_dict:
        skill.generation_config_json = json.dumps(update_dict.pop("generation_config"), ensure_ascii=False)
    for field, value in update_dict.items():
        setattr(skill, field, value)
    skill.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(skill)
    return skill


def delete_skill(db: Session, user: User, skill_id: str) -> None:
    skill = get_skill_or_404(db, user, skill_id)
    run_ids = list(
        db.scalars(
            select(ChatRun.id).where(
                ChatRun.tenant_id == user.tenant_id,
                ChatRun.skill_id == skill.id,
            )
        )
    )
    session_ids = list(
        db.scalars(
            select(ChatSession.id).where(
                ChatSession.tenant_id == user.tenant_id,
                ChatSession.skill_id == skill.id,
            )
        )
    )

    if run_ids or session_ids:
        message_filters = []
        if run_ids:
            message_filters.append(ChatMessage.run_id.in_(run_ids))
        if session_ids:
            message_filters.append(ChatMessage.session_id.in_(session_ids))
        db.query(ChatMessage).filter(
            ChatMessage.tenant_id == user.tenant_id,
            or_(*message_filters),
        ).delete(synchronize_session=False)

    if run_ids:
        db.query(ChatRun).filter(
            ChatRun.tenant_id == user.tenant_id,
            ChatRun.id.in_(run_ids),
        ).delete(synchronize_session=False)

    if session_ids:
        db.query(ChatSession).filter(
            ChatSession.tenant_id == user.tenant_id,
            ChatSession.id.in_(session_ids),
        ).delete(synchronize_session=False)

    db.query(ChatSkillDocument).filter(ChatSkillDocument.skill_id == skill.id).delete(synchronize_session=False)
    db.delete(skill)
    db.commit()
    delete_skill_trace_tree(user.tenant_id, skill.id)
