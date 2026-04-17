"""workspace_invite_service.py

Service layer for Phase 4 Batch E2: workspace invite flow.

Implements:
  - list_workspace_invites
  - create_workspace_invite
  - accept_workspace_invite
  - revoke_workspace_invite

Design notes
------------
- Email normalization is done centrally via ``normalize_email()``.
- Duplicate-pending check uses normalized email stored in DB.
- Expiry is handled **lazily**: an invite whose ``expires_at`` is in the past
  and whose ``status`` is still ``pending`` is treated as ``expired`` at
  read/accept/revoke time without necessarily writing ``status=expired`` back.
  The helper ``_effective_status()`` encapsulates this to keep behavior
  consistent across all operations.  We also *do* persist the transition
  (status=expired) when we encounter it during accept/revoke so that subsequent
  list calls reflect reality, but we do not run a background sweep.
- accept uses a plain ``session_user: User`` (not Principal) because the
  accepting user may not yet have a workspace or tenant membership.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.principal import Principal
from app.models import TenantMembership, User, Workspace, WorkspaceInvite, WorkspaceMembership
from app.services.workspace_access_service import (
    dump_workspace_permissions_override_json,
    parse_workspace_permissions_override,
)
from app.services.workspace_membership_service import (
    ACTIVE_STATUS,
    get_workspace_or_404,
    is_workspace_archived,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INVITE_DEFAULT_TTL_DAYS = 7

INVITE_ALLOWED_ROLES = frozenset({"admin", "member", "guest"})

# Roles that admin can invite (founder and admin invite are founder-only)
ADMIN_INVITE_ROLES = frozenset({"member", "guest"})


# ---------------------------------------------------------------------------
# Email normalization
# ---------------------------------------------------------------------------


def normalize_email(raw_email: str | None) -> str | None:
    """Return the canonical form of an email address: stripped + lower-cased.

    Returns ``None`` if the input is ``None`` or empty after stripping.
    """
    if not raw_email:
        return None
    normalized = raw_email.strip().lower()
    return normalized if normalized else None


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _effective_status(invite: WorkspaceInvite, now: datetime) -> str:
    """Return the runtime-effective status of an invite.

    A ``pending`` invite whose ``expires_at`` is in the past is reported as
    ``expired`` without requiring a DB write.  All other statuses are returned
    as-is.
    """
    if invite.status == "pending" and invite.expires_at <= now:
        return "expired"
    return invite.status


def serialize_invite(invite: WorkspaceInvite, *, now: datetime | None = None) -> dict[str, object]:
    if now is None:
        now = datetime.utcnow()
    return {
        "id": invite.id,
        "workspace_id": invite.workspace_id,
        "email": invite.email,
        "role": invite.role,
        "status": _effective_status(invite, now),
        "permissions_override": parse_workspace_permissions_override(invite.permissions_override_json),
        "invited_by": invite.invited_by,
        "accepted_user_id": invite.accepted_user_id,
        "expires_at": invite.expires_at,
        "accepted_at": invite.accepted_at,
        "revoked_at": invite.revoked_at,
        "created_at": invite.created_at,
        "updated_at": invite.updated_at,
    }


# ---------------------------------------------------------------------------
# Internal guards
# ---------------------------------------------------------------------------


def _get_workspace_for_invite_admin(
    db: Session,
    principal: Principal,
    workspace_id: str,
) -> Workspace:
    """Load workspace and validate it is the caller's active workspace (or platform admin bypass)."""
    workspace = get_workspace_or_404(db, workspace_id)
    if workspace.id != principal.workspace_id and not _is_platform_admin(principal):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    if is_workspace_archived(workspace) or workspace.status != ACTIVE_STATUS:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Workspace is archived")
    return workspace


