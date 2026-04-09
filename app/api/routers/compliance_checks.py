from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_principal
from app.core.db import get_db
from app.core.principal import Principal
from app.schemas.compliance import ComplianceCheckCreate, ComplianceCheckOut, ComplianceCheckUpdate, ComplianceRunFromCheckCreate, ComplianceRunOut
from app.services.compliance_service import (
    create_compliance_check,
    create_compliance_run_from_check,
    delete_compliance_check,
    get_compliance_check_or_404,
    serialize_compliance_check,
    serialize_compliance_run,
    list_compliance_checks,
    update_compliance_check,
)


router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/compliance-checks", tags=["compliance-checks"])


@router.post("", response_model=ComplianceCheckOut)
def create_compliance_check_endpoint(
    workspace_id: str,
    payload: ComplianceCheckCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    check = create_compliance_check(db, principal, workspace_id, payload)
    return serialize_compliance_check(check)


@router.get("", response_model=list[ComplianceCheckOut])
def list_compliance_checks_endpoint(
    workspace_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    return [serialize_compliance_check(check) for check in list_compliance_checks(db, principal, workspace_id)]


@router.get("/{check_id}", response_model=ComplianceCheckOut)
def get_compliance_check_endpoint(
    workspace_id: str,
    check_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    return serialize_compliance_check(get_compliance_check_or_404(db, principal, workspace_id, check_id))


@router.patch("/{check_id}", response_model=ComplianceCheckOut)
def patch_compliance_check_endpoint(
    workspace_id: str,
    check_id: str,
    payload: ComplianceCheckUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    check = update_compliance_check(db, principal, workspace_id, check_id, payload)
    return serialize_compliance_check(check)


@router.delete("/{check_id}", status_code=204)
def delete_compliance_check_endpoint(
    workspace_id: str,
    check_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
) -> Response:
    delete_compliance_check(db, principal, workspace_id, check_id)
    return Response(status_code=204)


@router.post("/{check_id}/runs", response_model=ComplianceRunOut)
def create_compliance_run_from_check_endpoint(
    workspace_id: str,
    check_id: str,
    payload: ComplianceRunFromCheckCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    run = create_compliance_run_from_check(db, principal, workspace_id, check_id, payload)
    return serialize_compliance_run(run)
