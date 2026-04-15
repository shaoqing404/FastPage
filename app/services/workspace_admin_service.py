import uuid
from datetime import datetime
import re

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.principal import Principal
from app.models import User, Workspace, WorkspaceMembership
from app.services.workspace_access_service import (
    dump_workspace_permissions_override_json,
    parse_workspace_permissions_override,
    resolve_workspace_capabilities,
    require_workspace_capability,
)
from app.services.workspace_membership_service import (
    ACTIVE_STATUS,
    ARCHIVED_STATUS,
    get_active_tenant_membership,
    get_workspace_membership,
    get_workspace_membership_by_user,
    get_workspace_or_404,
    is_workspace_archived,
    list_active_founder_memberships,
)


WORKSPACE_MEMBERSHIP_ROLES = frozenset({"founder", "admin", "member", "guest"})
WORKSPACE_MEMBERSHIP_STATUSES = frozenset({"active", "disabled", "removed"})
ADMIN_MANAGEABLE_ROLES = frozenset({"member", "guest"})


def serialize_workspace_member(
    membership: WorkspaceMembership,
    user: User,
) -> dict[str, object]:
    return {
        "id": membership.id,
        "workspace_id": membership.workspace_id,
        "user_id": membership.user_id,
        "email": user.email,
        "role": membership.role,
        "status": membership.status,
        "permissions_override": parse_workspace_permissions_override(membership.permissions_override_json),
        "created_at": membership.created_at,
        "updated_at": membership.updated_at,
    }


def serialize_workspace_admin_workspace(workspace: Workspace) -> dict[str, object]:
    return {
        "id": workspace.id,
        "tenant_id": workspace.tenant_id,
        "name": workspace.name,
        "slug": workspace.slug,
        "status": workspace.status,
        "is_default": workspace.is_default,
        "archived_at": workspace.archived_at,
        "archived_by": workspace.archived_by,
        "created_at": workspace.created_at,
        "updated_at": workspace.updated_at,
    }


def serialize_workspace_list_item(
    workspace: Workspace,
    membership: WorkspaceMembership,
    *,
    is_current: bool,
) -> dict[str, object]:
    return {
        **serialize_workspace_admin_workspace(workspace),
        "membership_id": membership.id,
        "membership_role": membership.role,
        "membership_status": membership.status,
        "permissions": resolve_workspace_capabilities(
            membership.role,
            membership.permissions_override_json,
        ),
        "permissions_override": parse_workspace_permissions_override(membership.permissions_override_json),
        "is_current": is_current,
    }


def list_accessible_workspaces(
    db: Session,
    principal: Principal,
) -> list[dict[str, object]]:
    rows = db.execute(
        select(WorkspaceMembership, Workspace)
        .join(Workspace, WorkspaceMembership.workspace_id == Workspace.id)
        .where(
            WorkspaceMembership.user_id == principal.user_id,
            WorkspaceMembership.status == ACTIVE_STATUS,
            Workspace.tenant_id == principal.tenant_id,
        )
        .order_by(
            Workspace.is_default.desc(),
            Workspace.created_at.asc(),
            Workspace.id.asc(),
            WorkspaceMembership.created_at.asc(),
            WorkspaceMembership.id.asc(),
        )
    ).all()
    return [
        serialize_workspace_list_item(
            workspace,
            membership,
            is_current=workspace.id == principal.workspace_id,
        )
        for membership, workspace in rows
    ]


def update_workspace_metadata(
    db: Session,
    principal: Principal,
    workspace_id: str,
    payload,
) -> dict[str, object]:
    workspace = get_workspace_or_404(db, workspace_id)
    if workspace.tenant_id != principal.tenant_id and not _is_platform_admin_actor(principal):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")

    if not _is_platform_admin_actor(principal):
        if workspace.id != principal.workspace_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
        require_workspace_capability(
            principal,
            "can_edit_workspace_metadata",
            detail="Missing workspace capability: can_edit_workspace_metadata",
        )

    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return serialize_workspace_admin_workspace(workspace)

    now = datetime.utcnow()
    if "name" in updates:
        name = (updates["name"] or "").strip()
        if not name:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Workspace name cannot be empty")
        workspace.name = name

    if "slug" in updates:
        slug = normalize_workspace_slug(updates["slug"])
        existing = db.scalar(
            select(Workspace).where(
                Workspace.tenant_id == workspace.tenant_id,
                Workspace.slug == slug,
                Workspace.id != workspace.id,
            )
        )
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Workspace slug already exists in this tenant")
        workspace.slug = slug

    workspace.updated_at = now
    db.commit()
    db.refresh(workspace)
    return serialize_workspace_admin_workspace(workspace)