def _require_invite_management_actor(principal: Principal) -> None:
    """Assert the principal has ``can_manage_invites``."""
    if _is_platform_admin(principal):
        return
    if principal.workspace_membership_role not in {"founder", "admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invite management is forbidden")
    if not principal.has_workspace_capability("can_manage_invites"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing workspace capability: can_manage_invites")


def _assert_invite_role_allowed(principal: Principal, role: str) -> None:
    """Validate the role the caller wants to assign via invite."""
    if role == "founder":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Founder role cannot be assigned via invite")
    if role not in INVITE_ALLOWED_ROLES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid invite role: {role}")
    if _is_platform_admin(principal):
        return
    if principal.workspace_membership_role == "founder":
        return
    # admin: may only invite member/guest
    if principal.workspace_membership_role == "admin" and role not in ADMIN_INVITE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admins may only invite member or guest",
        )


def _assert_revoke_role_allowed(principal: Principal, invite: WorkspaceInvite) -> None:
    """For revoke: admin cannot revoke admin invites."""
    if _is_platform_admin(principal):
        return
    if principal.workspace_membership_role == "founder":
        return
    if principal.workspace_membership_role == "admin" and invite.role not in ADMIN_INVITE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admins may only revoke member or guest invites",
        )


def _is_platform_admin(principal: Principal) -> bool:
    return principal.kind == "session" and principal.user.is_platform_admin


# ---------------------------------------------------------------------------
# Public API: list
# ---------------------------------------------------------------------------


def list_workspace_invites(
    db: Session,
    principal: Principal,
    workspace_id: str,
) -> list[dict[str, object]]:
    workspace = _get_workspace_for_invite_admin(db, principal, workspace_id)
    _require_invite_management_actor(principal)

    invites = db.scalars(
        select(WorkspaceInvite)
        .where(WorkspaceInvite.workspace_id == workspace.id)
        .order_by(WorkspaceInvite.created_at.desc(), WorkspaceInvite.id.asc())
    ).all()

    now = datetime.utcnow()
    return [serialize_invite(inv, now=now) for inv in invites]


# ---------------------------------------------------------------------------
# Public API: create
# ---------------------------------------------------------------------------


def create_workspace_invite(
    db: Session,
    principal: Principal,
    workspace_id: str,
    payload,
) -> dict[str, object]:
    workspace = _get_workspace_for_invite_admin(db, principal, workspace_id)
    _require_invite_management_actor(principal)

    role = payload.role
    _assert_invite_role_allowed(principal, role)

    # Normalize email
    raw_email: str = payload.email
    norm_email = normalize_email(raw_email)
    if not norm_email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email address")

    # Validate permissions_override
    override_json = dump_workspace_permissions_override_json(payload.permissions_override, role=role)

    # Duplicate pending invite check
    existing_pending = db.scalar(
        select(WorkspaceInvite).where(
            WorkspaceInvite.workspace_id == workspace.id,
            WorkspaceInvite.email == norm_email,
            WorkspaceInvite.status == "pending",
        )
    )
    if existing_pending is not None:
        # If the "pending" one is actually expired (lazy), persist and skip conflict
        now_check = datetime.utcnow()
        if existing_pending.expires_at <= now_check:
            # Persist expired status so it no longer blocks
            existing_pending.status = "expired"
            existing_pending.updated_at = now_check
            db.flush()
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A pending invite already exists for this email in this workspace",
            )

    # Determine expires_at
    if payload.expires_at is not None:
        expires_at = payload.expires_at
    else:
        expires_at = datetime.utcnow() + timedelta(days=INVITE_DEFAULT_TTL_DAYS)

    now = datetime.utcnow()
    invite = WorkspaceInvite(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        email=norm_email,
        role=role,
        permissions_override_json=override_json,
        status="pending",
        invited_by=principal.user_id,
        accepted_user_id=None,
        expires_at=expires_at,
        accepted_at=None,
        revoked_at=None,
        created_at=now,
        updated_at=now,
    )
    db.add(invite)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if _is_pending_invite_conflict_error(exc):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A pending invite already exists for this email in this workspace",
            ) from exc
        raise
    db.refresh(invite)
    return serialize_invite(invite)


