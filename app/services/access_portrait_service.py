from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.auth import resolve_auth_context
from app.models import (
    ApiKey,
    ChatRun,
    ChatSession,
    ChatSkill,
    KnowledgeBase,
    ModelProvider,
    Tenant,
    TenantMembership,
    User,
    Workspace,
    WorkspaceInvite,
    WorkspaceMembership,
)
from app.services.workspace_access_service import (
    parse_workspace_permissions_override,
    resolve_workspace_capabilities,
)
from app.services.workspace_membership_service import list_active_founder_memberships


def get_platform_user_access_portrait(
    db: Session,
    user_id: str,
    *,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
) -> dict[str, object]:
    user = _get_user_or_404(db, user_id)
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

    requested_context = {
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
    }
    platform_permissions = {
        "can_access_platform_control_plane": bool(user.is_active and user.is_platform_admin),
        "can_create_workspace": bool(user.is_active and (user.can_create_workspace or user.is_platform_admin)),
    }
    allowed_reasons, denied_reasons = _build_user_flag_explainability(user)
    resolved_context: dict[str, object] | None = None
    effective_tenant_membership = {
        "id": None,
        "tenant_id": None,
        "role": None,
        "status": None,
    }
    effective_workspace_membership = {
        "id": None,
        "workspace_id": None,
        "user_id": None,
        "role": None,
        "status": None,
        "permissions_override": {},
        "effective_permissions": {},
    }
    resource_rules = _empty_resource_rules()

    try:
        context = resolve_auth_context(
            db,
            user,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
        resolved_context = {
            "tenant_id": context.tenant_id,
            "workspace_id": context.workspace.id,
            "source": "explicit" if tenant_id is not None or workspace_id is not None else "login_default",
        }
        effective_tenant_membership = {
            "id": context.tenant_membership.id,
            "tenant_id": context.tenant_membership.tenant_id,
            "role": context.tenant_membership.role,
            "status": context.tenant_membership.status,
        }
        effective_workspace_membership = {
            "id": context.workspace_membership.id,
            "workspace_id": context.workspace_membership.workspace_id,
            "user_id": context.workspace_membership.user_id,
            "role": context.workspace_membership.role,
            "status": context.workspace_membership.status,
            "permissions_override": parse_workspace_permissions_override(
                context.workspace_membership.permissions_override_json
            ),
            "effective_permissions": context.workspace_permissions,
        }
        allowed_reasons.extend(
            [
                f"Resolved tenant membership via {resolved_context['source']} context.",
                f"Workspace membership role {context.workspace_membership.role} grants {sum(1 for value in context.workspace_permissions.values() if value)} enabled capabilities.",
            ]
        )
        resource_rules = _build_user_resource_rules(
            db,
            user=user,
            tenant_id=context.tenant_id,
            workspace_id=context.workspace.id,
        )
    except HTTPException as exc:
        denied_reasons.append(str(exc.detail))

    return {
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "flags": {
                "is_active": user.is_active,
                "can_create_workspace": user.can_create_workspace,
                "is_platform_admin": user.is_platform_admin,
                "must_change_password": user.must_change_password,
            },
            "compat_tenant_id": user.tenant_id,
        },
        "raw_memberships": {
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
        },
        "effective_portrait": {
            "requested_context": requested_context,
            "resolved_context": resolved_context,
            "tenant_membership": effective_tenant_membership,
            "workspace_membership": effective_workspace_membership,
            "platform_permissions": platform_permissions,
            "explainability": {
                "allowed_reasons": allowed_reasons,
                "denied_reasons": denied_reasons,
            },
        },
        "resource_rules": resource_rules,
    }


