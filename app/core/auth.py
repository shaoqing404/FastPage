from datetime import datetime, timedelta, timezone
import base64
import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass

import jwt
from fastapi import HTTPException, status
from fastapi.security import APIKeyHeader
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.principal import Principal
from app.models import ApiKey, RevokedToken, TenantMembership, User, Workspace, WorkspaceMembership
from app.services.workspace_access_service import resolve_workspace_capabilities
from app.services.workspace_membership_service import (
    resolve_active_tenant_membership,
    resolve_active_workspace_membership_context,
    resolve_workspace_tenant_id_hint,
)


settings = get_settings()
bearer_scheme = HTTPBearer(auto_error=False)
api_key_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)
PBKDF2_SCHEME = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 600_000


@dataclass
class AuthContext:
    user: User
    tenant_id: str
    workspace: Workspace
    tenant_membership: TenantMembership
    workspace_membership: WorkspaceMembership
    workspace_permissions: dict[str, bool]

    @property
    def membership(self) -> TenantMembership:
        return self.tenant_membership


@dataclass
class ActiveTenantContext:
    user: User
    tenant_membership: TenantMembership
    api_key: ApiKey | None = None

    @property
    def tenant_id(self) -> str:
        return self.tenant_membership.tenant_id


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return (
        f"{PBKDF2_SCHEME}${PBKDF2_ITERATIONS}$"
        f"{base64.urlsafe_b64encode(salt).decode('ascii')}$"
        f"{base64.urlsafe_b64encode(digest).decode('ascii')}"
    )


def _verify_password_hash(stored_hash: str, password: str) -> bool:
    try:
        scheme, iterations_text, salt_b64, digest_b64 = stored_hash.split("$", 3)
        if scheme != PBKDF2_SCHEME:
            return False
        salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
        expected_digest = base64.urlsafe_b64decode(digest_b64.encode("ascii"))
        actual_digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations_text))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(expected_digest, actual_digest)


def verify_password(password: str, stored_hash: str) -> bool:
    if stored_hash.startswith(f"{PBKDF2_SCHEME}$"):
        return _verify_password_hash(stored_hash, password)
    return hmac.compare_digest(stored_hash, password)


def is_legacy_password_hash(stored_hash: str) -> bool:
    return not stored_hash.startswith(f"{PBKDF2_SCHEME}$")


def is_legacy_bootstrap_admin(user: User) -> bool:
    return user.id == "user_default" and user.username == settings.admin_username


def verify_legacy_bootstrap_admin_password(user: User, password: str) -> bool:
    if not is_legacy_bootstrap_admin(user) or not is_legacy_password_hash(user.password_hash):
        return False
    return hmac.compare_digest(user.password_hash, password) or hmac.compare_digest(settings.admin_password, password)


def resolve_auth_context(
    db: Session,
    user: User,
    *,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
) -> AuthContext:
    tenant_hint = tenant_id
    if tenant_hint is None and workspace_id is not None:
        tenant_hint = resolve_workspace_tenant_id_hint(db, workspace_id)

    tenant_membership = resolve_active_tenant_membership(
        db,
        user.id,
        tenant_id=tenant_hint,
        fallback_tenant_id=user.tenant_id or None,
    )
    workspace_context = resolve_active_workspace_membership_context(
        db,
        user.id,
        tenant_membership.tenant_id,
        workspace_id=workspace_id,
    )
    workspace_permissions = resolve_workspace_capabilities(
        workspace_context.membership.role,
        workspace_context.membership.permissions_override_json,
    )

    return AuthContext(
        user=user,
        tenant_id=tenant_membership.tenant_id,
        workspace=workspace_context.workspace,
        tenant_membership=tenant_membership,
        workspace_membership=workspace_context.membership,
        workspace_permissions=workspace_permissions,
    )


def verify_login(db: Session, username: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.username == username))
    if not user or not user.is_active:
        return None
    if verify_password(password, user.password_hash):
        if is_legacy_password_hash(user.password_hash):
            user.password_hash = hash_password(password)
            db.commit()
        return user
    if not verify_legacy_bootstrap_admin_password(user, password):
        return None
    user.password_hash = hash_password(password)
    db.commit()
    return user


def create_access_token(context: AuthContext, expires_minutes: int = 720) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": context.user.id,
        "username": context.user.username,
        "tenant_id": context.tenant_id,
        "workspace_id": context.workspace.id,
        "membership_role": context.workspace_membership.role,
        "tenant_membership_role": context.tenant_membership.role,
        "workspace_membership_role": context.workspace_membership.role,
        "workspace_membership_id": context.workspace_membership.id,
        "jti": str(uuid.uuid4()),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=expires_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc


def revoke_token(db: Session, token: str) -> None:
    payload = decode_access_token(token)
    jti = payload["jti"]
    if db.get(RevokedToken, jti) is None:
        db.add(RevokedToken(jti=jti))
        db.commit()