# ---------------------------------------------------------------------------
# Public API: accept
# ---------------------------------------------------------------------------


def accept_workspace_invite(
    db: Session,
    session_user: User,
    invite_id: str,
) -> dict[str, object]:
    """Accept an invite.

    Auth model: requires only a valid bearer session user.  Principal /
    ``get_current_principal()`` is intentionally **not** used here — the
    accepting user may not yet have workspace or tenant membership.

    Transaction guarantee (single flush → commit):
      1. Ensure active TenantMembership in the invite's tenant.
      2. Create or reactivate WorkspaceMembership with invite role/override.
      3. Mark invite accepted.
      4. Repoint user.tenant_id to target tenant (compat field alignment).

    Post-commit:
      5. resolve_auth_context for target tenant/workspace.
      6. Issue new bearer token scoped to target tenant/workspace.
      7. Return invite + full auth handoff (token + workspace + memberships).
    """
    # Lazy import to avoid circular dependency at module load time.
    # auth.py imports workspace_membership_service; keeping this import local
    # to accept_workspace_invite prevents the cycle.
    from app.core.auth import create_access_token, resolve_auth_context  # noqa: PLC0415

    now = datetime.utcnow()

    # --- Load invite ---
    invite = db.get(WorkspaceInvite, invite_id)
    if invite is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")

    # --- Validate invite state ---
    eff_status = _effective_status(invite, now)
    if eff_status == "expired":
        # Persist so future reads are consistent
        invite.status = "expired"
        invite.updated_at = now
        db.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Invite has expired")
    if eff_status == "revoked":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Invite has been revoked")
    if eff_status == "accepted":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Invite has already been accepted")
    if eff_status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Invite is not pending (status={eff_status})")

    # --- Load workspace and check it is active ---
    workspace = db.get(Workspace, invite.workspace_id)
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    if is_workspace_archived(workspace) or workspace.status != ACTIVE_STATUS:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Workspace is archived; invite cannot be accepted")

    # --- Email match check ---
    user_email = normalize_email(session_user.email)
    if not user_email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account does not have an email address and cannot accept invite",
        )
    invite_email = invite.email  # already normalized at create-time
    if user_email != invite_email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your email does not match the invite target email",
        )

    # --- Validate invite role (paranoia check) ---
    if invite.role not in INVITE_ALLOWED_ROLES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Invite has invalid role: {invite.role}")

    # -----------------------------------------------------------------------
    # Begin transactional accept
    # -----------------------------------------------------------------------

    target_tenant_id = workspace.tenant_id

    # 1. Ensure user has an active TenantMembership in the target tenant
    _ensure_active_tenant_membership(db, session_user, target_tenant_id, now=now)

    # 2. Create or reactivate WorkspaceMembership
    membership = _upsert_workspace_membership(db, session_user, workspace, invite, now=now)

    # 3. Mark invite as accepted
    invite.status = "accepted"
    invite.accepted_user_id = session_user.id
    invite.accepted_at = now
    invite.updated_at = now

    # 4. Align the compat field user.tenant_id to the target tenant.
    #    This prevents the default auth resolution from falling back to the
    #    user's original tenant after a successful cross-tenant accept.
    #    user.tenant_id is a Phase 3 compat field; Phase 4 principal resolution
    #    uses tenant_membership directly, but the fallback path in
    #    resolve_active_tenant_membership still reads this field.
    if session_user.tenant_id != target_tenant_id:
        session_user.tenant_id = target_tenant_id
        session_user.updated_at = now

    db.flush()
    db.commit()
    db.refresh(invite)
    db.refresh(membership)
    db.refresh(session_user)

    # -----------------------------------------------------------------------
    # Post-commit: build auth handoff for target tenant/workspace
    # -----------------------------------------------------------------------
    auth_context = resolve_auth_context(
        db,
        session_user,
        tenant_id=target_tenant_id,
        workspace_id=workspace.id,
    )
    new_token = create_access_token(auth_context)

    wm = auth_context.workspace_membership
    tm = auth_context.tenant_membership
    ws = auth_context.workspace

    return {
        "invite": serialize_invite(invite, now=now),
        "access_token": new_token,
        "token_type": "bearer",
        "workspace": {
            "id": ws.id,
            "tenant_id": ws.tenant_id,
            "name": ws.name,
            "slug": ws.slug,
            "status": ws.status,
            "is_default": ws.is_default,
        },
        "tenant_membership": {
            "id": tm.id,
            "tenant_id": tm.tenant_id,
            "role": tm.role,
            "status": tm.status,
        },
        "workspace_membership": {
            "id": wm.id,
            "workspace_id": wm.workspace_id,
            "user_id": wm.user_id,
            "role": wm.role,
            "status": wm.status,
            "permissions_override": parse_workspace_permissions_override(wm.permissions_override_json),
            "permissions": auth_context.workspace_permissions,
        },
    }


