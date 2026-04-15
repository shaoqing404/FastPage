from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_principal
from app.core.db import get_db
from app.core.principal import Principal
from app.models import ParseJob
from app.services.workspace_access_service import require_workspace_capability
from app.services.workspace_scope_service import get_workspace_visibility_filter


router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


@router.get("")
def list_jobs(
    document_id: str | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    require_workspace_capability(principal, "can_view_runs")
    stmt = select(ParseJob).where(
        ParseJob.tenant_id == principal.tenant_id,
        get_workspace_visibility_filter(db, principal, ParseJob),
    )
    if document_id:
        stmt = stmt.where(ParseJob.document_id == document_id)
    jobs = db.scalars(stmt.order_by(ParseJob.created_at.desc())).all()
    return jobs


@router.get("/{job_id}")
def get_job(
    job_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    require_workspace_capability(principal, "can_view_runs")
    job = db.scalar(
        select(ParseJob).where(
            ParseJob.id == job_id,
            ParseJob.tenant_id == principal.tenant_id,
            get_workspace_visibility_filter(db, principal, ParseJob),
        )
    )
    if job is None:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job
