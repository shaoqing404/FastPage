"""workspace_invites.py

Router for invite actions that are NOT scoped to the workspace admin plane.

Currently contains only:
  POST /api/v1/workspace-invites/{invite_id}/accept

Auth model for accept:
  - Bearer session token ONLY (no API key).
  - Resolves the logged-in user via ``get_session_user``.
  - Does NOT use ``get_current_principal()`` — accept must succeed even when
    the user has no workspace or tenant membership yet.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_session_user
from app.core.db import get_db
from app.models import User
from app.schemas.workspace_invites import WorkspaceInviteAcceptOut
from app.services.workspace_invite_service import accept_workspace_invite


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
