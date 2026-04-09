from datetime import datetime
import json

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_principal
from app.core.db import get_db
from app.core.errors import AppError, ErrorCode
from app.core.principal import Principal
from app.models import Document, DocumentVersion, ParseJob
from app.schemas.documents import DocumentOut, DocumentVersionOut, ParseRequest, RestoreVersionResponse
from app.schemas.jobs import ParseJobOut
from app.services.audit_service import audit_from_principal
from app.services.document_service import (
    _document_workspace_filter,
    create_or_append_document,
    delete_document,
    get_document_or_404,
    restore_document_version,
)
from app.services.parse_service import schedule_parse_job
from app.core.config import default_llm_model, get_settings
from app.services.storage_service import read_json_artifact
import uuid


router = APIRouter(prefix="/api/v1/documents", tags=["documents"])
settings = get_settings()


@router.post("/upload")
def upload_document(
    request: Request,
    file: UploadFile = File(...),
    document_id: str | None = Form(default=None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    # ── Upload size guard ───────────────────────────────────────────────
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > settings.max_upload_bytes:
                raise AppError(
                    code=ErrorCode.UPLOAD_TOO_LARGE,
                    message=f"Upload exceeds maximum allowed size ({settings.max_upload_bytes} bytes)",
                    status_code=413,
                )
        except ValueError:
            pass  # Malformed Content-Length — let the framework handle it.

    document, version = create_or_append_document(db, principal, file, document_id=document_id)
    audit_from_principal(
        db, principal, "document.upload",
        target_type="document", target_id=document.id,
        meta={"version_id": version.id, "filename": file.filename},
    )
    db.commit()
    return {
        "document_id": document.id,
        "version_id": version.id,
        "status": version.parse_status,
    }


@router.get("", response_model=list[DocumentOut])
def list_documents(db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    workspace_filter = Document.workspace_id == principal.workspace_id
    if db.scalar(
        select(Document.id).where(
            Document.tenant_id == principal.tenant_id,
            Document.workspace_id.is_(None),
        ).limit(1)
    ) is not None:
        workspace_filter = _document_workspace_filter(db, principal)
    docs = db.scalars(
        select(Document)
        .where(Document.tenant_id == principal.tenant_id, workspace_filter)
        .order_by(Document.created_at.desc())
    ).all()
    return docs


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(document_id: str, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    return get_document_or_404(db, principal, document_id)


@router.get("/{document_id}/versions", response_model=list[DocumentVersionOut])
def list_versions(document_id: str, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    document = get_document_or_404(db, principal, document_id)
    versions = db.scalars(
        select(DocumentVersion).where(DocumentVersion.document_id == document_id).order_by(DocumentVersion.version_no.desc())
    ).all()
    return versions


@router.get("/{document_id}/versions/{version_id}", response_model=DocumentVersionOut)
def get_version(document_id: str, version_id: str, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    document = get_document_or_404(db, principal, document_id)
    version = db.get(DocumentVersion, version_id)
    if version is None or version.document_id != document.id:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document version not found")
    return version


def _create_parse_job(db: Session, principal: Principal, document: Document, version: DocumentVersion, model: str | None) -> ParseJob:
    now = datetime.utcnow()
    job = ParseJob(
        id=str(uuid.uuid4()),
        tenant_id=principal.tenant_id,
        workspace_id=document.workspace_id or principal.workspace_id,
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


def _resolve_version(db: Session, principal: Principal, document_id: str, version_id: str | None):
    document = get_document_or_404(db, principal, document_id)
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
async def parse_document(document_id: str, payload: ParseRequest, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    document, version = _resolve_version(db, principal, document_id, payload.version_id)
    job = _create_parse_job(db, principal, document, version, payload.model)
    schedule_parse_job(job.id)
    return job


@router.post("/{document_id}/reparse", response_model=ParseJobOut)
async def reparse_document(document_id: str, payload: ParseRequest, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    document, version = _resolve_version(db, principal, document_id, payload.version_id)
    job = _create_parse_job(db, principal, document, version, payload.model)
    schedule_parse_job(job.id)
    return job


@router.post("/{document_id}/versions/{version_id}/restore", response_model=RestoreVersionResponse)
def restore_version(document_id: str, version_id: str, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    document = restore_document_version(db, principal, document_id, version_id)
    return RestoreVersionResponse(document_id=document.id, active_version_id=document.active_version_id)


@router.get("/{document_id}/structure")
def get_structure(document_id: str, version_id: str | None = None, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    _, version = _resolve_version(db, principal, document_id, version_id)
    if not version.parsed_structure_path:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Document has no parsed structure yet")
    return read_json_artifact(version.parsed_structure_path)


@router.delete("/{document_id}", status_code=204)
def delete_document_endpoint(document_id: str, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)) -> Response:
    audit_from_principal(
        db, principal, "document.delete",
        target_type="document", target_id=document_id,
    )
    delete_document(db, principal, document_id)
    return Response(status_code=204)