def require_user(db: Session, credentials: HTTPAuthorizationCredentials | None) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    payload = decode_access_token(credentials.credentials)
    jti = payload["jti"]
    if db.get(RevokedToken, jti) is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked")

    user = db.get(User, payload["sub"])
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def _resolve_session_tenant_hint(
    db: Session,
    payload: dict,
) -> str | None:
    tenant_hint = payload.get("tenant_id")
    if tenant_hint is not None:
        return tenant_hint

    workspace_id = payload.get("workspace_id")
    if workspace_id is None:
        return None
    return resolve_workspace_tenant_id_hint(db, workspace_id)


def require_active_tenant_context(
    db: Session,
    credentials: HTTPAuthorizationCredentials | None,
    api_key_value: str | None,
) -> ActiveTenantContext:
    if credentials is not None:
        user = require_user(db, credentials)
        payload = decode_access_token(credentials.credentials)
        tenant_membership = resolve_active_tenant_membership(
            db,
            user.id,
            tenant_id=_resolve_session_tenant_hint(db, payload),
            fallback_tenant_id=user.tenant_id or None,
        )
        return ActiveTenantContext(
            user=user,
            tenant_membership=tenant_membership,
        )

    if api_key_value:
        matched_key, user = require_api_key_owner(db, api_key_value)
        tenant_membership = resolve_active_tenant_membership(
            db,
            user.id,
            tenant_id=matched_key.tenant_id,
        )
        matched_key.last_used_at = datetime.utcnow()
        db.commit()
        return ActiveTenantContext(
            user=user,
            tenant_membership=tenant_membership,
            api_key=matched_key,
        )

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing credentials")


def require_active_session_tenant_context(
    db: Session,
    credentials: HTTPAuthorizationCredentials | None,
) -> ActiveTenantContext:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    user = require_user(db, credentials)
    payload = decode_access_token(credentials.credentials)
    tenant_membership = resolve_active_tenant_membership(
        db,
        user.id,
        tenant_id=_resolve_session_tenant_hint(db, payload),
        fallback_tenant_id=user.tenant_id or None,
    )
    return ActiveTenantContext(
        user=user,
        tenant_membership=tenant_membership,
    )


def _hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(f"{settings.secret_key}:{raw_key}".encode("utf-8")).hexdigest()


def generate_api_key_value() -> tuple[str, str]:
    raw = f"pidx_{secrets.token_urlsafe(32)}"
    return raw, _hash_api_key(raw)


def get_api_key_prefix(raw_key: str) -> str:
    return raw_key[:12]


def require_api_key_owner(db: Session, api_key_value: str) -> tuple[ApiKey, User]:
    hashed = _hash_api_key(api_key_value)
    stmt = select(ApiKey).where(ApiKey.status == "active", ApiKey.revoked_at.is_(None))
    keys = db.scalars(stmt).all()
    matched_key = next((item for item in keys if hmac.compare_digest(item.key_hash, hashed)), None)
    if matched_key is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    user = db.get(User, matched_key.created_by)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key owner is invalid")

    return matched_key, user


def require_principal(
    db: Session,
    credentials: HTTPAuthorizationCredentials | None,
    api_key_value: str | None,
) -> Principal:
    if credentials is not None:
        user = require_user(db, credentials)
        payload = decode_access_token(credentials.credentials)
        context = resolve_auth_context(
            db,
            user,
            tenant_id=payload.get("tenant_id"),
            workspace_id=payload.get("workspace_id"),
        )
        return Principal(
            kind="session",
            tenant_id=context.tenant_id,
            workspace_id=context.workspace.id,
            tenant_membership_role=context.tenant_membership.role,
            tenant_membership_status=context.tenant_membership.status,
            workspace_membership_role=context.workspace_membership.role,
            workspace_membership_status=context.workspace_membership.status,
            workspace_permissions=context.workspace_permissions,
            user=user,
            workspace_membership_id=context.workspace_membership.id,
        )

    if api_key_value:
        matched_key, user = require_api_key_owner(db, api_key_value)
        context = resolve_auth_context(
            db,
            user,
            tenant_id=matched_key.tenant_id,
            workspace_id=matched_key.workspace_id,
        )
        matched_key.last_used_at = datetime.utcnow()
        db.commit()
        return Principal(
            kind="api_key",
            tenant_id=context.tenant_id,
            workspace_id=context.workspace.id,
            tenant_membership_role=context.tenant_membership.role,
            tenant_membership_status=context.tenant_membership.status,
            workspace_membership_role=context.workspace_membership.role,
            workspace_membership_status=context.workspace_membership.status,
            workspace_permissions=context.workspace_permissions,
            user=user,
            api_key=matched_key,
            workspace_membership_id=context.workspace_membership.id,
        )

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing credentials")
