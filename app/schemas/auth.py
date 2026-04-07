from datetime import datetime

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: str
    tenant_id: str
    username: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class ApiKeyCreateRequest(BaseModel):
    name: str


class ApiKeyCreateResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    key_prefix: str
    status: str
    created_at: datetime
    api_key: str


class ApiKeyOut(BaseModel):
    id: str
    tenant_id: str
    name: str
    key_prefix: str
    status: str
    created_by: str
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
