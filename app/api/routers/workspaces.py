from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_principal
from app.core.db import get_db
from app.core.principal import Principal
from app.schemas.workspace_invites import (
    WorkspaceInviteCreateRequest,
    WorkspaceInviteOut,
)
from app.schemas.workspaces import (
    WorkspaceArchiveOut,
    WorkspaceFounderTransferRequest,
    WorkspaceFounderTransferResponse,
    WorkspaceMemberCreateRequest,
    WorkspaceMemberOut,
    WorkspaceMemberUpdateRequest,
)
from app.services.workspace_admin_service import (
    archive_workspace,
    create_workspace_member,
    list_workspace_members,
    remove_workspace_member,
    transfer_workspace_founder,
    update_workspace_member,
)
from app.services.workspace_invite_service import (
    create_workspace_invite,
    list_workspace_invites,
    revoke_workspace_invite,
)


router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}", tags=["workspaces"])


# ---------------------------------------------------------------------------
# Member management (E1 — unchanged)
# ---------------------------------------------------------------------------


@router.get("/members", response_model=list[WorkspaceMemberOut])
def list_workspace_members_endpoint(
    workspace_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    return list_workspace_members(db, principal, workspace_id)


@router.post("/members", response_model=WorkspaceMemberOut, status_code=status.HTTP_201_CREATED)
def create_workspace_member_endpoint(
    workspace_id: str,
    payload: WorkspaceMemberCreateRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    return create_workspace_member(db, principal, workspace_id, payload)


@router.patch("/members/{membership_id}", response_model=WorkspaceMemberOut)
def update_workspace_member_endpoint(
    workspace_id: str,
    membership_id: str,
    payload: WorkspaceMemberUpdateRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    return update_workspace_member(db, principal, workspace_id, membership_id, payload)


@router.delete("/members/{membership_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_workspace_member_endpoint(
    workspace_id: str,
    membership_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
) -> Response:
    remove_workspace_member(db, principal, workspace_id, membership_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Founder transfer & archive (E1 — unchanged)
# ---------------------------------------------------------------------------


@router.post("/founder-transfer", response_model=WorkspaceFounderTransferResponse)
def transfer_workspace_founder_endpoint(
    workspace_id: str,
    payload: WorkspaceFounderTransferRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    return transfer_workspace_founder(
        db,
        principal,
        workspace_id,
        target_user_id=payload.target_user_id,
    )


@router.post("/archive", response_model=WorkspaceArchiveOut)
def archive_workspace_endpoint(
    workspace_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    return archive_workspace(db, principal, workspace_id)


# ---------------------------------------------------------------------------
# Workspace invite management (E2 — new)
# ---------------------------------------------------------------------------


@router.get("/invites", response_model=list[WorkspaceInviteOut])
def list_workspace_invites_endpoint(
    workspace_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """List all invites for a workspace.

    Requires: founder / admin / platform-admin.
    """
    return list_workspace_invites(db, principal, workspace_id)


@router.post("/invites", response_model=WorkspaceInviteOut, status_code=status.HTTP_201_CREATED)
def create_workspace_invite_endpoint(
    workspace_id: str,
    payload: WorkspaceInviteCreateRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Create a workspace invite by email.

    Requires: founder / admin / platform-admin.
    founder may invite admin/member/guest.
    admin may invite member/guest only.
    Duplicate pending invite for the same normalized email returns 409.
    """
    return create_workspace_invite(db, principal, workspace_id, payload)


@router.post("/invites/{invite_id}/revoke", response_model=WorkspaceInviteOut)
def revoke_workspace_invite_endpoint(
    workspace_id: str,
    invite_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Revoke a pending workspace invite.

    Requires: founder / admin / platform-admin.
    Admin may only revoke member/guest invites.
    Only pending invites can be revoked; accepted/expired/revoked return 409.
    """
    return revoke_workspace_invite(db, principal, workspace_id, invite_id)

