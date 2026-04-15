from datetime import datetime
from typing import Literal

from pydantic import BaseModel


WorkspaceMembershipRole = Literal["founder", "admin", "member", "guest"]
WorkspaceMembershipStatus = Literal["active", "disabled", "removed"]


class WorkspaceMemberOut(BaseModel):
    id: str
    workspace_id: str
    user_id: str
    email: str | None
    role: WorkspaceMembershipRole
    status: WorkspaceMembershipStatus
    permissions_override: dict[str, bool]
    created_at: datetime
    updated_at: datetime


class WorkspaceMemberCreateRequest(BaseModel):
    user_id: str
    role: WorkspaceMembershipRole = "member"
    permissions_override: dict[str, bool] | None = None


class WorkspaceMemberUpdateRequest(BaseModel):
    role: WorkspaceMembershipRole | None = None
    status: WorkspaceMembershipStatus | None = None
    permissions_override: dict[str, bool] | None = None


class WorkspaceFounderTransferRequest(BaseModel):
    target_user_id: str


class WorkspaceFounderTransferResponse(BaseModel):
    workspace_id: str
    founder_membership: WorkspaceMemberOut
    previous_founder_membership: WorkspaceMemberOut


class WorkspaceArchiveOut(BaseModel):
    id: str
    tenant_id: str
    name: str
    slug: str
    status: str
    is_default: bool
    archived_at: datetime | None
    archived_by: str | None
    created_at: datetime
    updated_at: datetime
