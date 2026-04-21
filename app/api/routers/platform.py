from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.core.auth import api_key_scheme, bearer_scheme, require_user
from app.core.db import get_db
from app.models import User
from app.schemas.auth import ResetPasswordResponse
from app.schemas.platform import (
    PlatformTenantDetailOut,
    PlatformTenantListItemOut,
    PlatformUserAccessPortraitOut,
    PlatformUserCreateRequest,
    PlatformUserDetailOut,
    PlatformUserListItemOut,
    PlatformUserUpdateRequest,
    PlatformWorkspaceAccessPortraitOut,
    PlatformWorkspaceDetailOut,
    PlatformWorkspaceListItemOut,
)
from app.services.access_portrait_service import (
    get_platform_user_access_portrait,
    get_platform_workspace_access_portrait,
)
from app.services.platform_admin_service import (
    archive_platform_workspace,
    create_platform_user,
    get_platform_tenant_detail,
    get_platform_user_detail,
    get_platform_workspace_detail,
    list_platform_tenants,
    list_platform_users,
    list_platform_workspaces,
    patch_platform_user,
    reset_platform_user_password,
)


router = APIRouter(prefix="/api/v1/platform", tags=["platform"])


def require_platform_admin_session(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    api_key_value: str | None = Depends(api_key_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        if api_key_value:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Platform admin session required")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    user = require_user(db, credentials)
    if not user.is_platform_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Platform admin access required")
    return user


@router.get("/users", response_model=list[PlatformUserListItemOut])
def list_platform_users_endpoint(
    _: User = Depends(require_platform_admin_session),
    db: Session = Depends(get_db),
):
    return list_platform_users(db)


@router.get("/users/{user_id}", response_model=PlatformUserDetailOut)
def get_platform_user_detail_endpoint(
    user_id: str,
    _: User = Depends(require_platform_admin_session),
    db: Session = Depends(get_db),
):
    return get_platform_user_detail(db, user_id)


@router.get("/users/{user_id}/access-portrait", response_model=PlatformUserAccessPortraitOut)
def get_platform_user_access_portrait_endpoint(
    user_id: str,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    _: User = Depends(require_platform_admin_session),
    db: Session = Depends(get_db),
):
    return get_platform_user_access_portrait(
        db,
        user_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )


@router.post("/users", response_model=PlatformUserDetailOut, status_code=status.HTTP_201_CREATED)
def create_platform_user_endpoint(
    payload: PlatformUserCreateRequest,
    current_user: User = Depends(require_platform_admin_session),
    db: Session = Depends(get_db),
):
    return create_platform_user(
        db,
        payload,
        actor_user_id=current_user.id,
        actor_tenant_id=current_user.tenant_id,
    )


@router.patch("/users/{user_id}", response_model=PlatformUserDetailOut)
def patch_platform_user_endpoint(
    user_id: str,
    payload: PlatformUserUpdateRequest,
    _: User = Depends(require_platform_admin_session),
    db: Session = Depends(get_db),
):
    return patch_platform_user(db, user_id, payload)


@router.post("/users/{user_id}/reset-password", response_model=ResetPasswordResponse)
def reset_platform_user_password_endpoint(
    user_id: str,
    _: User = Depends(require_platform_admin_session),
    db: Session = Depends(get_db),
):
    """Reset a user's password to a random temporary value.

    The temporary password is returned exactly once and must be communicated
    to the user out-of-band.  The user will be forced to change it on next
    login.
    """
    temp_password = reset_platform_user_password(db, user_id)
    return ResetPasswordResponse(temporary_password=temp_password)



@router.get("/workspaces", response_model=list[PlatformWorkspaceListItemOut])
def list_platform_workspaces_endpoint(
    _: User = Depends(require_platform_admin_session),
    db: Session = Depends(get_db),
):
    return list_platform_workspaces(db)


@router.get("/workspaces/{workspace_id}", response_model=PlatformWorkspaceDetailOut)
def get_platform_workspace_detail_endpoint(
    workspace_id: str,
    _: User = Depends(require_platform_admin_session),
    db: Session = Depends(get_db),
):
    return get_platform_workspace_detail(db, workspace_id)


@router.get("/workspaces/{workspace_id}/access-portrait", response_model=PlatformWorkspaceAccessPortraitOut)
def get_platform_workspace_access_portrait_endpoint(
    workspace_id: str,
    _: User = Depends(require_platform_admin_session),
    db: Session = Depends(get_db),
):
    return get_platform_workspace_access_portrait(db, workspace_id)


@router.post("/workspaces/{workspace_id}/archive", response_model=PlatformWorkspaceDetailOut)
def archive_platform_workspace_endpoint(
    workspace_id: str,
    current_user: User = Depends(require_platform_admin_session),
    db: Session = Depends(get_db),
):
    return archive_platform_workspace(db, workspace_id, actor_user_id=current_user.id)


@router.get("/tenants", response_model=list[PlatformTenantListItemOut])
def list_platform_tenants_endpoint(
    _: User = Depends(require_platform_admin_session),
    db: Session = Depends(get_db),
):
    return list_platform_tenants(db)


@router.get("/tenants/{tenant_id}", response_model=PlatformTenantDetailOut)
def get_platform_tenant_detail_endpoint(
    tenant_id: str,
    _: User = Depends(require_platform_admin_session),
    db: Session = Depends(get_db),
):
    return get_platform_tenant_detail(db, tenant_id)
