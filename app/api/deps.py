from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.core.auth import api_key_scheme, bearer_scheme, require_active_tenant_context, require_principal, require_user
from app.core.db import get_db
from app.models import User
from app.core.principal import Principal


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    api_key_value: str | None = Depends(api_key_scheme),
    db: Session = Depends(get_db),
) -> User:
    return require_active_tenant_context(db, credentials, api_key_value).user


def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    api_key_value: str | None = Depends(api_key_scheme),
    db: Session = Depends(get_db),
) -> Principal:
    return require_principal(db, credentials, api_key_value)


def get_session_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Resolve bearer-session user only — no API key accepted.

    Used by the invite accept endpoint where the caller may not yet have
    workspace or tenant membership, so ``get_current_principal()`` cannot
    be used.
    """
    return require_user(db, credentials)