def _ensure_active_tenant_membership(
    db: Session,
    user: User,
    tenant_id: str,
    *,
    now: datetime,
) -> TenantMembership:
    """Ensure the user has an active TenantMembership in the given tenant.

    - If membership does not exist → create a minimal one (role='member', status='active').
    - If membership exists but disabled/removed → restore to active.
    - If membership is already active → no-op.
    """
    existing = db.scalar(
        select(TenantMembership).where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.user_id == user.id,
        )
    )
    if existing is None:
        tm = TenantMembership(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            user_id=user.id,
            role="member",
            status="active",
            created_by=None,
            created_at=now,
            updated_at=now,
        )
        db.add(tm)
        db.flush()
        return tm

    if existing.status != ACTIVE_STATUS:
        existing.status = ACTIVE_STATUS
        existing.updated_at = now
        db.flush()

    return existing


def _upsert_workspace_membership(
    db: Session,
    user: User,
    workspace: Workspace,
    invite: WorkspaceInvite,
    *,
    now: datetime,
) -> WorkspaceMembership:
    """Create or reactivate a WorkspaceMembership based on invite.

    Rules (from spec):
    - existing active membership → 409 (already joined)
    - existing disabled/removed → reactivate with invite role/override
    - no existing → create fresh
    - founder membership must not be granted via invite (paranoia guard)
    """
    existing = db.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace.id,
            WorkspaceMembership.user_id == user.id,
        )
    )

    override_json = invite.permissions_override_json

    if existing is not None:
        if existing.status == ACTIVE_STATUS:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User already has an active membership in this workspace",
            )
        # Reactivate
        if invite.role == "founder":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Founder role cannot be granted via invite")
        existing.role = invite.role
        existing.status = ACTIVE_STATUS
        existing.permissions_override_json = override_json
        existing.updated_at = now
        db.flush()
        return existing

    # Create new
    if invite.role == "founder":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Founder role cannot be granted via invite")

    membership = WorkspaceMembership(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        user_id=user.id,
        role=invite.role,
        status=ACTIVE_STATUS,
        permissions_override_json=override_json,
        created_by=None,
        created_at=now,
        updated_at=now,
    )
    db.add(membership)
    db.flush()
    return membership


def _is_pending_invite_conflict_error(exc: IntegrityError) -> bool:
    message = str(exc.orig).lower() if exc.orig is not None else str(exc).lower()
    return (
        "uq_workspace_invites_workspace_pending_normalized_email" in message
        or "pending_normalized_email" in message
    )


# ---------------------------------------------------------------------------
# Public API: revoke
# ---------------------------------------------------------------------------


