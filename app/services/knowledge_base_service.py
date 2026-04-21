import json
import uuid
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.principal import Principal
from app.models import ChatSkill, DocumentVersion, KnowledgeBase, KnowledgeBaseDocument
from app.services.document_service import list_accessible_documents_by_ids
from app.services.skill_service import replace_skill_documents_from_knowledge_base
from app.services.workspace_access_service import (
    assert_can_edit_knowledge_base,
    assert_can_read_knowledge_base,
    can_read_knowledge_base,
    require_workspace_capability,
)


def ensure_workspace_access(principal: Principal, workspace_id: str) -> None:
    if principal.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")


def serialize_knowledge_base_document(document: KnowledgeBaseDocument) -> dict:
    return {
        "document_id": document.document_id,
        "pinned_version_id": document.pinned_version_id,
        "enabled": document.enabled,
        "label": document.label,
        "sort_order": document.sort_order,
    }


def serialize_knowledge_base(knowledge_base: KnowledgeBase) -> dict:
    return {
        "id": knowledge_base.id,
        "tenant_id": knowledge_base.tenant_id,
        "workspace_id": knowledge_base.workspace_id,
        "name": knowledge_base.name,
        "description": knowledge_base.description,
        "status": knowledge_base.status,
        "visibility": knowledge_base.visibility,
        "retrieval_profile": json.loads(knowledge_base.retrieval_profile_json or "{}"),
        "created_by": knowledge_base.created_by,
        "created_at": knowledge_base.created_at,
        "updated_at": knowledge_base.updated_at,
        "documents": [serialize_knowledge_base_document(document) for document in knowledge_base.documents],
    }


def list_knowledge_bases(db: Session, principal: Principal, workspace_id: str) -> list[KnowledgeBase]:
    ensure_workspace_access(principal, workspace_id)
    knowledge_bases = db.scalars(
        select(KnowledgeBase)
        .where(
            KnowledgeBase.tenant_id == principal.tenant_id,
            KnowledgeBase.workspace_id == workspace_id,
        )
        .options(selectinload(KnowledgeBase.documents))
        .order_by(KnowledgeBase.created_at.desc())
    ).all()
    return [knowledge_base for knowledge_base in knowledge_bases if can_read_knowledge_base(principal, knowledge_base)]


def get_knowledge_base_or_404(db: Session, principal: Principal, workspace_id: str, knowledge_base_id: str) -> KnowledgeBase:
    ensure_workspace_access(principal, workspace_id)
    knowledge_base = db.scalar(
        select(KnowledgeBase)
        .where(
            KnowledgeBase.id == knowledge_base_id,
            KnowledgeBase.tenant_id == principal.tenant_id,
            KnowledgeBase.workspace_id == workspace_id,
        )
        .options(selectinload(KnowledgeBase.documents))
    )
    if knowledge_base is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge base not found")
    assert_can_read_knowledge_base(principal, knowledge_base)
    return knowledge_base


def _validate_knowledge_base_documents(
    db: Session,
    principal: Principal,
    workspace_id: str,
    documents_payload: list,
) -> None:
    if not documents_payload:
        return

    document_ids = [document.document_id for document in documents_payload]
    if len(document_ids) != len(set(document_ids)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Duplicate document_id in knowledge base payload")

    docs = list_accessible_documents_by_ids(db, principal, document_ids)
    if len(docs) != len(document_ids):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="One or more knowledge base documents are invalid")

    pinned_version_ids = [document.pinned_version_id for document in documents_payload if document.pinned_version_id]
    if not pinned_version_ids:
        return

    versions = db.scalars(select(DocumentVersion).where(DocumentVersion.id.in_(pinned_version_ids))).all()
    versions_by_id = {version.id: version for version in versions}
    for document in documents_payload:
        if not document.pinned_version_id:
            continue
        version = versions_by_id.get(document.pinned_version_id)
        if version is None or version.document_id != document.document_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"pinned_version_id is invalid for document {document.document_id}",
            )


def replace_knowledge_base_documents(knowledge_base: KnowledgeBase, documents_payload: list) -> None:
    now = datetime.utcnow()
    knowledge_base.documents[:] = [
        KnowledgeBaseDocument(
            knowledge_base_id=knowledge_base.id,
            document_id=document.document_id,
            pinned_version_id=document.pinned_version_id,
            enabled=document.enabled,
            label=document.label,
            sort_order=document.sort_order,
            created_at=now,
            updated_at=now,
        )
        for document in documents_payload
    ]


def sync_knowledge_base_skills(db: Session, knowledge_base: KnowledgeBase) -> None:
    skills = db.scalars(
        select(ChatSkill)
        .where(ChatSkill.knowledge_base_id == knowledge_base.id)
        .options(selectinload(ChatSkill.documents))
    ).all()
    for skill in skills:
        replace_skill_documents_from_knowledge_base(skill, knowledge_base)


def create_knowledge_base(db: Session, principal: Principal, workspace_id: str, payload) -> KnowledgeBase:
    ensure_workspace_access(principal, workspace_id)
    require_workspace_capability(
        principal,
        "can_manage_knowledge_bases",
        detail="Missing workspace capability: can_manage_knowledge_bases",
    )
    _validate_knowledge_base_documents(db, principal, workspace_id, payload.documents)
    now = datetime.utcnow()
    knowledge_base = KnowledgeBase(
        id=str(uuid.uuid4()),
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        name=payload.name,
        description=payload.description,
        status=payload.status,
        visibility=payload.visibility,
        retrieval_profile_json=json.dumps(payload.retrieval_profile, ensure_ascii=False),
        created_by=principal.user_id,
        created_at=now,
        updated_at=now,
    )
    replace_knowledge_base_documents(knowledge_base, payload.documents)
    db.add(knowledge_base)
    db.commit()
    db.refresh(knowledge_base)
    return get_knowledge_base_or_404(db, principal, workspace_id, knowledge_base.id)


