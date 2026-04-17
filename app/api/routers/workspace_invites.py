"""workspace_invites.py

Router for invite actions that are NOT scoped to the workspace admin plane.

Contains:
  POST /api/v1/workspace-invites/{invite_id}/accept
  GET  /api/v1/workspace-invites/{invite_id}/preview   (public, no auth)
  POST /api/v1/workspace-invites/{invite_id}/claim     (public, no auth)

Auth model for accept:
  - Bearer session token ONLY (no API key).
  - Resolves the logged-in user via ``get_session_user``.
  - Does NOT use ``get_current_principal()`` — accept must succeed even when
    the user has no workspace or tenant membership yet.

Auth model for preview / claim:
  - No authentication required.
  - The invite UUID itself serves as a bearer-like credential.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_session_user
from app.core.db import get_db
from app.models import User
from app.schemas.workspace_invites import (
    InviteClaimRequest,
    InvitePreviewResponse,
    WorkspaceInviteAcceptOut,
)
from app.services.workspace_invite_service import (
    accept_workspace_invite,
    claim_workspace_invite,
    preview_workspace_invite,
)


router = APIRouter(prefix="/api/v1/workspace-invites", tags=["workspace-invites"])


@router.post("/{invite_id}/accept", response_model=WorkspaceInviteAcceptOut)
def accept_workspace_invite_endpoint(
    invite_id: str,
    db: Session = Depends(get_db),
    session_user: User = Depends(get_session_user),
):
    """Accept a workspace invite.

    The caller must be authenticated via a bearer session token. The
    logged-in user's normalized email must match the invite's target email.
    """
    return accept_workspace_invite(db, session_user, invite_id)


@router.get("/{invite_id}/preview", response_model=InvitePreviewResponse)
def preview_workspace_invite_endpoint(
    invite_id: str,
    db: Session = Depends(get_db),
):
    """Return a desensitized preview of an invite for unauthenticated users.

    No authentication is required. Returns minimal information about the
    invite (workspace name, role, masked email) to render the claim form.
    """
    return preview_workspace_invite(db, invite_id)


@router.post("/{invite_id}/claim")
def claim_workspace_invite_endpoint(
    invite_id: str,
    payload: InviteClaimRequest,
    db: Session = Depends(get_db),
):
    """Claim an invite by setting a password and optionally a username.

    No authentication is required — the invite UUID itself is the credential.
    If the invite email has no corresponding User, one is auto-created.
    Returns a full auth handoff response (token + workspace + memberships).
    """
    return claim_workspace_invite(
        db,
        invite_id,
        password=payload.password,
        username=payload.username,
    )
