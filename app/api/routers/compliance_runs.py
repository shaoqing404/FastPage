from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_principal
from app.core.db import get_db
from app.core.principal import Principal
from app.schemas.compliance import ComplianceRunCreate, ComplianceRunOut
from app.services.compliance_service import (
    create_compliance_run,
    get_compliance_run_or_404,
    list_compliance_runs,
    serialize_compliance_run,
)


router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/compliance-runs", tags=["compliance-runs"])


@router.post("", response_model=ComplianceRunOut)
def create_compliance_run_endpoint(
    workspace_id: str,
    payload: ComplianceRunCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    run = create_compliance_run(db, principal, workspace_id, payload)
    return serialize_compliance_run(run)


@router.get("", response_model=list[ComplianceRunOut])
def list_compliance_runs_endpoint(
    workspace_id: str,
    status: str | None = None,
    compliance_check_id: str | None = None,
    mode: str | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    runs = list_compliance_runs(
        db,
        principal,
        workspace_id,
        status_value=status,
        compliance_check_id=compliance_check_id,
        mode=mode,
        created_after=created_after,
        created_before=created_before,
    )
    return [serialize_compliance_run(run) for run in runs]


@router.get("/{run_id}", response_model=ComplianceRunOut)
def get_compliance_run_endpoint(
    workspace_id: str,
    run_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    return serialize_compliance_run(get_compliance_run_or_404(db, principal, workspace_id, run_id))