def update_knowledge_base(db: Session, principal: Principal, workspace_id: str, knowledge_base_id: str, payload) -> KnowledgeBase:
    knowledge_base = get_knowledge_base_or_404(db, principal, workspace_id, knowledge_base_id)
    assert_can_edit_knowledge_base(principal, knowledge_base)
    update_dict = payload.model_dump(exclude_unset=True)
    if update_dict.get("status") is None and "status" in update_dict:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="status cannot be null")
    if "retrieval_profile" in update_dict:
        knowledge_base.retrieval_profile_json = json.dumps(update_dict.pop("retrieval_profile"), ensure_ascii=False)
    for field, value in update_dict.items():
        setattr(knowledge_base, field, value)
    knowledge_base.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(knowledge_base)
    return get_knowledge_base_or_404(db, principal, workspace_id, knowledge_base.id)


def replace_knowledge_base_documents_for_id(
    db: Session,
    principal: Principal,
    workspace_id: str,
    knowledge_base_id: str,
    documents_payload: list,
) -> KnowledgeBase:
    knowledge_base = get_knowledge_base_or_404(db, principal, workspace_id, knowledge_base_id)
    assert_can_edit_knowledge_base(principal, knowledge_base)
    _validate_knowledge_base_documents(db, principal, workspace_id, documents_payload)
    replace_knowledge_base_documents(knowledge_base, documents_payload)
    sync_knowledge_base_skills(db, knowledge_base)
    knowledge_base.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(knowledge_base)
    return get_knowledge_base_or_404(db, principal, workspace_id, knowledge_base.id)


def add_knowledge_base_document(
    db: Session,
    principal: Principal,
    workspace_id: str,
    knowledge_base_id: str,
    payload,
) -> KnowledgeBase:
    knowledge_base = get_knowledge_base_or_404(db, principal, workspace_id, knowledge_base_id)
    assert_can_edit_knowledge_base(principal, knowledge_base)
    if any(document.document_id == payload.document_id for document in knowledge_base.documents):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Document is already bound to this knowledge base")
    _validate_knowledge_base_documents(db, principal, workspace_id, [payload])
    now = datetime.utcnow()
    knowledge_base.documents.append(
        KnowledgeBaseDocument(
            knowledge_base_id=knowledge_base.id,
            document_id=payload.document_id,
            pinned_version_id=payload.pinned_version_id,
            enabled=payload.enabled,
            label=payload.label,
            sort_order=payload.sort_order,
            created_at=now,
            updated_at=now,
        )
    )
    sync_knowledge_base_skills(db, knowledge_base)
    knowledge_base.updated_at = now
    db.commit()
    db.refresh(knowledge_base)
    return get_knowledge_base_or_404(db, principal, workspace_id, knowledge_base.id)


def update_knowledge_base_document(
    db: Session,
    principal: Principal,
    workspace_id: str,
    knowledge_base_id: str,
    document_id: str,
    payload,
) -> KnowledgeBase:
    knowledge_base = get_knowledge_base_or_404(db, principal, workspace_id, knowledge_base_id)
    assert_can_edit_knowledge_base(principal, knowledge_base)
    document_binding = next((document for document in knowledge_base.documents if document.document_id == document_id), None)
    if document_binding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge base document not found")

    update_dict = payload.model_dump(exclude_unset=True)
    if update_dict.get("enabled") is None and "enabled" in update_dict:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="enabled cannot be null")
    if update_dict.get("sort_order") is None and "sort_order" in update_dict:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="sort_order cannot be null")
    if "pinned_version_id" in update_dict and update_dict["pinned_version_id"] is not None:
        _validate_knowledge_base_documents(
            db,
            principal,
            workspace_id,
            [
                type("Binding", (), {"document_id": document_id, "pinned_version_id": update_dict["pinned_version_id"]})(),
            ],
        )
    for field, value in update_dict.items():
        setattr(document_binding, field, value)
    sync_knowledge_base_skills(db, knowledge_base)
    document_binding.updated_at = datetime.utcnow()
    knowledge_base.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(knowledge_base)
    return get_knowledge_base_or_404(db, principal, workspace_id, knowledge_base.id)


def delete_knowledge_base_document(
    db: Session,
    principal: Principal,
    workspace_id: str,
    knowledge_base_id: str,
    document_id: str,
) -> None:
    knowledge_base = get_knowledge_base_or_404(db, principal, workspace_id, knowledge_base_id)
    assert_can_edit_knowledge_base(principal, knowledge_base)
    document_binding = next((document for document in knowledge_base.documents if document.document_id == document_id), None)
    if document_binding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge base document not found")
    knowledge_base.documents.remove(document_binding)
    sync_knowledge_base_skills(db, knowledge_base)
    knowledge_base.updated_at = datetime.utcnow()
    db.commit()


def delete_knowledge_base(db: Session, principal: Principal, workspace_id: str, knowledge_base_id: str) -> None:
    knowledge_base = get_knowledge_base_or_404(db, principal, workspace_id, knowledge_base_id)
    assert_can_edit_knowledge_base(principal, knowledge_base)
    skill_ref = db.scalar(
        select(ChatSkill.id).where(
            ChatSkill.tenant_id == principal.tenant_id,
            ChatSkill.workspace_id == workspace_id,
            ChatSkill.knowledge_base_id == knowledge_base.id,
        ).limit(1)
    )
    if skill_ref:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Knowledge base is still bound to skills")
    db.delete(knowledge_base)
    db.commit()
