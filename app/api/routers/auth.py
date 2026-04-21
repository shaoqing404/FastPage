from datetime import datetime
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_principal, get_current_user, get_session_user
from app.core.auth import (
    AuthContext,
    build_auth_response_payload,
    require_active_session_tenant_context,
    bearer_scheme,
    generate_api_key_value,
    get_api_key_prefix,
    resolve_auth_context,
    resolve_session_auth_context,
    revoke_token,
    verify_login,
    verify_password,
)
from app.core.db import get_db
from app.core.principal import Principal
from app.models import ApiKey, TenantMembership, User
from app.schemas.auth import (
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeyOut,
    ChangePasswordRequest,
    ContextSwitchRequest,
    LoginRequest,
    MembershipOut,
    TokenResponse,
    UserOut,
    WorkspaceOut,
    WorkspaceMembershipOut,
)
from app.services.workspace_access_service import parse_workspace_permissions_override, require_workspace_capability


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _serialize_tenant_membership(membership: TenantMembership) -> MembershipOut:
    return MembershipOut(
        id=membership.id,
        tenant_id=membership.tenant_id,
        role=membership.role,
        status=membership.status,
    )


def _serialize_workspace_membership(context: AuthContext) -> WorkspaceMembershipOut:
    membership = context.workspace_membership
    return WorkspaceMembershipOut(
        id=membership.id,
        workspace_id=membership.workspace_id,
        user_id=membership.user_id,
        role=membership.role,
        status=membership.status,
        permissions_override=parse_workspace_permissions_override(membership.permissions_override_json),
        permissions=context.workspace_permissions,
    )


def _build_token_response(db: Session, context: AuthContext) -> TokenResponse:
    return TokenResponse.model_validate(build_auth_response_payload(db, context))


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = verify_login(db, payload.username, payload.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    context = resolve_auth_context(db, user)
    return _build_token_response(db, context)


@router.post("/change-password", response_model=TokenResponse)
def change_password(
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_session_user),
) -> TokenResponse:
    """Change the authenticated user's password.

    Requires the current password for verification.  Clears the
    ``must_change_password`` flag if it was set.
    """
    from app.core.auth import hash_password as _hash_password  # noqa: PLC0415

    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")

    current_user.password_hash = _hash_password(payload.new_password)
    if current_user.must_change_password:
        current_user.must_change_password = False
    from datetime import datetime as _dt  # noqa: PLC0415
    current_user.updated_at = _dt.utcnow()
    db.commit()
    db.refresh(current_user)

    context = resolve_auth_context(db, current_user)
    return _build_token_response(db, context)


@router.get("/context", response_model=TokenResponse)
def get_context(
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> TokenResponse:
    context = resolve_session_auth_context(db, credentials)
    return _build_token_response(db, context)


@router.post("/context/switch", response_model=TokenResponse)
def switch_context(
    payload: ContextSwitchRequest,
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> TokenResponse:
    tenant_context = require_active_session_tenant_context(db, credentials)

    context = resolve_auth_context(
        db,
        tenant_context.user,
        tenant_id=tenant_context.tenant_id,
        workspace_id=payload.workspace_id,
    )
    return _build_token_response(db, context)


@router.post("/logout", status_code=204)
def logout(
    current_user: User = Depends(get_current_user),
    credentials=Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Response:
    _ = current_user
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    revoke_token(db, credentials.credentials)
    return Response(status_code=204)


@router.post("/apikeys", response_model=ApiKeyCreateResponse)
def create_api_key(
    payload: ApiKeyCreateRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    require_workspace_capability(
        principal,
        "can_manage_api_keys",
        detail="Missing workspace capability: can_manage_api_keys",
    )
    raw_key, hashed_key = generate_api_key_value()
    api_key = ApiKey(
        id=str(uuid.uuid4()),
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        name=payload.name,
        key_prefix=get_api_key_prefix(raw_key),
        key_hash=hashed_key,
        status="active",
        created_by=principal.user_id,
        created_at=datetime.utcnow(),
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return ApiKeyCreateResponse(
        id=api_key.id,
        tenant_id=api_key.tenant_id,
        workspace_id=principal.workspace_id,
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        status=api_key.status,
        created_at=api_key.created_at,
        api_key=raw_key,
    )


@router.get("/apikeys", response_model=list[ApiKeyOut])
def list_api_keys(
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    require_workspace_capability(
        principal,
        "can_manage_api_keys",
        detail="Missing workspace capability: can_manage_api_keys",
    )
    keys = db.scalars(
        select(ApiKey).where(
            ApiKey.tenant_id == principal.tenant_id,
            ApiKey.workspace_id == principal.workspace_id,
        ).order_by(ApiKey.created_at.desc())
    ).all()
    return keys


@router.delete("/apikeys/{key_id}", status_code=204)
def revoke_api_key_endpoint(
    key_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
) -> Response:
    require_workspace_capability(
        principal,
        "can_manage_api_keys",
        detail="Missing workspace capability: can_manage_api_keys",
    )
    api_key = db.get(ApiKey, key_id)
    if (
        api_key is None
        or api_key.tenant_id != principal.tenant_id
        or api_key.workspace_id != principal.workspace_id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    api_key.status = "revoked"
    api_key.revoked_at = datetime.utcnow()
    db.commit()
    return Response(status_code=204)