def list_workspace_members(
    db: Session,
    principal: Principal,
    workspace_id: str,
) -> list[dict[str, object]]:
    workspace = _get_workspace_for_admin_operation(db, principal, workspace_id)
    _require_member_management_actor(principal)

    rows = db.execute(
        select(WorkspaceMembership, User)
        .join(User, WorkspaceMembership.user_id == User.id)
        .where(WorkspaceMembership.workspace_id == workspace.id)
        .order_by(WorkspaceMembership.created_at.asc(), WorkspaceMembership.id.asc())
    ).all()
    return [serialize_workspace_member(membership, user) for membership, user in rows]


def create_workspace_member(
    db: Session,
    principal: Principal,
    workspace_id: str,
    payload,
) -> dict[str, object]:
    workspace = _get_workspace_for_admin_operation(db, principal, workspace_id)
    _require_member_management_actor(principal)

    role = payload.role
    _validate_membership_role(role)
    _assert_assignable_role(principal, role)

    user = db.get(User, payload.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if get_active_tenant_membership(db, user.id, tenant_id=workspace.tenant_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User is not in the workspace tenant")

    override_json = dump_workspace_permissions_override_json(payload.permissions_override, role=role)
    existing_membership = get_workspace_membership_by_user(db, workspace.id, user.id)
    now = datetime.utcnow()

    if existing_membership is not None:
        _assert_manageable_target(principal, existing_membership, desired_role=role)
        if existing_membership.status == ACTIVE_STATUS:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Workspace membership already exists")

        existing_membership.role = role
        existing_membership.status = ACTIVE_STATUS
        existing_membership.permissions_override_json = override_json
        existing_membership.updated_at = now
        db.commit()
        db.refresh(existing_membership)
        return serialize_workspace_member(existing_membership, user)

    membership = WorkspaceMembership(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        user_id=user.id,
        role=role,
        status=ACTIVE_STATUS,
        permissions_override_json=override_json,
        created_by=principal.user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(membership)
    db.commit()
    db.refresh(membership)
    return serialize_workspace_member(membership, user)


def update_workspace_member(
    db: Session,
    principal: Principal,
    workspace_id: str,
    membership_id: str,
    payload,
) -> dict[str, object]:
    workspace = _get_workspace_for_admin_operation(db, principal, workspace_id)
    _require_member_management_actor(principal)

    membership = get_workspace_membership(db, workspace.id, membership_id)
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace membership not found")

    update_dict = payload.model_dump(exclude_unset=True)
    desired_role = update_dict.get("role", membership.role)
    desired_status = update_dict.get("status", membership.status)
    _validate_membership_role(desired_role)
    _validate_membership_status(desired_status)
    _assert_manageable_target(principal, membership, desired_role=desired_role)

    if not update_dict:
        return serialize_workspace_member(membership, _get_membership_user_or_404(db, membership))

    if "permissions_override" in update_dict:
        membership.permissions_override_json = dump_workspace_permissions_override_json(
            update_dict["permissions_override"],
            role=desired_role,
        )
    if "role" in update_dict:
        membership.role = desired_role
    if "status" in update_dict:
        membership.status = desired_status
    membership.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(membership)
    return serialize_workspace_member(membership, _get_membership_user_or_404(db, membership))


def remove_workspace_member(
    db: Session,
    principal: Principal,
    workspace_id: str,
    membership_id: str,
) -> None:
    workspace = _get_workspace_for_admin_operation(db, principal, workspace_id)
    _require_member_management_actor(principal)

    membership = get_workspace_membership(db, workspace.id, membership_id)
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace membership not found")

    _assert_manageable_target(principal, membership, desired_role=membership.role)
    if membership.status == "removed":
        return

    membership.status = "removed"
    membership.updated_at = datetime.utcnow()
    db.commit()


def transfer_workspace_founder(
    db: Session,
    principal: Principal,
    workspace_id: str,
    *,
    target_user_id: str,
) -> dict[str, object]:
    workspace = _get_workspace_for_admin_operation(db, principal, workspace_id)
    _require_founder_transfer_actor(principal)

    founders = list_active_founder_memberships(db, workspace.id)
    if len(founders) != 1:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Workspace founder invariant is broken")
    current_founder = founders[0]

    target_membership = db.scalar(
        select(WorkspaceMembership)
        .where(
            WorkspaceMembership.workspace_id == workspace.id,
            WorkspaceMembership.user_id == target_user_id,
            WorkspaceMembership.status == ACTIVE_STATUS,
        )
        .order_by(WorkspaceMembership.created_at.asc(), WorkspaceMembership.id.asc())
    )
    if target_membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target workspace membership not found")
    if target_membership.id == current_founder.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Target user is already the workspace founder")

    now = datetime.utcnow()
    previous_founder = current_founder
    previous_founder.role = "admin"
    previous_founder.updated_at = now
    db.flush()

    target_membership.role = "founder"
    target_membership.updated_at = now

    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _is_active_founder_conflict_error(exc):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Workspace founder invariant is broken") from exc
        raise

    founders_after = list_active_founder_memberships(db, workspace.id)
    if len(founders_after) != 1 or founders_after[0].id != target_membership.id:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Workspace founder invariant is broken")

    db.commit()
    db.refresh(previous_founder)
    db.refresh(target_membership)

    return {
        "workspace_id": workspace.id,
        "founder_membership": serialize_workspace_member(target_membership, _get_membership_user_or_404(db, target_membership)),
        "previous_founder_membership": serialize_workspace_member(
            previous_founder,
            _get_membership_user_or_404(db, previous_founder),
        ),
    }


def archive_workspace(
    db: Session,
    principal: Principal,
    workspace_id: str,
) -> dict[str, object]:
    workspace = _get_workspace_for_admin_operation(db, principal, workspace_id)
    _require_archive_actor(principal)

    if workspace.is_default:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Default workspace cannot be archived")

    now = datetime.utcnow()
    workspace.status = ARCHIVED_STATUS
    workspace.archived_at = now
    workspace.archived_by = principal.user_id
    workspace.updated_at = now
    db.commit()
    db.refresh(workspace)
    return serialize_workspace_admin_workspace(workspace)


def _get_workspace_for_admin_operation(
    db: Session,
    principal: Principal,
    workspace_id: str,
) -> Workspace:
    workspace = get_workspace_or_404(db, workspace_id)
    if workspace.id != principal.workspace_id and not _is_platform_admin_actor(principal):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    if workspace.status != ACTIVE_STATUS or is_workspace_archived(workspace):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Workspace is archived")
    return workspace


def _require_member_management_actor(principal: Principal) -> None:
    if _is_platform_admin_actor(principal):
        return
    if principal.workspace_membership_role not in {"founder", "admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workspace member management is forbidden")
    if not principal.has_workspace_capability("can_manage_members"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing workspace capability: can_manage_members")


def _require_founder_transfer_actor(principal: Principal) -> None:
    if _is_platform_admin_actor(principal):
        return
    if principal.workspace_membership_role != "founder":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Founder transfer is forbidden")
    if not principal.has_workspace_capability("can_transfer_founder"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing workspace capability: can_transfer_founder")


def _require_archive_actor(principal: Principal) -> None:
    if _is_platform_admin_actor(principal):
        return
    if principal.workspace_membership_role != "founder":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workspace archive is forbidden")
    if not principal.has_workspace_capability("can_archive_workspace"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing workspace capability: can_archive_workspace")


def _assert_assignable_role(
    principal: Principal,
    role: str,
) -> None:
    if role == "founder":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Founder role must be transferred via founder transfer")
    if _is_platform_admin_actor(principal):
        return
    if principal.workspace_membership_role == "founder":
        return
    if principal.workspace_membership_role != "admin" or role not in ADMIN_MANAGEABLE_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admins can create only member or guest memberships")


def _assert_manageable_target(
    principal: Principal,
    membership: WorkspaceMembership,
    *,
    desired_role: str,
) -> None:
    if membership.role == "founder" or desired_role == "founder":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Founder membership must be managed via founder transfer",
        )
    if _is_platform_admin_actor(principal):
        return
    if principal.workspace_membership_role == "founder":
        return
    if principal.workspace_membership_role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workspace member management is forbidden")
    if membership.role not in ADMIN_MANAGEABLE_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admins can manage only member or guest memberships")
    if desired_role not in ADMIN_MANAGEABLE_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admins cannot assign admin or founder role")


def _validate_membership_role(role: str) -> None:
    if role not in WORKSPACE_MEMBERSHIP_ROLES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid workspace membership role")


def _validate_membership_status(status_value: str) -> None:
    if status_value not in WORKSPACE_MEMBERSHIP_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid workspace membership status")


def _get_membership_user_or_404(
    db: Session,
    membership: WorkspaceMembership,
) -> User:
    user = db.get(User, membership.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace membership user not found")
    return user


def _is_platform_admin_actor(principal: Principal) -> bool:
    return principal.kind == "session" and principal.user.is_platform_admin


def _is_active_founder_conflict_error(exc: IntegrityError) -> bool:
    message = str(exc.orig).lower() if exc.orig is not None else str(exc).lower()
    return (
        "uq_workspace_memberships_active_founder_workspace_id" in message
        or "active_founder_workspace_id" in message
    )


def normalize_workspace_slug(raw_slug: str | None) -> str:
    if raw_slug is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Workspace slug is required")

    slug = raw_slug.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    if not slug:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Workspace slug is invalid")
    if len(slug) > 128:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Workspace slug is too long")
    return slug
