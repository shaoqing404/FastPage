from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_principal
from app.core.db import get_db
from app.core.principal import Principal
from app.models import ChatRun, Document, ParseJob
from app.services.workspace_access_service import require_workspace_capability
from app.services.workspace_scope_service import get_workspace_visibility_filter


router = APIRouter(prefix="/api/v1/metrics", tags=["metrics"])


@router.get("/overview")
def overview(db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    require_workspace_capability(principal, "can_view_runs")

    tenant_id = principal.tenant_id

    total_documents = db.scalar(
        select(func.count()).select_from(Document).where(
            Document.tenant_id == tenant_id,
            get_workspace_visibility_filter(db, principal, Document),
        )
    ) or 0
    total_jobs = db.scalar(
        select(func.count()).select_from(ParseJob).where(
            ParseJob.tenant_id == tenant_id,
            get_workspace_visibility_filter(db, principal, ParseJob),
        )
    ) or 0
    total_runs = db.scalar(
        select(func.count()).select_from(ChatRun).where(
            ChatRun.tenant_id == tenant_id,
            get_workspace_visibility_filter(db, principal, ChatRun),
        )
    ) or 0

    return {
        "documents": total_documents,
        "parse_jobs": total_jobs,
        "chat_runs": total_runs,
    }
