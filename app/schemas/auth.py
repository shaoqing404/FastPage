from datetime import datetime

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class ContextSwitchRequest(BaseModel):
    workspace_id: str


class UserOut(BaseModel):
    id: str
    tenant_id: str
    workspace_id: str
    username: str
    membership_role: str
    tenant_membership_role: str
    tenant_membership_status: str
    workspace_membership_role: str
    workspace_membership_status: str


class WorkspaceOut(BaseModel):
    id: str
    tenant_id: str
    name: str
    slug: str
    status: str
    is_default: bool


class MembershipOut(BaseModel):
    id: str
    tenant_id: str
    role: str
    status: str


class WorkspaceMembershipOut(BaseModel):
    id: str
    workspace_id: str
    user_id: str
    role: str
    status: str
    permissions_override: dict[str, bool]
    permissions: dict[str, bool]


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
    workspace: WorkspaceOut
    tenant_membership: MembershipOut
    workspace_membership: WorkspaceMembershipOut
    memberships: list[MembershipOut]


class ApiKeyCreateRequest(BaseModel):
    name: str


class ApiKeyCreateResponse(BaseModel):
    id: str
    tenant_id: str
    workspace_id: str
    name: str
    key_prefix: str
    status: str
    created_at: datetime
    api_key: str


class ApiKeyOut(BaseModel):
    id: str
    tenant_id: str
    workspace_id: str | None
    name: str
    key_prefix: str
    status: str
    created_by: str
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
