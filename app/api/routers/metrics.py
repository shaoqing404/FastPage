from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models import ChatRun, Document, ParseJob, User


router = APIRouter(prefix="/api/v1/metrics", tags=["metrics"])


@router.get("/overview")
def overview(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant_id = current_user.tenant_id
    total_documents = db.scalar(select(func.count()).select_from(Document).where(Document.tenant_id == tenant_id)) or 0
    total_jobs = db.scalar(select(func.count()).select_from(ParseJob).where(ParseJob.tenant_id == tenant_id)) or 0
    total_runs = db.scalar(select(func.count()).select_from(ChatRun).where(ChatRun.tenant_id == tenant_id)) or 0
    return {
        "documents": total_documents,
        "parse_jobs": total_jobs,
        "chat_runs": total_runs,
    }