def revoke_workspace_invite(
    db: Session,
    principal: Principal,
    workspace_id: str,
    invite_id: str,
) -> dict[str, object]:
    workspace = _get_workspace_for_invite_admin(db, principal, workspace_id)
    _require_invite_management_actor(principal)

    invite = db.scalar(
        select(WorkspaceInvite).where(
            WorkspaceInvite.id == invite_id,
            WorkspaceInvite.workspace_id == workspace.id,
        )
    )
    if invite is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")

    # Role boundary check for admin
    _assert_revoke_role_allowed(principal, invite)

    now = datetime.utcnow()
    eff_status = _effective_status(invite, now)

    if eff_status == "accepted":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Accepted invites cannot be revoked")
    if eff_status == "revoked":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Invite is already revoked")
    if eff_status == "expired":
        # Persist and report stable error
        invite.status = "expired"
        invite.updated_at = now
        db.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Invite has already expired and cannot be revoked")
    if eff_status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Invite cannot be revoked (status={eff_status})")

    invite.status = "revoked"
    invite.revoked_at = now
    invite.updated_at = now
    db.commit()
    db.refresh(invite)
    return serialize_invite(invite, now=now)


# ---------------------------------------------------------------------------
# Public API: preview (no auth required)
# ---------------------------------------------------------------------------


def _mask_email(email: str) -> str:
    """Return a masked version of an email, e.g. ``j***@example.com``."""
    parts = email.split("@", 1)
    if len(parts) != 2:
        return "***"
    local = parts[0]
    domain = parts[1]
    if len(local) <= 1:
        return f"*@{domain}"
    return f"{local[0]}***@{domain}"


def preview_workspace_invite(
    db: Session,
    invite_id: str,
) -> dict[str, object]:
    """Return a desensitized preview of an invite for unauthenticated users.

    Only returns minimal information needed to render the claim form.
    """
    invite = db.get(WorkspaceInvite, invite_id)
    if invite is None:
        return {"valid": False, "workspace_name": "", "role": "", "inviter_username": "", "email_masked": ""}

    now = datetime.utcnow()
    eff_status = _effective_status(invite, now)
    if eff_status != "pending":
        return {"valid": False, "workspace_name": "", "role": "", "inviter_username": "", "email_masked": ""}

    workspace = db.get(Workspace, invite.workspace_id)
    workspace_name = workspace.name if workspace else "Unknown workspace"

    inviter = db.get(User, invite.invited_by)
    inviter_username = inviter.username if inviter else "Unknown"

    return {
        "valid": True,
        "workspace_name": workspace_name,
        "role": invite.role,
        "inviter_username": inviter_username,
        "email_masked": _mask_email(invite.email),
    }


# ---------------------------------------------------------------------------
# Public API: claim (no auth required — invite UUID is the credential)
# ---------------------------------------------------------------------------


