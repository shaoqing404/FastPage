from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import case, distinct, func, select
from sqlalchemy.orm import Session

from app.models import Tenant, TenantMembership, User, Workspace, WorkspaceMembership
from app.services.workspace_membership_service import _get_default_workspace, get_workspace_or_404
from app.core.auth import hash_password
from app.models.user import _normalize_email
import uuid


ACTIVE_STATUS = "active"
ARCHIVED_STATUS = "archived"


def list_platform_users(db: Session) -> list[dict[str, object]]:
    tenant_counts = dict(
        db.execute(
            select(TenantMembership.user_id, func.count(distinct(TenantMembership.tenant_id)))
            .group_by(TenantMembership.user_id)
        ).all()
    )
    workspace_counts = dict(
        db.execute(
            select(WorkspaceMembership.user_id, func.count(distinct(WorkspaceMembership.workspace_id)))
            .group_by(WorkspaceMembership.user_id)
        ).all()
    )
    users = db.scalars(select(User).order_by(User.created_at.asc(), User.id.asc())).all()
    return [
        _serialize_platform_user(
            user,
            tenant_membership_count=tenant_counts.get(user.id, 0),
            workspace_membership_count=workspace_counts.get(user.id, 0),
        )
        for user in users
    ]


def get_platform_user_detail(db: Session, user_id: str) -> dict[str, object]:
    user = _get_user_or_404(db, user_id)
    return _serialize_platform_user_detail(db, user)


