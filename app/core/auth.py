from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
import uuid

import jwt
from fastapi import HTTPException, status
from fastapi.security import APIKeyHeader
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.principal import Principal
from app.models import ApiKey, RevokedToken, User


settings = get_settings()
bearer_scheme = HTTPBearer(auto_error=False)
api_key_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_login(db: Session, username: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.username == username))
    if not user or not user.is_active:
        return None
    if username != settings.admin_username or password != settings.admin_password:
        return None
    return user


def create_access_token(user: User, expires_minutes: int = 720) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user.id,
        "username": user.username,
        "tenant_id": user.tenant_id,
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
        return Principal(kind="session", tenant_id=user.tenant_id, user=user)

    if api_key_value:
        hashed = _hash_api_key(api_key_value)
        stmt = select(ApiKey).where(ApiKey.status == "active", ApiKey.revoked_at.is_(None))
        keys = db.scalars(stmt).all()
        matched_key = next((item for item in keys if hmac.compare_digest(item.key_hash, hashed)), None)
        if matched_key is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
        user = db.get(User, matched_key.created_by)
        if user is None or not user.is_active or user.tenant_id != matched_key.tenant_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key owner is invalid")
        matched_key.last_used_at = datetime.utcnow()
        db.commit()
        return Principal(kind="api_key", tenant_id=matched_key.tenant_id, user=user, api_key=matched_key)

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing credentials")
