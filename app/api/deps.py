from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from types import SimpleNamespace

from app.core.auth import api_key_scheme, bearer_scheme, require_active_tenant_context, require_principal, require_user
from app.core.db import SessionLocal, get_db
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


def _snapshot_principal(principal: Principal) -> Principal:
    user = SimpleNamespace(
        id=principal.user.id,
        tenant_id=getattr(principal.user, "tenant_id", None),
        username=getattr(principal.user, "username", None),
        email=getattr(principal.user, "email", None),
        can_create_workspace=getattr(principal.user, "can_create_workspace", False),
        is_platform_admin=getattr(principal.user, "is_platform_admin", False),
        must_change_password=getattr(principal.user, "must_change_password", False),
    )
    api_key = None
    if principal.api_key is not None:
        api_key = SimpleNamespace(
            id=principal.api_key.id,
            tenant_id=principal.api_key.tenant_id,
            workspace_id=principal.api_key.workspace_id,
            created_by=principal.api_key.created_by,
            key_prefix=principal.api_key.key_prefix,
            status=principal.api_key.status,
        )
    return Principal(
        kind=principal.kind,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        tenant_membership_role=principal.tenant_membership_role,
        tenant_membership_status=principal.tenant_membership_status,
        workspace_membership_role=principal.workspace_membership_role,
        workspace_membership_status=principal.workspace_membership_status,
        workspace_permissions=dict(principal.workspace_permissions),
        user=user,
        api_key=api_key,
        workspace_membership_id=principal.workspace_membership_id,
    )


def resolve_stream_principal(
    credentials: HTTPAuthorizationCredentials | None,
    api_key_value: str | None,
) -> Principal:
    with SessionLocal() as db:
        principal = require_principal(db, credentials, api_key_value)
        return _snapshot_principal(principal)
