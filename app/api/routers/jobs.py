from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models import ParseJob, User


router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


@router.get("")
def list_jobs(document_id: str | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    stmt = select(ParseJob).where(ParseJob.tenant_id == current_user.tenant_id)
    if document_id:
        stmt = stmt.where(ParseJob.document_id == document_id)
    jobs = db.scalars(stmt.order_by(ParseJob.created_at.desc())).all()
    return jobs


@router.get("/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    job = db.get(ParseJob, job_id)
    if job is None or job.tenant_id != current_user.tenant_id:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job
