from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TenantMembership, Workspace, WorkspaceMembership


ACTIVE_STATUS = "active"
ARCHIVED_STATUS = "archived"


@dataclass
class ResolvedWorkspaceMembershipContext:
    workspace: Workspace
    membership: WorkspaceMembership


def is_workspace_archived(workspace: Workspace) -> bool:
    return workspace.status == ARCHIVED_STATUS or workspace.archived_at is not None


def resolve_active_tenant_membership(
    db: Session,
    user_id: str,
    *,
    tenant_id: str | None = None,
    fallback_tenant_id: str | None = None,
) -> TenantMembership:
    if tenant_id is not None:
        membership = _get_active_tenant_membership(db, user_id, tenant_id=tenant_id)
        if membership is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No active tenant membership")
        return membership

    if fallback_tenant_id:
        membership = _get_active_tenant_membership(db, user_id, tenant_id=fallback_tenant_id)
        if membership is not None:
            return membership

    membership = _get_active_tenant_membership(db, user_id)
    if membership is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No active tenant membership")
    return membership


def get_active_tenant_membership(
    db: Session,
    user_id: str,
    *,
    tenant_id: str,
) -> TenantMembership | None:
    return _get_active_tenant_membership(db, user_id, tenant_id=tenant_id)


def resolve_active_workspace_membership_context(
    db: Session,
    user_id: str,
    tenant_id: str,
    *,
    workspace_id: str | None = None,
) -> ResolvedWorkspaceMembershipContext:
    if workspace_id is not None:
        return _resolve_explicit_workspace_membership_context(
            db,
            user_id=user_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )

    default_workspace = _get_default_workspace(db, tenant_id)
    if default_workspace is not None:
        default_membership = _get_active_workspace_membership(db, user_id, default_workspace.id)
        if default_membership is not None:
            return ResolvedWorkspaceMembershipContext(
                workspace=default_workspace,
                membership=default_membership,
            )

    fallback = db.execute(
        select(WorkspaceMembership, Workspace)
        .join(Workspace, WorkspaceMembership.workspace_id == Workspace.id)
        .where(
            WorkspaceMembership.user_id == user_id,
            WorkspaceMembership.status == ACTIVE_STATUS,
            Workspace.tenant_id == tenant_id,
            Workspace.status == ACTIVE_STATUS,
            Workspace.archived_at.is_(None),
        )
        .order_by(
            WorkspaceMembership.created_at.asc(),
            WorkspaceMembership.id.asc(),
            Workspace.created_at.asc(),
            Workspace.id.asc(),
        )
    ).first()
    if fallback is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No active workspace membership")

    membership, workspace = fallback
    return ResolvedWorkspaceMembershipContext(workspace=workspace, membership=membership)


def resolve_workspace_tenant_id_hint(
    db: Session,
    workspace_id: str | None,
) -> str | None:
    if workspace_id is None:
        return None
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        return None
    return workspace.tenant_id


def get_workspace_or_404(
    db: Session,
    workspace_id: str,
) -> Workspace:
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    return workspace


def get_workspace_membership(
    db: Session,
    workspace_id: str,
    membership_id: str,
) -> WorkspaceMembership | None:
    return db.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.id == membership_id,
            WorkspaceMembership.workspace_id == workspace_id,
        )
    )


def get_workspace_membership_by_user(
    db: Session,
    workspace_id: str,
    user_id: str,
) -> WorkspaceMembership | None:
    return db.scalar(
        select(WorkspaceMembership)
        .where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user_id,
        )
        .order_by(WorkspaceMembership.created_at.asc(), WorkspaceMembership.id.asc())
    )


def list_workspace_memberships(
    db: Session,
    workspace_id: str,
) -> list[WorkspaceMembership]:
    return db.scalars(
        select(WorkspaceMembership)
        .where(WorkspaceMembership.workspace_id == workspace_id)
        .order_by(WorkspaceMembership.created_at.asc(), WorkspaceMembership.id.asc())
    ).all()


def list_active_founder_memberships(
    db: Session,
    workspace_id: str,
) -> list[WorkspaceMembership]:
    return db.scalars(
        select(WorkspaceMembership)
        .where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.role == "founder",
            WorkspaceMembership.status == ACTIVE_STATUS,
        )
        .order_by(WorkspaceMembership.created_at.asc(), WorkspaceMembership.id.asc())
    ).all()


def _get_active_tenant_membership(
    db: Session,
    user_id: str,
    tenant_id: str | None = None,
) -> TenantMembership | None:
    stmt = (
        select(TenantMembership)
        .where(
            TenantMembership.user_id == user_id,
            TenantMembership.status == ACTIVE_STATUS,
        )
        .order_by(TenantMembership.created_at.asc(), TenantMembership.id.asc())
    )
    if tenant_id is not None:
        stmt = stmt.where(TenantMembership.tenant_id == tenant_id)
    return db.scalar(stmt)


def _get_active_workspace_membership(
    db: Session,
    user_id: str,
    workspace_id: str,
) -> WorkspaceMembership | None:
    return db.scalar(
        select(WorkspaceMembership)
        .where(
            WorkspaceMembership.user_id == user_id,
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.status == ACTIVE_STATUS,
        )
        .order_by(WorkspaceMembership.created_at.asc(), WorkspaceMembership.id.asc())
    )


def _get_default_workspace(db: Session, tenant_id: str) -> Workspace | None:
    return db.scalar(
        select(Workspace)
        .where(
            Workspace.tenant_id == tenant_id,
            Workspace.is_default.is_(True),
            Workspace.status == ACTIVE_STATUS,
            Workspace.archived_at.is_(None),
        )
        .order_by(Workspace.created_at.asc(), Workspace.id.asc())
    )


def _resolve_explicit_workspace_membership_context(
    db: Session,
    *,
    user_id: str,
    tenant_id: str,
    workspace_id: str,
) -> ResolvedWorkspaceMembershipContext:
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Workspace not found")
    if workspace.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Workspace not in active tenant")
    if is_workspace_archived(workspace) or workspace.status != ACTIVE_STATUS:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Workspace is archived")

    membership = _get_active_workspace_membership(db, user_id, workspace_id)
    if membership is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No active workspace membership")

    return ResolvedWorkspaceMembershipContext(workspace=workspace, membership=membership)