def create_platform_user(
    db: Session,
    payload,
    *,
    actor_user_id: str,
    actor_tenant_id: str,
) -> dict[str, object]:
    if db.scalar(select(User).where(User.username == payload.username)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")

    email = _normalize_email(payload.email)
    if email and db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")

    default_workspace = _get_default_workspace(db, actor_tenant_id)
    if not default_workspace:
        # Fallback to any active non-archived workspace if default is missing (rare defensive fallback)
        default_workspace = db.scalar(
            select(Workspace)
            .where(
                Workspace.tenant_id == actor_tenant_id,
                Workspace.status == ACTIVE_STATUS,
                Workspace.archived_at.is_(None),
            )
            .order_by(Workspace.created_at.asc())
        )
        if not default_workspace:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="No workspace available for provisioning")

    now = datetime.utcnow()
    user_id = f"user_{uuid.uuid4().hex}"
    
    user = User(
        id=user_id,
        tenant_id=actor_tenant_id,
        username=payload.username,
        email=email,
        password_hash=hash_password(payload.password),
        is_active=payload.is_active,
        can_create_workspace=payload.can_create_workspace,
        is_platform_admin=payload.is_platform_admin,
        created_at=now,
        updated_at=now,
    )
    db.add(user)
    db.flush()

    tm = TenantMembership(
        id=f"tm_{actor_tenant_id}_{user_id}"[:64],
        tenant_id=actor_tenant_id,
        user_id=user_id,
        role="member",
        status=ACTIVE_STATUS,
        created_by=actor_user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(tm)

    wm = WorkspaceMembership(
        id=f"wm_{default_workspace.id}_{user_id}"[:64],
        workspace_id=default_workspace.id,
        user_id=user_id,
        role="member",
        status=ACTIVE_STATUS,
        permissions_override_json="{}",
        created_by=actor_user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(wm)

    db.commit()
    db.refresh(user)
    return _serialize_platform_user_detail(db, user)


def patch_platform_user(
    db: Session,
    user_id: str,
    payload,
) -> dict[str, object]:
    user = _get_user_or_404(db, user_id)
    updates = payload.model_dump(exclude_unset=True)
    if updates:
        for field_name, value in updates.items():
            setattr(user, field_name, value)
        user.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(user)
    return _serialize_platform_user_detail(db, user)


def list_platform_workspaces(db: Session) -> list[dict[str, object]]:
    rows = db.execute(
        select(Workspace, Tenant)
        .join(Tenant, Tenant.id == Workspace.tenant_id)
        .order_by(Workspace.created_at.asc(), Workspace.id.asc())
    ).all()
    founder_map = _load_active_founder_map(db)
    counts_map = _load_workspace_member_counts(db)
    return [
        _serialize_platform_workspace_summary(
            workspace,
            tenant,
            founder=founder_map.get(workspace.id),
            counts=counts_map.get(workspace.id, {"member_count": 0, "active_member_count": 0}),
        )
        for workspace, tenant in rows
    ]


def get_platform_workspace_detail(db: Session, workspace_id: str) -> dict[str, object]:
    workspace, tenant = _get_workspace_with_tenant_or_404(db, workspace_id)
    founder_map = _load_active_founder_map(db, workspace_ids=[workspace_id])
    counts_map = _load_workspace_member_counts(db, workspace_ids=[workspace_id])
    members = _list_workspace_members(db, workspace_id)
    return {
        **_serialize_platform_workspace_summary(
            workspace,
            tenant,
            founder=founder_map.get(workspace.id),
            counts=counts_map.get(workspace.id, {"member_count": 0, "active_member_count": 0}),
        ),
        "members": members,
    }


def archive_platform_workspace(
    db: Session,
    workspace_id: str,
    *,
    actor_user_id: str,
) -> dict[str, object]:
    workspace = get_workspace_or_404(db, workspace_id)
    if workspace.is_default:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Default workspace cannot be archived")
    if workspace.status == ARCHIVED_STATUS or workspace.archived_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Workspace is already archived")

    now = datetime.utcnow()
    workspace.status = ARCHIVED_STATUS
    workspace.archived_at = now
    workspace.archived_by = actor_user_id
    workspace.updated_at = now
    db.commit()
    return get_platform_workspace_detail(db, workspace_id)


def list_platform_tenants(db: Session) -> list[dict[str, object]]:
    user_counts = dict(
        db.execute(
            select(
                TenantMembership.tenant_id,
                func.count(distinct(TenantMembership.user_id)),
            )
            .where(TenantMembership.status == ACTIVE_STATUS)
            .group_by(TenantMembership.tenant_id)
        ).all()
    )
    workspace_counts = dict(
        db.execute(
            select(Workspace.tenant_id, func.count(Workspace.id))
            .group_by(Workspace.tenant_id)
        ).all()
    )
    tenants = db.scalars(select(Tenant).order_by(Tenant.created_at.asc(), Tenant.id.asc())).all()
    return [
        _serialize_platform_tenant(
            tenant,
            user_count=user_counts.get(tenant.id, 0),
            workspace_count=workspace_counts.get(tenant.id, 0),
        )
        for tenant in tenants
    ]


def get_platform_tenant_detail(db: Session, tenant_id: str) -> dict[str, object]:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    user_count = db.scalar(
        select(func.count(distinct(TenantMembership.user_id))).where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.status == ACTIVE_STATUS,
        )
    ) or 0
    workspace_count = db.scalar(
        select(func.count(Workspace.id)).where(Workspace.tenant_id == tenant_id)
    ) or 0

    user_rows = db.execute(
        select(TenantMembership, User)
        .join(User, User.id == TenantMembership.user_id)
        .where(TenantMembership.tenant_id == tenant_id)
        .order_by(TenantMembership.created_at.asc(), TenantMembership.id.asc())
    ).all()
    workspace_rows = db.scalars(
        select(Workspace)
        .where(Workspace.tenant_id == tenant_id)
        .order_by(Workspace.created_at.asc(), Workspace.id.asc())
    ).all()

    return {
        **_serialize_platform_tenant(tenant, user_count=user_count, workspace_count=workspace_count),
        "users": [
            {
                "id": membership.id,
                "user_id": user.id,
                "username": user.username,
                "email": user.email,
                "role": membership.role,
                "status": membership.status,
                "created_at": membership.created_at,
                "updated_at": membership.updated_at,
            }
            for membership, user in user_rows
        ],
        "workspaces": [
            {
                "id": workspace.id,
                "name": workspace.name,
                "slug": workspace.slug,
                "status": workspace.status,
                "is_default": workspace.is_default,
                "archived_at": workspace.archived_at,
                "created_at": workspace.created_at,
                "updated_at": workspace.updated_at,
            }
            for workspace in workspace_rows
        ],
    }


def _serialize_platform_user(
    user: User,
    *,
    tenant_membership_count: int,
    workspace_membership_count: int,
) -> dict[str, object]:
    return {
        "id": user.id,
        "tenant_id": user.tenant_id,
        "username": user.username,
        "email": user.email,
        "is_active": user.is_active,
        "can_create_workspace": user.can_create_workspace,
        "is_platform_admin": user.is_platform_admin,
        "tenant_membership_count": tenant_membership_count,
        "workspace_membership_count": workspace_membership_count,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }


def _serialize_platform_user_detail(db: Session, user: User) -> dict[str, object]:
    tenant_memberships = db.execute(
        select(TenantMembership, Tenant)
        .join(Tenant, Tenant.id == TenantMembership.tenant_id)
        .where(TenantMembership.user_id == user.id)
        .order_by(TenantMembership.created_at.asc(), TenantMembership.id.asc())
    ).all()
    workspace_memberships = db.execute(
        select(WorkspaceMembership, Workspace, Tenant)
        .join(Workspace, Workspace.id == WorkspaceMembership.workspace_id)
        .join(Tenant, Tenant.id == Workspace.tenant_id)
        .where(WorkspaceMembership.user_id == user.id)
        .order_by(WorkspaceMembership.created_at.asc(), WorkspaceMembership.id.asc())
    ).all()
    return {
        **_serialize_platform_user(
            user,
            tenant_membership_count=len(tenant_memberships),
            workspace_membership_count=len(workspace_memberships),
        ),
        "tenant_memberships": [
            {
                "id": membership.id,
                "tenant_id": membership.tenant_id,
                "tenant_name": tenant.name,
                "role": membership.role,
                "status": membership.status,
                "created_at": membership.created_at,
                "updated_at": membership.updated_at,
            }
            for membership, tenant in tenant_memberships
        ],
        "workspace_memberships": [
            {
                "id": membership.id,
                "workspace_id": workspace.id,
                "workspace_name": workspace.name,
                "workspace_slug": workspace.slug,
                "tenant_id": workspace.tenant_id,
                "tenant_name": tenant.name,
                "role": membership.role,
                "status": membership.status,
                "created_at": membership.created_at,
                "updated_at": membership.updated_at,
            }
            for membership, workspace, tenant in workspace_memberships
        ],
    }


def _serialize_platform_workspace_summary(
    workspace: Workspace,
    tenant: Tenant,
    *,
    founder: tuple[WorkspaceMembership, User] | None,
    counts: dict[str, int],
) -> dict[str, object]:
    founder_membership = founder[0] if founder is not None else None
    founder_user = founder[1] if founder is not None else None
    return {
        "id": workspace.id,
        "tenant_id": workspace.tenant_id,
        "tenant_name": tenant.name,
        "name": workspace.name,
        "slug": workspace.slug,
        "status": workspace.status,
        "is_default": workspace.is_default,
        "archived_at": workspace.archived_at,
        "archived_by": workspace.archived_by,
        "created_by": workspace.created_by,
        "created_at": workspace.created_at,
        "updated_at": workspace.updated_at,
        "founder_user_id": founder_membership.user_id if founder_membership is not None else None,
        "founder_username": founder_user.username if founder_user is not None else None,
        "founder_email": founder_user.email if founder_user is not None else None,
        "member_count": counts["member_count"],
        "active_member_count": counts["active_member_count"],
    }


def _serialize_platform_tenant(
    tenant: Tenant,
    *,
    user_count: int,
    workspace_count: int,
) -> dict[str, object]:
    return {
        "id": tenant.id,
        "name": tenant.name,
        "status": tenant.status,
        "created_at": tenant.created_at,
        "user_count": user_count,
        "workspace_count": workspace_count,
    }


def _load_active_founder_map(
    db: Session,
    *,
    workspace_ids: list[str] | None = None,
) -> dict[str, tuple[WorkspaceMembership, User]]:
    stmt = (
        select(WorkspaceMembership, User)
        .join(User, User.id == WorkspaceMembership.user_id)
        .where(
            WorkspaceMembership.role == "founder",
            WorkspaceMembership.status == ACTIVE_STATUS,
        )
        .order_by(WorkspaceMembership.created_at.asc(), WorkspaceMembership.id.asc())
    )
    if workspace_ids is not None:
        stmt = stmt.where(WorkspaceMembership.workspace_id.in_(workspace_ids))

    founder_map: dict[str, tuple[WorkspaceMembership, User]] = {}
    for membership, user in db.execute(stmt).all():
        founder_map.setdefault(membership.workspace_id, (membership, user))
    return founder_map


def _load_workspace_member_counts(
    db: Session,
    *,
    workspace_ids: list[str] | None = None,
) -> dict[str, dict[str, int]]:
    stmt = select(
        WorkspaceMembership.workspace_id,
        func.count(WorkspaceMembership.id),
        func.sum(case((WorkspaceMembership.status == ACTIVE_STATUS, 1), else_=0)),
    ).group_by(WorkspaceMembership.workspace_id)
    if workspace_ids is not None:
        stmt = stmt.where(WorkspaceMembership.workspace_id.in_(workspace_ids))

    return {
        workspace_id: {
            "member_count": member_count,
            "active_member_count": active_member_count or 0,
        }
        for workspace_id, member_count, active_member_count in db.execute(stmt).all()
    }


def _list_workspace_members(
    db: Session,
    workspace_id: str,
) -> list[dict[str, object]]:
    rows = db.execute(
        select(WorkspaceMembership, User)
        .join(User, User.id == WorkspaceMembership.user_id)
        .where(WorkspaceMembership.workspace_id == workspace_id)
        .order_by(WorkspaceMembership.created_at.asc(), WorkspaceMembership.id.asc())
    ).all()
    return [
        {
            "id": membership.id,
            "user_id": membership.user_id,
            "username": user.username,
            "email": user.email,
            "role": membership.role,
            "status": membership.status,
            "created_at": membership.created_at,
            "updated_at": membership.updated_at,
        }
        for membership, user in rows
    ]


def _get_user_or_404(db: Session, user_id: str) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


def _get_workspace_with_tenant_or_404(
    db: Session,
    workspace_id: str,
) -> tuple[Workspace, Tenant]:
    row = db.execute(
        select(Workspace, Tenant)
        .join(Tenant, Tenant.id == Workspace.tenant_id)
        .where(Workspace.id == workspace_id)
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    return row


def reset_platform_user_password(
    db: Session,
    user_id: str,
) -> str:
    """Reset a user's password to a random temporary value.

    Sets ``must_change_password=True`` so the user is forced to choose a real
    password on next login.

    Returns the cleartext temporary password (visible only to the calling
    platform admin, only this once).
    """
    import secrets  # noqa: PLC0415

    user = _get_user_or_404(db, user_id)

    temp_password = secrets.token_urlsafe(12)  # ~16 chars
    user.password_hash = hash_password(temp_password)
    user.must_change_password = True
    user.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(user)

    return temp_password
