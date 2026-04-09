import asyncio
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import default_llm_model, get_settings
from app.core.db import SessionLocal
from app.models import Document, DocumentVersion, ParseJob
from app.services.pageindex_service import parse_pdf_to_structure_async
from app.services.storage_service import local_artifact_path, write_document_structure
from app.services.task_queue_service import enqueue_parse_job


settings = get_settings()


def _job_update(
    db: Session,
    job: ParseJob,
    *,
    status: str,
    current_step: str,
    progress_percent: int,
    error_message: str | None = None,
) -> None:
    job.status = status
    job.current_step = current_step
    job.progress_percent = progress_percent
    job.error_message = error_message
    if status == "parsing" and job.started_at is None:
        job.started_at = datetime.utcnow()
    if status in {"index_ready", "failed"}:
        job.finished_at = datetime.utcnow()
        if job.started_at:
            job.duration_ms = int((job.finished_at - job.started_at).total_seconds() * 1000)
    db.commit()


async def run_parse_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(ParseJob, job_id)
        if job is None:
            return
        version = db.get(DocumentVersion, job.version_id)
        document = db.get(Document, job.document_id)
        if version is None or document is None:
            _job_update(db, job, status="failed", current_step="missing_artifacts", progress_percent=100, error_message="Document version not found")
            return

        _job_update(db, job, status="queued", current_step="queued", progress_percent=5)
        version.parse_status = "queued"
        document.status = "queued"
        db.commit()

        _job_update(db, job, status="parsing", current_step="parsing_pdf", progress_percent=25)
        version.parse_status = "parsing"
        document.status = "parsing"
        db.commit()

        with local_artifact_path(version.storage_path) as pdf_path:
            result = await parse_pdf_to_structure_async(str(pdf_path), job.model or default_llm_model())
        structure_path = write_document_structure(
            tenant_id=job.tenant_id,
            document_id=document.id,
            version_id=version.id,
            data=result,
        )

        version.parsed_structure_path = str(structure_path)
        version.parse_status = "index_ready"
        version.parse_error = None
        document.status = "index_ready"
        document.active_version_id = version.id
        document.updated_at = datetime.utcnow()
        db.commit()

        _job_update(db, job, status="index_ready", current_step="index_ready", progress_percent=100)
    except Exception as exc:
        db.rollback()
        job = db.get(ParseJob, job_id)
        if job is not None:
            _job_update(db, job, status="failed", current_step="failed", progress_percent=100, error_message=str(exc))
        version = db.get(DocumentVersion, job.version_id) if job else None
        document = db.get(Document, job.document_id) if job else None
        if version is not None:
            version.parse_status = "failed"
            version.parse_error = str(exc)
        if document is not None:
            document.status = "failed"
            document.updated_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()


def schedule_parse_job(job_id: str) -> None:
    enqueue_parse_job(job_id)
