from datetime import datetime
import hashlib
import uuid

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ChatMessage, ChatRun, ChatSkillDocument, Document, DocumentVersion, ParseJob, User
from app.services.storage_service import delete_document_tree, save_uploaded_pdf


def _hash_file(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_or_append_document(
    db: Session,
    user: User,
    file: UploadFile,
    document_id: str | None = None,
) -> tuple[Document, DocumentVersion]:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only PDF upload is supported")

    if document_id:
        document = db.get(Document, document_id)
        if document is None or document.tenant_id != user.tenant_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    else:
        document = Document(
            id=str(uuid.uuid4()),
            tenant_id=user.tenant_id,
            owner_user_id=user.id,
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
        tenant_id=user.tenant_id,
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


def restore_document_version(db: Session, user: User, document_id: str, version_id: str) -> Document:
    document = db.get(Document, document_id)
    version = db.get(DocumentVersion, version_id)
    if document is None or version is None or document.tenant_id != user.tenant_id or version.document_id != document.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document version not found")
    document.active_version_id = version.id
    document.status = version.parse_status
    document.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(document)
    return document


def delete_document(db: Session, user: User, document_id: str) -> None:
    document = db.get(Document, document_id)
    if document is None or document.tenant_id != user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    # Break the self-referential FK from documents.active_version_id before removing versions.
    document.active_version_id = None

    run_ids = list(
        db.scalars(
            select(ChatRun.id).where(
                ChatRun.tenant_id == user.tenant_id,
                ChatRun.document_id == document.id,
            )
        )
    )
    if run_ids:
        (
            db.query(ChatMessage)
            .filter(ChatMessage.tenant_id == user.tenant_id, ChatMessage.run_id.in_(run_ids))
            .update({"run_id": None}, synchronize_session=False)
        )

    db.query(ChatRun).filter(ChatRun.tenant_id == user.tenant_id, ChatRun.document_id == document.id).delete(synchronize_session=False)
    db.query(ParseJob).filter(ParseJob.tenant_id == user.tenant_id, ParseJob.document_id == document.id).delete(synchronize_session=False)
    db.query(ChatSkillDocument).filter(ChatSkillDocument.document_id == document.id).delete(synchronize_session=False)
    db.flush()
    db.query(DocumentVersion).filter(DocumentVersion.document_id == document.id).delete()
    db.delete(document)
    db.commit()
    delete_document_tree(user.tenant_id, document.id)
