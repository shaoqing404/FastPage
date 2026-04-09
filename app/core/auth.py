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
from app.models import ApiKey, RevokedToken, TenantMembership, User, Workspace


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
    membership: TenantMembership


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


def _get_membership(
    db: Session,
    user_id: str,
    tenant_id: str | None = None,
) -> TenantMembership | None:
    stmt = select(TenantMembership).where(
        TenantMembership.user_id == user_id,
        TenantMembership.status == "active",
    )
    if tenant_id is not None:
        stmt = stmt.where(TenantMembership.tenant_id == tenant_id)
        return db.scalar(stmt.order_by(TenantMembership.created_at.asc()))
    return db.scalar(stmt.order_by(TenantMembership.created_at.asc()))


def _get_default_workspace(db: Session, tenant_id: str, workspace_id: str | None = None) -> Workspace | None:
    if workspace_id is not None:
        workspace = db.scalar(
            select(Workspace).where(
                Workspace.id == workspace_id,
                Workspace.tenant_id == tenant_id,
                Workspace.status == "active",
            )
        )
        if workspace is not None:
            return workspace
    workspace = db.scalar(
        select(Workspace).where(
            Workspace.tenant_id == tenant_id,
            Workspace.is_default.is_(True),
            Workspace.status == "active",
        )
    )
    if workspace is not None:
        return workspace
    return db.scalar(
        select(Workspace).where(
            Workspace.tenant_id == tenant_id,
            Workspace.status == "active",
        ).order_by(Workspace.created_at.asc())
    )


def resolve_auth_context(
    db: Session,
    user: User,
    *,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
) -> AuthContext:
    membership = _get_membership(db, user.id, tenant_id=tenant_id)
    if membership is None and tenant_id is None and user.tenant_id:
        membership = _get_membership(db, user.id, tenant_id=user.tenant_id)
    if membership is None:
        membership = _get_membership(db, user.id)
    if membership is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No active tenant membership")

    workspace = _get_default_workspace(db, membership.tenant_id, workspace_id=workspace_id)
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No active workspace")

    return AuthContext(
        user=user,
        tenant_id=membership.tenant_id,
        workspace=workspace,
        membership=membership,
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
        "membership_role": context.membership.role,
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


def _hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(f"{settings.secret_key}:{raw_key}".encode("utf-8")).hexdigest()


def generate_api_key_value() -> tuple[str, str]:
    raw = f"pidx_{secrets.token_urlsafe(32)}"
    return raw, _hash_api_key(raw)


def get_api_key_prefix(raw_key: str) -> str:
    return raw_key[:12]


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
            membership_role=context.membership.role,
            user=user,
        )

    if api_key_value:
        hashed = _hash_api_key(api_key_value)
        stmt = select(ApiKey).where(ApiKey.status == "active", ApiKey.revoked_at.is_(None))
        keys = db.scalars(stmt).all()
        matched_key = next((item for item in keys if hmac.compare_digest(item.key_hash, hashed)), None)
        if matched_key is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
        user = db.get(User, matched_key.created_by)
        if user is None or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key owner is invalid")
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
            membership_role=context.membership.role,
            user=user,
            api_key=matched_key,
        )

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing credentials")
