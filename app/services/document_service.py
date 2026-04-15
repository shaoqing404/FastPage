from datetime import datetime
import hashlib
import uuid

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.principal import Principal
from app.models import ChatMessage, ChatRun, ChatSkillDocument, Document, DocumentVersion, KnowledgeBaseDocument, ParseJob, Workspace
from app.services.storage_service import delete_document_tree, save_uploaded_pdf


def _hash_file(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


from app.services.workspace_scope_service import get_workspace_visibility_filter


def list_accessible_documents_by_ids(db: Session, principal: Principal, document_ids: list[str]) -> list[Document]:
    if not document_ids:
        return []
    return db.scalars(
        select(Document).where(
            Document.id.in_(document_ids),
            Document.tenant_id == principal.tenant_id,
            get_workspace_visibility_filter(db, principal, Document),
        )
    ).all()


def get_document_or_404(db: Session, principal: Principal, document_id: str) -> Document:
    document = db.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.tenant_id == principal.tenant_id,
            get_workspace_visibility_filter(db, principal, Document),
        )
    )
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return document


# PDF magic bytes: every valid PDF starts with "%PDF-"
_PDF_MAGIC = b"%PDF-"


def _validate_pdf_magic_bytes(file: UploadFile) -> None:
    """Peek at the first 5 bytes to verify PDF magic.  Rewinds the file."""
    header = file.file.read(len(_PDF_MAGIC))
    file.file.seek(0)
    if header[:len(_PDF_MAGIC)] != _PDF_MAGIC:
        raise AppError(
            code=ErrorCode.UPLOAD_INVALID_FILE,
            message="File content is not a valid PDF (magic bytes mismatch)",
            status_code=400,
        )


def create_or_append_document(
    db: Session,
    principal: Principal,
    file: UploadFile,
    document_id: str | None = None,
) -> tuple[Document, DocumentVersion]:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise AppError(
            code=ErrorCode.UPLOAD_INVALID_FILE,
            message="Only PDF upload is supported",
            status_code=400,
        )

    # Validate PDF content before persisting.
    _validate_pdf_magic_bytes(file)

    if document_id:
        document = get_document_or_404(db, principal, document_id)
        if document.workspace_id is None:
            document.workspace_id = principal.workspace_id
    else:
        document = Document(
            id=str(uuid.uuid4()),
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            owner_user_id=principal.user_id,
            display_name=file.filename,
            source_filename=file.filename,
            status="uploaded",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(document)
        db.flush()

    current_max = db.scalar(select(func.max(DocumentVersion.version_no)).where(DocumentVersion.document_id == document.id)) or 0
    version = DocumentVersion(
        id=str(uuid.uuid4()),
        document_id=document.id,
        version_no=int(current_max) + 1,
        storage_path="",
        file_hash="",
        parse_status="uploaded",
    )
    db.add(version)
    db.flush()

    storage_uri = save_uploaded_pdf(
        file,
        tenant_id=principal.tenant_id,
        document_id=document.id,
        version_id=version.id,
    )
    version.storage_path = storage_uri
    if storage_uri.startswith("minio://"):
        version.file_hash = f"remote:{version.id}"
    else:
        version.file_hash = _hash_file(storage_uri)

    document.active_version_id = version.id
    document.status = "uploaded"
    document.display_name = file.filename if not document.display_name else document.display_name
    document.source_filename = file.filename
    document.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(document)
    db.refresh(version)
    return document, version


def restore_document_version(db: Session, principal: Principal, document_id: str, version_id: str) -> Document:
    document = get_document_or_404(db, principal, document_id)
    version = db.get(DocumentVersion, version_id)
    if version is None or version.document_id != document.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document version not found")
    document.active_version_id = version.id
    document.status = version.parse_status
    document.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(document)
    return document


def delete_document(db: Session, principal: Principal, document_id: str) -> None:
    document = get_document_or_404(db, principal, document_id)

    # Break the self-referential FK from documents.active_version_id before removing versions.
    document.active_version_id = None

    run_ids = list(
        db.scalars(
            select(ChatRun.id).where(
                ChatRun.tenant_id == principal.tenant_id,
                ChatRun.document_id == document.id,
            )
        )
    )
    if run_ids:
        (
            db.query(ChatMessage)
            .filter(ChatMessage.tenant_id == principal.tenant_id, ChatMessage.run_id.in_(run_ids))
            .update({"run_id": None}, synchronize_session=False)
        )

    db.query(ChatRun).filter(ChatRun.tenant_id == principal.tenant_id, ChatRun.document_id == document.id).delete(synchronize_session=False)
    db.query(ParseJob).filter(ParseJob.tenant_id == principal.tenant_id, ParseJob.document_id == document.id).delete(synchronize_session=False)
    db.query(ChatSkillDocument).filter(ChatSkillDocument.document_id == document.id).delete(synchronize_session=False)
    db.query(KnowledgeBaseDocument).filter(KnowledgeBaseDocument.document_id == document.id).delete(synchronize_session=False)
    db.flush()
    db.query(DocumentVersion).filter(DocumentVersion.document_id == document.id).delete()
    db.delete(document)
    db.commit()
    delete_document_tree(principal.tenant_id, document.id)