def get_platform_workspace_access_portrait(
    db: Session,
    workspace_id: str,
) -> dict[str, object]:
    row = db.execute(
        select(Workspace, Tenant)
        .join(Tenant, Tenant.id == Workspace.tenant_id)
        .where(Workspace.id == workspace_id)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    workspace, tenant = row

    member_rows = db.execute(
        select(WorkspaceMembership, User)
        .join(User, User.id == WorkspaceMembership.user_id)
        .where(WorkspaceMembership.workspace_id == workspace.id)
        .order_by(WorkspaceMembership.created_at.asc(), WorkspaceMembership.id.asc())
    ).all()
    founder_memberships = list_active_founder_memberships(db, workspace.id)
    founder_membership = founder_memberships[0] if founder_memberships else None
    founder_user = None
    if founder_membership is not None:
        founder_user = db.get(User, founder_membership.user_id)

    by_role = {role: 0 for role in ("founder", "admin", "member", "guest")}
    active_count = 0
    members_payload: list[dict[str, object]] = []
    for membership, user in member_rows:
        if membership.status == "active":
            active_count += 1
            by_role[membership.role] = by_role.get(membership.role, 0) + 1
        members_payload.append(
            {
                "id": membership.id,
                "user_id": membership.user_id,
                "username": user.username,
                "email": user.email,
                "role": membership.role,
                "status": membership.status,
                "permissions_override": parse_workspace_permissions_override(
                    membership.permissions_override_json
                ),
                "effective_permissions": resolve_workspace_capabilities(
                    membership.role,
                    membership.permissions_override_json,
                ),
                "created_at": membership.created_at,
                "updated_at": membership.updated_at,
            }
        )

    invite_counts = {"pending": 0, "accepted": 0, "expired": 0, "revoked": 0}
    for invite in db.scalars(
        select(WorkspaceInvite).where(WorkspaceInvite.workspace_id == workspace.id)
    ).all():
        invite_counts[_effective_invite_status(invite)] += 1

    return {
        "workspace": {
            "id": workspace.id,
            "tenant_id": workspace.tenant_id,
            "name": workspace.name,
            "slug": workspace.slug,
            "status": workspace.status,
            "is_default": workspace.is_default,
        },
        "tenant": {
            "id": tenant.id,
            "name": tenant.name,
            "status": tenant.status,
        },
        "founder": {
            "membership_id": founder_membership.id if founder_membership is not None else None,
            "user_id": founder_user.id if founder_user is not None else None,
            "username": founder_user.username if founder_user is not None else None,
            "email": founder_user.email if founder_user is not None else None,
        },
        "membership_summary": {
            "total": len(member_rows),
            "active": active_count,
            "by_role": by_role,
            "active_founder_invariant_ok": len(founder_memberships) == 1,
        },
        "members": members_payload,
        "invite_summary": invite_counts,
        "resource_scope": _build_workspace_resource_scope(
            db,
            tenant_id=workspace.tenant_id,
            workspace_id=workspace.id,
        ),
        "archive_state": {
            "status": workspace.status,
            "archived_at": workspace.archived_at,
            "archived_by": workspace.archived_by,
        },
    }


def _build_user_flag_explainability(user: User) -> tuple[list[str], list[str]]:
    allowed_reasons: list[str] = []
    denied_reasons: list[str] = []
    if user.is_active:
        allowed_reasons.append("User is active.")
    else:
        denied_reasons.append("User is inactive.")
    if user.is_platform_admin:
        allowed_reasons.append("Platform admin flag allows platform control-plane access.")
    else:
        denied_reasons.append("Platform control-plane access denied because is_platform_admin=false.")
    if user.can_create_workspace or user.is_platform_admin:
        allowed_reasons.append("Workspace creation is allowed by can_create_workspace or platform-admin bypass.")
    else:
        denied_reasons.append("Workspace creation denied because can_create_workspace=false.")
    if user.must_change_password:
        denied_reasons.append("User must change password on next login.")
    else:
        allowed_reasons.append("Password lifecycle does not currently block session continuation.")
    return allowed_reasons, denied_reasons


def _empty_resource_rules() -> dict[str, dict[str, object]]:
    return {
        "providers": _resource_rule(
            scope="unresolved",
            explanation="No effective tenant/workspace context could be resolved for provider scope.",
            counts={},
        ),
        "api_keys": _resource_rule(
            scope="unresolved",
            explanation="No effective workspace context could be resolved for API key scope.",
            counts={},
        ),
        "knowledge_bases": _resource_rule(
            scope="unresolved",
            explanation="No effective workspace context could be resolved for knowledge base scope.",
            counts={},
        ),
        "skills": _resource_rule(
            scope="unresolved",
            explanation="No effective workspace context could be resolved for skill scope.",
            counts={},
        ),
        "sessions_runs": _resource_rule(
            scope="unresolved",
            explanation="No effective workspace context could be resolved for session/run scope.",
            counts={},
        ),
    }


def _resource_rule(*, scope: str, explanation: str, counts: dict[str, int]) -> dict[str, object]:
    return {
        "scope": scope,
        "explanation": explanation,
        "counts": counts,
    }


def _build_user_resource_rules(
    db: Session,
    *,
    user: User,
    tenant_id: str,
    workspace_id: str,
) -> dict[str, dict[str, object]]:
    provider_total, provider_shared, provider_bound = db.execute(
        select(
            func.count(ModelProvider.id),
            func.sum(case((ModelProvider.workspace_id.is_(None), 1), else_=0)),
            func.sum(case((ModelProvider.workspace_id == workspace_id, 1), else_=0)),
        ).where(ModelProvider.tenant_id == tenant_id)
    ).one()
    kb_total, kb_owned, kb_private, kb_workspace_read, kb_workspace_edit = db.execute(
        select(
            func.count(KnowledgeBase.id),
            func.sum(case((KnowledgeBase.created_by == user.id, 1), else_=0)),
            func.sum(case((KnowledgeBase.visibility == "private", 1), else_=0)),
            func.sum(case((KnowledgeBase.visibility == "workspace_read", 1), else_=0)),
            func.sum(case((KnowledgeBase.visibility == "workspace_edit", 1), else_=0)),
        ).where(
            KnowledgeBase.tenant_id == tenant_id,
            KnowledgeBase.workspace_id == workspace_id,
        )
    ).one()
    skill_total, skill_owned, skill_private, skill_workspace_read, skill_workspace_edit = db.execute(
        select(
            func.count(ChatSkill.id),
            func.sum(case((ChatSkill.owner_user_id == user.id, 1), else_=0)),
            func.sum(case((ChatSkill.visibility == "private", 1), else_=0)),
            func.sum(case((ChatSkill.visibility == "workspace_read", 1), else_=0)),
            func.sum(case((ChatSkill.visibility == "workspace_edit", 1), else_=0)),
        ).where(
            ChatSkill.tenant_id == tenant_id,
            ChatSkill.workspace_id == workspace_id,
        )
    ).one()
    active_run_statuses = ("accepted", "queued", "retrieving", "answering")
    api_key_total, api_key_active, api_key_owned = db.execute(
        select(
            func.count(ApiKey.id),
            func.sum(case((ApiKey.status == "active", 1), else_=0)),
            func.sum(case((ApiKey.created_by == user.id, 1), else_=0)),
        ).where(
            ApiKey.tenant_id == tenant_id,
            ApiKey.workspace_id == workspace_id,
        )
    ).one()
    session_count = db.scalar(
        select(func.count(ChatSession.id)).where(
            ChatSession.tenant_id == tenant_id,
            ChatSession.workspace_id == workspace_id,
            ChatSession.user_id == user.id,
        )
    ) or 0
    run_count, active_run_count = db.execute(
        select(
            func.count(ChatRun.id),
            func.sum(case((ChatRun.status.in_(active_run_statuses), 1), else_=0)),
        ).where(
            ChatRun.tenant_id == tenant_id,
            ChatRun.workspace_id == workspace_id,
            ChatRun.user_id == user.id,
        )
    ).one()
    return {
        "providers": _resource_rule(
            scope="tenant_shared_or_workspace_bound",
            explanation="System providers are tenant-shared; user-created providers are accessible when shared or bound to the resolved workspace.",
            counts={
                "tenant_total": int(provider_total or 0),
                "tenant_shared": int(provider_shared or 0),
                "workspace_bound": int(provider_bound or 0),
                "accessible_in_context": int((provider_shared or 0) + (provider_bound or 0)),
            },
        ),
        "api_keys": _resource_rule(
            scope="workspace",
            explanation="API keys are workspace-scoped and require the resolved workspace context.",
            counts={
                "workspace_total": int(api_key_total or 0),
                "active": int(api_key_active or 0),
                "owned_by_user": int(api_key_owned or 0),
            },
        ),
        "knowledge_bases": _resource_rule(
            scope="workspace_visibility",
            explanation="Knowledge bases are workspace-scoped; visibility controls whether non-admin members may read/edit them.",
            counts={
                "workspace_total": int(kb_total or 0),
                "owned_by_user": int(kb_owned or 0),
                "private": int(kb_private or 0),
                "workspace_read": int(kb_workspace_read or 0),
                "workspace_edit": int(kb_workspace_edit or 0),
            },
        ),
        "skills": _resource_rule(
            scope="workspace_visibility",
            explanation="Skills are workspace-scoped; visibility and workspace membership decide whether they may be read or edited.",
            counts={
                "workspace_total": int(skill_total or 0),
                "owned_by_user": int(skill_owned or 0),
                "private": int(skill_private or 0),
                "workspace_read": int(skill_workspace_read or 0),
                "workspace_edit": int(skill_workspace_edit or 0),
            },
        ),
        "sessions_runs": _resource_rule(
            scope="workspace_user_owned",
            explanation="Sessions and runs remain workspace-scoped and are counted here for the resolved user/context pair.",
            counts={
                "sessions_owned_by_user": int(session_count or 0),
                "runs_owned_by_user": int(run_count or 0),
                "active_runs_owned_by_user": int(active_run_count or 0),
            },
        ),
    }


def _build_workspace_resource_scope(
    db: Session,
    *,
    tenant_id: str,
    workspace_id: str,
) -> dict[str, dict[str, object]]:
    provider_total, provider_shared, provider_bound = db.execute(
        select(
            func.count(ModelProvider.id),
            func.sum(case((ModelProvider.workspace_id.is_(None), 1), else_=0)),
            func.sum(case((ModelProvider.workspace_id == workspace_id, 1), else_=0)),
        ).where(ModelProvider.tenant_id == tenant_id)
    ).one()
    api_key_total, api_key_active = db.execute(
        select(
            func.count(ApiKey.id),
            func.sum(case((ApiKey.status == "active", 1), else_=0)),
        ).where(
            ApiKey.tenant_id == tenant_id,
            ApiKey.workspace_id == workspace_id,
        )
    ).one()
    kb_total, kb_private, kb_workspace_read, kb_workspace_edit = db.execute(
        select(
            func.count(KnowledgeBase.id),
            func.sum(case((KnowledgeBase.visibility == "private", 1), else_=0)),
            func.sum(case((KnowledgeBase.visibility == "workspace_read", 1), else_=0)),
            func.sum(case((KnowledgeBase.visibility == "workspace_edit", 1), else_=0)),
        ).where(
            KnowledgeBase.tenant_id == tenant_id,
            KnowledgeBase.workspace_id == workspace_id,
        )
    ).one()
    skill_total, skill_active, skill_private, skill_workspace_read, skill_workspace_edit = db.execute(
        select(
            func.count(ChatSkill.id),
            func.sum(case((ChatSkill.is_active.is_(True), 1), else_=0)),
            func.sum(case((ChatSkill.visibility == "private", 1), else_=0)),
            func.sum(case((ChatSkill.visibility == "workspace_read", 1), else_=0)),
            func.sum(case((ChatSkill.visibility == "workspace_edit", 1), else_=0)),
        ).where(
            ChatSkill.tenant_id == tenant_id,
            ChatSkill.workspace_id == workspace_id,
        )
    ).one()
    active_run_statuses = ("accepted", "queued", "retrieving", "answering")
    session_count = db.scalar(
        select(func.count(ChatSession.id)).where(
            ChatSession.tenant_id == tenant_id,
            ChatSession.workspace_id == workspace_id,
        )
    ) or 0
    run_count, active_run_count = db.execute(
        select(
            func.count(ChatRun.id),
            func.sum(case((ChatRun.status.in_(active_run_statuses), 1), else_=0)),
        ).where(
            ChatRun.tenant_id == tenant_id,
            ChatRun.workspace_id == workspace_id,
        )
    ).one()
    return {
        "providers": _resource_rule(
            scope="tenant_shared_or_workspace_bound",
            explanation="This workspace may use tenant-shared providers plus providers explicitly bound to this workspace.",
            counts={
                "tenant_total": int(provider_total or 0),
                "tenant_shared": int(provider_shared or 0),
                "workspace_bound": int(provider_bound or 0),
                "accessible_in_workspace": int((provider_shared or 0) + (provider_bound or 0)),
            },
        ),
        "api_keys": _resource_rule(
            scope="workspace",
            explanation="API keys are scoped to a workspace and cannot cross into /api/v1/platform/*.",
            counts={
                "workspace_total": int(api_key_total or 0),
                "active": int(api_key_active or 0),
            },
        ),
        "knowledge_bases": _resource_rule(
            scope="workspace_visibility",
            explanation="Knowledge bases live inside a workspace; visibility determines whether non-admin members may consume them.",
            counts={
                "workspace_total": int(kb_total or 0),
                "private": int(kb_private or 0),
                "workspace_read": int(kb_workspace_read or 0),
                "workspace_edit": int(kb_workspace_edit or 0),
            },
        ),
        "skills": _resource_rule(
            scope="workspace_visibility",
            explanation="Skills are workspace resources; visibility governs read access while membership capabilities govern management actions.",
            counts={
                "workspace_total": int(skill_total or 0),
                "active": int(skill_active or 0),
                "private": int(skill_private or 0),
                "workspace_read": int(skill_workspace_read or 0),
                "workspace_edit": int(skill_workspace_edit or 0),
            },
        ),
        "sessions_runs": _resource_rule(
            scope="workspace",
            explanation="Chat sessions and runs are counted at workspace scope so operators can explain where execution history lives.",
            counts={
                "sessions": int(session_count or 0),
                "runs": int(run_count or 0),
                "active_runs": int(active_run_count or 0),
            },
        ),
    }


def _effective_invite_status(invite: WorkspaceInvite) -> str:
    if invite.status == "pending" and invite.expires_at <= datetime.utcnow():
        return "expired"
    return invite.status


def _get_user_or_404(db: Session, user_id: str) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user
