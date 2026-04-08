from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.core.auth import api_key_scheme, bearer_scheme, require_principal
from app.core.db import get_db
from app.models import User
from app.core.principal import Principal


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    api_key_value: str | None = Depends(api_key_scheme),
    db: Session = Depends(get_db),
) -> User:
    principal = require_principal(db, credentials, api_key_value)
    return principal.user


def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    api_key_value: str | None = Depends(api_key_scheme),
    db: Session = Depends(get_db),
) -> Principal:
    return require_principal(db, credentials, api_key_value)
