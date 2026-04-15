from datetime import datetime
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_principal, get_current_user
from app.core.auth import (
    AuthContext,
    require_active_session_tenant_context,
    bearer_scheme,
    create_access_token,
    generate_api_key_value,
    get_api_key_prefix,
    resolve_auth_context,
    resolve_session_auth_context,
    revoke_token,
    verify_login,
)
from app.core.db import get_db
from app.core.principal import Principal
from app.models import ApiKey, TenantMembership, User
from app.schemas.auth import (
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeyOut,
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
    memberships = db.scalars(
        select(TenantMembership).where(TenantMembership.user_id == context.user.id).order_by(TenantMembership.created_at.asc())
    ).all()
    token = create_access_token(context)
    return TokenResponse(
        access_token=token,
        user=UserOut(
            id=context.user.id,
            tenant_id=context.tenant_id,
            workspace_id=context.workspace.id,
            username=context.user.username,
            email=context.user.email,
            can_create_workspace=context.user.can_create_workspace,
            is_platform_admin=context.user.is_platform_admin,
            membership_role=context.workspace_membership.role,
            tenant_membership_role=context.tenant_membership.role,
            tenant_membership_status=context.tenant_membership.status,
            workspace_membership_role=context.workspace_membership.role,
            workspace_membership_status=context.workspace_membership.status,
        ),
        workspace=WorkspaceOut(
            id=context.workspace.id,
            tenant_id=context.workspace.tenant_id,
            name=context.workspace.name,
            slug=context.workspace.slug,
            status=context.workspace.status,
            is_default=context.workspace.is_default,
        ),
        tenant_membership=_serialize_tenant_membership(context.tenant_membership),
        workspace_membership=_serialize_workspace_membership(context),
        memberships=[_serialize_tenant_membership(membership) for membership in memberships],
    )


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = verify_login(db, payload.username, payload.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    context = resolve_auth_context(db, user)
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