def claim_workspace_invite(
    db: Session,
    invite_id: str,
    password: str,
    username: str | None = None,
) -> dict[str, object]:
    """Claim an invite by setting a password and optionally a username.

    Two branches:
      A) invite email matches an existing User → set password if user has no
         real password yet, otherwise reject (ask them to log in).
      B) no matching User → auto-create User + TenantMembership, then accept.

    Returns a full auth handoff response (token + workspace + memberships).
    """
    from app.core.auth import create_access_token, hash_password, resolve_auth_context  # noqa: PLC0415

    now = datetime.utcnow()

    # --- Load invite ---
    invite = db.get(WorkspaceInvite, invite_id)
    if invite is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")

    # --- Validate invite state ---
    eff_status = _effective_status(invite, now)
    if eff_status == "expired":
        invite.status = "expired"
        invite.updated_at = now
        db.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Invite has expired")
    if eff_status == "revoked":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Invite has been revoked")
    if eff_status == "accepted":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Invite has already been accepted")
    if eff_status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Invite is not pending (status={eff_status})")

    # --- Load workspace ---
    workspace = db.get(Workspace, invite.workspace_id)
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    if is_workspace_archived(workspace) or workspace.status != ACTIVE_STATUS:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Workspace is archived")

    invite_email = invite.email  # already normalized at create-time
    target_tenant_id = workspace.tenant_id

    # --- Resolve or create user ---
    existing_user = db.scalar(select(User).where(User.email == invite_email))

    if existing_user is not None:
        # Branch A: existing user
        # Check if they already have a proper password
        if existing_user.password_hash and not existing_user.password_hash.startswith("PLACEHOLDER"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This email already has an account with a password. Please log in and accept the invite from your dashboard.",
            )
        # Set password for user with placeholder/empty hash
        existing_user.password_hash = hash_password(password)
        if username:
            # Check uniqueness
            conflict = db.scalar(select(User).where(User.username == username, User.id != existing_user.id))
            if conflict:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")
            existing_user.username = username
        existing_user.updated_at = now
        user = existing_user
    else:
        # Branch B: auto-create user
        final_username = username or invite_email.split("@")[0]
        # Ensure username uniqueness
        if db.scalar(select(User).where(User.username == final_username)):
            # Append a short suffix
            final_username = f"{final_username}_{uuid.uuid4().hex[:6]}"

        user = User(
            id=f"user_{uuid.uuid4().hex}",
            tenant_id=target_tenant_id,
            username=final_username,
            email=invite_email,
            password_hash=hash_password(password),
            is_active=True,
            can_create_workspace=False,
            is_platform_admin=False,
            must_change_password=False,
            created_at=now,
            updated_at=now,
        )
        db.add(user)
        db.flush()

    # --- Ensure tenant membership ---
    _ensure_active_tenant_membership(db, user, target_tenant_id, now=now)

    # --- Create or reactivate workspace membership ---
    membership = _upsert_workspace_membership(db, user, workspace, invite, now=now)

    # --- Mark invite as accepted ---
    invite.status = "accepted"
    invite.accepted_user_id = user.id
    invite.accepted_at = now
    invite.updated_at = now

    # --- Align compat field ---
    if user.tenant_id != target_tenant_id:
        user.tenant_id = target_tenant_id
        user.updated_at = now

    db.flush()
    db.commit()
    db.refresh(invite)
    db.refresh(membership)
    db.refresh(user)

    # --- Build auth handoff ---
    auth_context = resolve_auth_context(
        db,
        user,
        tenant_id=target_tenant_id,
        workspace_id=workspace.id,
    )
    new_token = create_access_token(auth_context)

    wm = auth_context.workspace_membership
    tm = auth_context.tenant_membership
    ws = auth_context.workspace

    return {
        "invite": serialize_invite(invite, now=now),
        "access_token": new_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "tenant_id": tm.tenant_id,
            "workspace_id": ws.id,
            "username": user.username,
            "email": user.email,
            "can_create_workspace": user.can_create_workspace,
            "is_platform_admin": user.is_platform_admin,
            "membership_role": wm.role,
            "tenant_membership_role": tm.role,
            "tenant_membership_status": tm.status,
            "workspace_membership_role": wm.role,
            "workspace_membership_status": wm.status,
        },
        "workspace": {
            "id": ws.id,
            "tenant_id": ws.tenant_id,
            "name": ws.name,
            "slug": ws.slug,
            "status": ws.status,
            "is_default": ws.is_default,
        },
        "tenant_membership": {
            "id": tm.id,
            "tenant_id": tm.tenant_id,
            "role": tm.role,
            "status": tm.status,
        },
        "workspace_membership": {
            "id": wm.id,
            "workspace_id": wm.workspace_id,
            "user_id": wm.user_id,
            "role": wm.role,
            "status": wm.status,
            "permissions_override": parse_workspace_permissions_override(wm.permissions_override_json),
            "permissions": auth_context.workspace_permissions,
        },
    }

