from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Shared type aliases
# ---------------------------------------------------------------------------

InviteRole = Literal["admin", "member", "guest"]
InviteStatus = Literal["pending", "accepted", "expired", "revoked"]


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class WorkspaceInviteCreateRequest(BaseModel):
    """Payload for POST /api/v1/workspaces/{workspace_id}/invites."""

    email: str
    role: InviteRole = "member"
    permissions_override: dict[str, bool] | None = None
    # expires_at is optional; service will supply a default if absent
    expires_at: datetime | None = None


class WorkspaceInviteRevokeRequest(BaseModel):
    """Payload for POST /api/v1/workspaces/{workspace_id}/invites/{invite_id}/revoke.

    Currently no extra fields required; kept as a body model for future use.
    """

    pass


# ---------------------------------------------------------------------------
# Response shapes
# ---------------------------------------------------------------------------


class WorkspaceInviteOut(BaseModel):
    """Full invite resource as returned by list / create / revoke / accept."""

    id: str
    workspace_id: str
    email: str
    role: str
    status: str
    permissions_override: dict[str, bool]
    invited_by: str
    accepted_user_id: str | None
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Accept response — includes full auth handoff so caller can immediately use
# the new token for the target tenant/workspace without a separate login.
# ---------------------------------------------------------------------------


class InviteAcceptWorkspaceOut(BaseModel):
    id: str
    tenant_id: str
    name: str
    slug: str
    status: str
    is_default: bool


class InviteAcceptTenantMembershipOut(BaseModel):
    id: str
    tenant_id: str
    role: str
    status: str


class InviteAcceptWorkspaceMembershipOut(BaseModel):
    id: str
    workspace_id: str
    user_id: str
    role: str
    status: str
    permissions_override: dict[str, bool]
    permissions: dict[str, bool]


class WorkspaceInviteAcceptOut(BaseModel):
    """Response for POST /api/v1/workspace-invites/{invite_id}/accept.

    Returns:
      - invite           : updated invite resource (status=accepted)
      - access_token     : new bearer token scoped to the target tenant/workspace
      - token_type       : "bearer"
      - workspace        : target workspace info
      - tenant_membership: resolved active tenant membership in the target tenant
      - workspace_membership: resolved active workspace membership

    The caller should replace their current token with ``access_token`` to
    immediately enter the target tenant/workspace without a separate
    context/switch call.
    """

    invite: WorkspaceInviteOut
    access_token: str
    token_type: str = "bearer"
    workspace: InviteAcceptWorkspaceOut
    tenant_membership: InviteAcceptTenantMembershipOut
    workspace_membership: InviteAcceptWorkspaceMembershipOut
