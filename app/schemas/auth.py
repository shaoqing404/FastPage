from datetime import datetime

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: str
    tenant_id: str
    workspace_id: str
    username: str
    membership_role: str


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


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
    workspace: WorkspaceOut
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
