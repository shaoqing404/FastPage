import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from alembic import command
    from alembic.config import Config
except ModuleNotFoundError:  # pragma: no cover - compatibility fallback for incomplete envs
    command = None
    Config = None
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import hash_password
from app.core.config import default_llm_model, get_settings
from app.core.crypto import encrypt_text
from app.core.db import Base, engine
from app.models import ModelProvider, Tenant, TenantMembership, User, Workspace, WorkspaceMembership


ACTIVE_STATUS = "active"
DEFAULT_TENANT_ROLE = "owner"
DEFAULT_WORKSPACE_ROLE = "founder"
FALLBACK_DEFAULT_WORKSPACE_ROLE = "admin"
DEFAULT_BOOTSTRAP_PLATFORM_ADMIN = True
DEFAULT_BOOTSTRAP_CAN_CREATE_WORKSPACE = True
VALID_WORKSPACE_ROLES = frozenset({"founder", "admin", "member", "guest"})
EMPTY_PERMISSIONS_OVERRIDE = "{}"


def default_workspace_id_for_tenant(tenant_id: str) -> str:
    suffix = tenant_id.replace("-", "_")
    workspace_id = f"workspace_default_{suffix}"
    return workspace_id[:64]


def _migration_config() -> Config:
    root = Path(__file__).resolve().parents[2]
    if Config is None:
        raise RuntimeError("Alembic is not installed")
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.set_main_option("sqlalchemy.url", get_settings().database_url)
    return config


def _run_migrations() -> None:
    if command is None:
        Base.metadata.create_all(bind=engine)
        return
    try:
        command.upgrade(_migration_config(), "head")
    except Exception as e:
        logger.error(f"Database migration failed during bootstrap: {e}")
        logger.error("Please ensure you have resolved any data inconsistencies (e.g. duplicate emails) before upgrading the database.")
        raise


def _ensure_default_workspace(db: Session, tenant_id: str, created_by: str | None) -> Workspace:
    workspace = db.scalar(
        select(Workspace).where(
            Workspace.tenant_id == tenant_id,
            Workspace.is_default.is_(True),
        )
    )
    if workspace is None:
        workspace = db.scalar(
            select(Workspace).where(
                Workspace.tenant_id == tenant_id,
                Workspace.id == default_workspace_id_for_tenant(tenant_id),
            )
        )
    if workspace is None:
        workspace = db.scalar(
            select(Workspace).where(
                Workspace.tenant_id == tenant_id,
                Workspace.slug == "default",
            )
        )
    if workspace is not None:
        changed = False
        if workspace.status != ACTIVE_STATUS:
            workspace.status = ACTIVE_STATUS
            changed = True
        if workspace.archived_at is not None:
            workspace.archived_at = None
            changed = True
        if workspace.archived_by is not None:
            workspace.archived_by = None
            changed = True
        if not workspace.is_default:
            workspace.is_default = True
            changed = True
        if workspace.created_by is None and created_by is not None:
            workspace.created_by = created_by
            changed = True
        if changed:
            workspace.updated_at = datetime.utcnow()
        return workspace

    workspace = Workspace(
        id=default_workspace_id_for_tenant(tenant_id),
        tenant_id=tenant_id,
        name="Default Workspace",
        slug="default",
        status=ACTIVE_STATUS,
        is_default=True,
        created_by=created_by,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(workspace)
    db.flush()
    return workspace


def _ensure_membership(db: Session, tenant_id: str, user_id: str, role: str, created_by: str | None) -> TenantMembership:
    membership = db.scalar(
        select(TenantMembership).where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.user_id == user_id,
        )
    )
    if membership is not None:
        changed = False
        if membership.status != ACTIVE_STATUS:
            membership.status = ACTIVE_STATUS
            changed = True
        if membership.role != role:
            membership.role = role
            changed = True
        if membership.created_by is None and created_by is not None:
            membership.created_by = created_by
            changed = True
        if changed:
            membership.updated_at = datetime.utcnow()
        return membership

    membership = TenantMembership(
        id=f"tm_{tenant_id}_{user_id}"[:64],
        tenant_id=tenant_id,
        user_id=user_id,
        role=role,
        status=ACTIVE_STATUS,
        created_by=created_by,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(membership)
    db.flush()
    return membership


def _active_founder_membership_for_workspace(db: Session, workspace_id: str) -> WorkspaceMembership | None:
    return db.scalar(
        select(WorkspaceMembership)
        .where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.role == DEFAULT_WORKSPACE_ROLE,
            WorkspaceMembership.status == ACTIVE_STATUS,
        )
        .order_by(WorkspaceMembership.created_at.asc(), WorkspaceMembership.id.asc())
    )


def _default_workspace_role_for_user(
    db: Session,
    workspace_id: str,
    user_id: str,
) -> str:
    active_founder = _active_founder_membership_for_workspace(db, workspace_id)
    if active_founder is None or active_founder.user_id == user_id:
        return DEFAULT_WORKSPACE_ROLE
    return FALLBACK_DEFAULT_WORKSPACE_ROLE


