from datetime import datetime
import json

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models import Document, DocumentVersion, ParseJob, User
from app.schemas.documents import DocumentOut, DocumentVersionOut, ParseRequest, RestoreVersionResponse
from app.schemas.jobs import ParseJobOut
from app.services.document_service import create_or_append_document, delete_document, restore_document_version
from app.services.parse_service import schedule_parse_job
from app.core.config import default_llm_model, get_settings
from app.services.storage_service import read_json_artifact
import uuid


router = APIRouter(prefix="/api/v1/documents", tags=["documents"])
settings = get_settings()


@router.post("/upload")
def upload_document(
    file: UploadFile = File(...),
    document_id: str | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    document, version = create_or_append_document(db, current_user, file, document_id=document_id)
    return {
        "document_id": document.id,
        "version_id": version.id,
        "status": version.parse_status,
    }


@router.get("", response_model=list[DocumentOut])
def list_documents(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    docs = db.scalars(select(Document).where(Document.tenant_id == current_user.tenant_id).order_by(Document.created_at.desc())).all()
    return docs


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(document_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    document = db.get(Document, document_id)
    if document is None or document.tenant_id != current_user.tenant_id:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return document


@router.get("/{document_id}/versions", response_model=list[DocumentVersionOut])
def list_versions(document_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    document = db.get(Document, document_id)
    if document is None or document.tenant_id != current_user.tenant_id:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    versions = db.scalars(
        select(DocumentVersion).where(DocumentVersion.document_id == document_id).order_by(DocumentVersion.version_no.desc())
    ).all()
    return versions


@router.get("/{document_id}/versions/{version_id}", response_model=DocumentVersionOut)
def get_version(document_id: str, version_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    document = db.get(Document, document_id)
    version = db.get(DocumentVersion, version_id)
    if document is None or version is None or document.tenant_id != current_user.tenant_id or version.document_id != document.id:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document version not found")
    return version


def _create_parse_job(db: Session, current_user: User, document: Document, version: DocumentVersion, model: str | None) -> ParseJob:
    now = datetime.utcnow()
    job = ParseJob(
        id=str(uuid.uuid4()),
        tenant_id=current_user.tenant_id,
        document_id=document.id,
        version_id=version.id,
        model=model or default_llm_model(),
        status="uploaded",
        current_step="uploaded",
        progress_percent=0,
        created_at=now,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _resolve_version(db: Session, current_user: User, document_id: str, version_id: str | None):
    document = db.get(Document, document_id)
    if document is None or document.tenant_id != current_user.tenant_id:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    target_version_id = version_id or document.active_version_id
    if target_version_id is None:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Document has no active version")
    version = db.get(DocumentVersion, target_version_id)
    if version is None or version.document_id != document.id:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document version not found")
    return document, version


@router.post("/{document_id}/parse", response_model=ParseJobOut)
async def parse_document(document_id: str, payload: ParseRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    document, version = _resolve_version(db, current_user, document_id, payload.version_id)
    job = _create_parse_job(db, current_user, document, version, payload.model)
    schedule_parse_job(job.id)
    return job


@router.post("/{document_id}/reparse", response_model=ParseJobOut)
async def reparse_document(document_id: str, payload: ParseRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    document, version = _resolve_version(db, current_user, document_id, payload.version_id)
    job = _create_parse_job(db, current_user, document, version, payload.model)
    schedule_parse_job(job.id)
    return job


@router.post("/{document_id}/versions/{version_id}/restore", response_model=RestoreVersionResponse)
def restore_version(document_id: str, version_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    document = restore_document_version(db, current_user, document_id, version_id)
    return RestoreVersionResponse(document_id=document.id, active_version_id=document.active_version_id)


@router.get("/{document_id}/structure")
def get_structure(document_id: str, version_id: str | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _, version = _resolve_version(db, current_user, document_id, version_id)
    if not version.parsed_structure_path:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Document has no parsed structure yet")
    return read_json_artifact(version.parsed_structure_path)


@router.delete("/{document_id}", status_code=204)
def delete_document_endpoint(document_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> Response:
    delete_document(db, current_user, document_id)
    return Response(status_code=204)
