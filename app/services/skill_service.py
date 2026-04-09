import json
import uuid
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.principal import Principal
from app.models import (
    ChatMessage,
    ChatRun,
    ChatSession,
    ChatSkill,
    ChatSkillDocument,
    Document,
    KnowledgeBase,
    ModelProvider,
    User,
)
from app.services.document_service import list_accessible_documents_by_ids
from app.services.provider_service import can_bind_provider_to_workspace
from app.services.storage_service import delete_skill_trace_tree


def serialize_skill(skill: ChatSkill) -> dict:
    knowledge_base_documents = skill.knowledge_base.documents if skill.knowledge_base is not None else []
    document_ids = [link.document_id for link in knowledge_base_documents if link.enabled]
    if skill.knowledge_base is None:
        document_ids = [link.document_id for link in skill.documents]
    return {
        "id": skill.id,
        "tenant_id": skill.tenant_id,
        "workspace_id": skill.workspace_id,
        "owner_user_id": skill.owner_user_id,
        "name": skill.name,
        "description": skill.description,
        "system_prompt": skill.system_prompt,
        "document_scope_type": skill.document_scope_type,
        "knowledge_base_id": skill.knowledge_base_id,
        "provider_id": skill.provider_id,
        "model": skill.model,
        "request_config": json.loads(skill.request_config_json or "{}"),
        "conversation_config": json.loads(skill.conversation_config_json or "{}"),
        "retrieval_config": json.loads(skill.retrieval_config_json or "{}"),
        "generation_config": json.loads(skill.generation_config_json or "{}"),
        "document_ids": document_ids,
        "is_active": skill.is_active,
        "created_at": skill.created_at,
        "updated_at": skill.updated_at,
    }


def _principal_workspace_id(actor: Principal | User) -> str | None:
    return getattr(actor, "workspace_id", None)


def get_skill_or_404(db: Session, actor: Principal | User, skill_id: str) -> ChatSkill:
    skill = db.scalar(
        select(ChatSkill)
        .where(ChatSkill.id == skill_id)
        .options(
            selectinload(ChatSkill.documents),
            selectinload(ChatSkill.knowledge_base).selectinload(KnowledgeBase.documents),
        )
    )
    if skill is None or skill.tenant_id != actor.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found")
    workspace_id = _principal_workspace_id(actor)
    if workspace_id is not None and skill.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found")
    return skill


def validate_document_ids(db: Session, actor: Principal | User, document_ids: list[str]) -> None:
    if not document_ids:
        return
    if len(document_ids) != len(set(document_ids)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Duplicate document_ids are not allowed")
    workspace_id = _principal_workspace_id(actor)
    if workspace_id is None:
        docs = db.scalars(select(Document).where(Document.id.in_(document_ids), Document.tenant_id == actor.tenant_id)).all()
    else:
        docs = list_accessible_documents_by_ids(db, actor, document_ids)
    if len(docs) != len(document_ids):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="One or more document_ids are invalid")


def replace_skill_documents(skill: ChatSkill, document_ids: list[str]) -> None:
    skill.documents[:] = [ChatSkillDocument(skill_id=skill.id, document_id=document_id) for document_id in document_ids]


def replace_skill_documents_from_knowledge_base(skill: ChatSkill, knowledge_base: KnowledgeBase | None) -> None:
    if knowledge_base is None:
        return
    replace_skill_documents(
        skill,
        [document.document_id for document in knowledge_base.documents if document.enabled],
    )


def validate_provider_id(db: Session, actor: Principal | User, provider_id: str | None) -> None:
    if not provider_id:
        return
    provider = db.get(ModelProvider, provider_id)
    if provider is None or provider.tenant_id != actor.tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="provider_id is invalid")
    workspace_id = _principal_workspace_id(actor)
    if workspace_id is not None and not can_bind_provider_to_workspace(provider, workspace_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="provider_id is not accessible from this workspace")


def validate_knowledge_base_id(db: Session, actor: Principal | User, knowledge_base_id: str | None) -> KnowledgeBase | None:
    if not knowledge_base_id:
        return None
    knowledge_base = db.scalar(
        select(KnowledgeBase)
        .where(KnowledgeBase.id == knowledge_base_id)
        .options(selectinload(KnowledgeBase.documents))
    )
    if knowledge_base is None or knowledge_base.tenant_id != actor.tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="knowledge_base_id is invalid")
    workspace_id = _principal_workspace_id(actor)
    if workspace_id is not None and knowledge_base.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="knowledge_base_id is invalid")
    return knowledge_base


def create_skill(db: Session, principal: Principal, payload) -> ChatSkill:
    validate_provider_id(db, principal, payload.provider_id)
    knowledge_base = validate_knowledge_base_id(db, principal, payload.knowledge_base_id)
    if knowledge_base is None:
        validate_document_ids(db, principal, payload.document_ids)
    now = datetime.utcnow()
    skill = ChatSkill(
        id=str(uuid.uuid4()),
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        owner_user_id=principal.user_id,
        name=payload.name,
        description=payload.description,
        system_prompt=payload.system_prompt,
        document_scope_type=payload.document_scope_type,
        knowledge_base_id=payload.knowledge_base_id,
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
    if knowledge_base is not None:
        replace_skill_documents_from_knowledge_base(skill, knowledge_base)
    else:
        replace_skill_documents(skill, payload.document_ids)
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill


def update_skill(db: Session, principal: Principal, skill_id: str, payload) -> ChatSkill:
    skill = get_skill_or_404(db, principal, skill_id)
    update_dict = payload.model_dump(exclude_unset=True)
    next_knowledge_base = skill.knowledge_base
    document_ids_payload = None
    if "document_ids" in update_dict:
        document_ids_payload = update_dict.pop("document_ids")
    if "provider_id" in update_dict:
        validate_provider_id(db, principal, update_dict["provider_id"])
    if "knowledge_base_id" in update_dict:
        next_knowledge_base = validate_knowledge_base_id(db, principal, update_dict["knowledge_base_id"])
    if document_ids_payload is not None:
        if update_dict.get("knowledge_base_id", skill.knowledge_base_id) is None:
            validate_document_ids(db, principal, document_ids_payload)
            replace_skill_documents(skill, document_ids_payload)
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
    if skill.knowledge_base_id is not None or next_knowledge_base is not None:
        replace_skill_documents_from_knowledge_base(skill, next_knowledge_base)
    skill.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(skill)
    return skill


def delete_skill(db: Session, principal: Principal, skill_id: str) -> None:
    skill = get_skill_or_404(db, principal, skill_id)
    run_ids = list(
        db.scalars(
            select(ChatRun.id).where(
                ChatRun.tenant_id == principal.tenant_id,
                ChatRun.skill_id == skill.id,
            )
        )
    )
    session_ids = list(
        db.scalars(
            select(ChatSession.id).where(
                ChatSession.tenant_id == principal.tenant_id,
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
            ChatMessage.tenant_id == principal.tenant_id,
            or_(*message_filters),
        ).delete(synchronize_session=False)

    if run_ids:
        db.query(ChatRun).filter(
            ChatRun.tenant_id == principal.tenant_id,
            ChatRun.id.in_(run_ids),
        ).delete(synchronize_session=False)

    if session_ids:
        db.query(ChatSession).filter(
            ChatSession.tenant_id == principal.tenant_id,
            ChatSession.id.in_(session_ids),
        ).delete(synchronize_session=False)

    db.query(ChatSkillDocument).filter(ChatSkillDocument.skill_id == skill.id).delete(synchronize_session=False)
    db.delete(skill)
    db.commit()
    delete_skill_trace_tree(principal.tenant_id, skill.id)