def _ensure_default_workspace_membership(
    db: Session,
    workspace_id: str,
    user_id: str,
    created_by: str | None,
) -> WorkspaceMembership:
    membership = db.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user_id,
        )
    )
    desired_role = _default_workspace_role_for_user(db, workspace_id, user_id)
    now = datetime.utcnow()

    if membership is not None:
        changed = False
        if membership.role not in VALID_WORKSPACE_ROLES or membership.role != desired_role:
            membership.role = desired_role
            changed = True
        if membership.status != ACTIVE_STATUS:
            membership.status = ACTIVE_STATUS
            changed = True
        if not membership.permissions_override_json:
            membership.permissions_override_json = EMPTY_PERMISSIONS_OVERRIDE
            changed = True
        if membership.created_by is None and created_by is not None:
            membership.created_by = created_by
            changed = True
        if changed:
            membership.updated_at = now
            db.flush()
        return membership

    membership = WorkspaceMembership(
        id=f"wm_{workspace_id}_{user_id}"[:64],
        workspace_id=workspace_id,
        user_id=user_id,
        role=desired_role,
        status=ACTIVE_STATUS,
        permissions_override_json=EMPTY_PERMISSIONS_OVERRIDE,
        created_by=created_by,
        created_at=now,
        updated_at=now,
    )
    db.add(membership)
    db.flush()
    return membership


def _ensure_default_admin_user_flags(user: User) -> bool:
    changed = False
    if not user.is_platform_admin:
        user.is_platform_admin = DEFAULT_BOOTSTRAP_PLATFORM_ADMIN
        changed = True
    if not user.can_create_workspace:
        user.can_create_workspace = DEFAULT_BOOTSTRAP_CAN_CREATE_WORKSPACE
        changed = True
    if changed:
        user.updated_at = datetime.utcnow()
    return changed


def _normalize_provider_workspace_scope(db: Session, tenant_id: str, default_workspace_id: str) -> None:
    providers = db.scalars(
        select(ModelProvider).where(ModelProvider.tenant_id == tenant_id)
    ).all()
    changed = False
    for provider in providers:
        if provider.managed_by_system:
            if provider.workspace_id is not None:
                provider.workspace_id = None
                provider.updated_at = datetime.utcnow()
                changed = True
            if getattr(provider, "share_mode", None) != "none":
                provider.share_mode = "none"
                provider.updated_at = datetime.utcnow()
                changed = True
            continue
    if changed:
        db.flush()


def init_db() -> None:
    _run_migrations()
    settings = get_settings()

    with Session(engine) as db:
        tenant = db.get(Tenant, "tenant_default")
        if tenant is None:
            tenant = Tenant(id="tenant_default", name="Default Tenant", status="active")
            db.add(tenant)
            db.flush()
        elif tenant.status != ACTIVE_STATUS:
            tenant.status = ACTIVE_STATUS

        user = db.scalar(select(User).where(User.username == settings.admin_username))
        if user is None:
            user = User(
                id="user_default",
                tenant_id=tenant.id,
                username=settings.admin_username,
                password_hash=hash_password(settings.admin_password),
                can_create_workspace=DEFAULT_BOOTSTRAP_CAN_CREATE_WORKSPACE,
                is_platform_admin=DEFAULT_BOOTSTRAP_PLATFORM_ADMIN,
                is_active=True,
            )
            db.add(user)
            db.flush()
        else:
            _ensure_default_admin_user_flags(user)
            if not user.is_active:
                user.is_active = True
                user.updated_at = datetime.utcnow()

        workspace = _ensure_default_workspace(db, tenant.id, user.id if user is not None else None)
        _ensure_membership(db, tenant.id, user.id, DEFAULT_TENANT_ROLE, user.id)
        _ensure_default_workspace_membership(db, workspace.id, user.id, user.id)
        db.commit()

        if settings.llm_base_url and settings.llm_api_key:
            system_provider = db.scalar(
                select(ModelProvider).where(
                    ModelProvider.tenant_id == tenant.id,
                    ModelProvider.managed_by_system.is_(True),
                )
            )
            existing_default_provider = db.scalar(
                select(ModelProvider).where(
                    ModelProvider.tenant_id == tenant.id,
                    ModelProvider.workspace_id.is_(None),
                    ModelProvider.is_default.is_(True),
                )
            )
            now_provider_model = default_llm_model()
            system_payload = {
                "provider_type": "system_default",
                "name": "System Default Provider",
                "base_url": settings.llm_base_url,
                "api_key_encrypted": encrypt_text(settings.secret_key, settings.llm_api_key),
                "default_model": now_provider_model,
                "supported_models_json": json.dumps([now_provider_model], ensure_ascii=False),
                "extra_headers_json": "{}",
                "enabled": True,
                "managed_by_system": True,
                "workspace_id": None,
                "share_mode": "none",
                "source_provider_id": None,
            }
            if system_provider is None:
                system_provider = ModelProvider(
                    id="provider_system_default",
                    tenant_id=tenant.id,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                    is_default=existing_default_provider is None,
                    **system_payload,
                )
                db.add(system_provider)
            else:
                for field, value in system_payload.items():
                    setattr(system_provider, field, value)
                system_provider.updated_at = datetime.utcnow()

            _normalize_provider_workspace_scope(db, tenant.id, workspace.id)
            db.flush()
            if workspace.default_provider_id == system_provider.id:
                workspace.default_provider_id = None
                workspace.updated_at = datetime.utcnow()
            if workspace.default_provider_id is None and existing_default_provider is not None and existing_default_provider.id != system_provider.id:
                workspace.default_provider_id = existing_default_provider.id
                workspace.updated_at = datetime.utcnow()
            db.commit()
        else:
            _normalize_provider_workspace_scope(db, tenant.id, workspace.id)
            db.commit()
