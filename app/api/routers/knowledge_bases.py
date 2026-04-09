from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_principal
from app.core.db import get_db
from app.core.principal import Principal
from app.schemas.knowledge_bases import (
    KnowledgeBaseCreate,
    KnowledgeBaseDocumentCreate,
    KnowledgeBaseDocumentUpdate,
    KnowledgeBaseDocumentsReplace,
    KnowledgeBaseOut,
    KnowledgeBaseUpdate,
)
from app.services.knowledge_base_service import (
    add_knowledge_base_document,
    delete_knowledge_base,
    delete_knowledge_base_document,
    get_knowledge_base_or_404,
    list_knowledge_bases,
    replace_knowledge_base_documents_for_id,
    serialize_knowledge_base,
    update_knowledge_base,
    update_knowledge_base_document,
    create_knowledge_base,
)


router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/knowledge-bases", tags=["knowledge-bases"])


@router.post("", response_model=KnowledgeBaseOut)
def create_knowledge_base_endpoint(
    workspace_id: str,
    payload: KnowledgeBaseCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    knowledge_base = create_knowledge_base(db, principal, workspace_id, payload)
    return serialize_knowledge_base(knowledge_base)


@router.get("", response_model=list[KnowledgeBaseOut])
def list_knowledge_bases_endpoint(
    workspace_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    return [serialize_knowledge_base(knowledge_base) for knowledge_base in list_knowledge_bases(db, principal, workspace_id)]


@router.get("/{knowledge_base_id}", response_model=KnowledgeBaseOut)
def get_knowledge_base_endpoint(
    workspace_id: str,
    knowledge_base_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    knowledge_base = get_knowledge_base_or_404(db, principal, workspace_id, knowledge_base_id)
    return serialize_knowledge_base(knowledge_base)


@router.patch("/{knowledge_base_id}", response_model=KnowledgeBaseOut)
def patch_knowledge_base(
    workspace_id: str,
    knowledge_base_id: str,
    payload: KnowledgeBaseUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    knowledge_base = update_knowledge_base(db, principal, workspace_id, knowledge_base_id, payload)
    return serialize_knowledge_base(knowledge_base)


@router.delete("/{knowledge_base_id}", status_code=204)
def delete_knowledge_base_endpoint(
    workspace_id: str,
    knowledge_base_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
) -> Response:
    delete_knowledge_base(db, principal, workspace_id, knowledge_base_id)
    return Response(status_code=204)


@router.put("/{knowledge_base_id}/documents", response_model=KnowledgeBaseOut)
def replace_knowledge_base_documents_endpoint(
    workspace_id: str,
    knowledge_base_id: str,
    payload: KnowledgeBaseDocumentsReplace,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    knowledge_base = replace_knowledge_base_documents_for_id(
        db,
        principal,
        workspace_id,
        knowledge_base_id,
        payload.documents,
    )
    return serialize_knowledge_base(knowledge_base)


@router.post("/{knowledge_base_id}/documents", response_model=KnowledgeBaseOut)
def add_knowledge_base_document_endpoint(
    workspace_id: str,
    knowledge_base_id: str,
    payload: KnowledgeBaseDocumentCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    knowledge_base = add_knowledge_base_document(db, principal, workspace_id, knowledge_base_id, payload)
    return serialize_knowledge_base(knowledge_base)


@router.patch("/{knowledge_base_id}/documents/{document_id}", response_model=KnowledgeBaseOut)
def patch_knowledge_base_document_endpoint(
    workspace_id: str,
    knowledge_base_id: str,
    document_id: str,
    payload: KnowledgeBaseDocumentUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    knowledge_base = update_knowledge_base_document(db, principal, workspace_id, knowledge_base_id, document_id, payload)
    return serialize_knowledge_base(knowledge_base)


@router.delete("/{knowledge_base_id}/documents/{document_id}", status_code=204)
def delete_knowledge_base_document_endpoint(
    workspace_id: str,
    knowledge_base_id: str,
    document_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
) -> Response:
    delete_knowledge_base_document(db, principal, workspace_id, knowledge_base_id, document_id)
    return Response(status_code=204)
