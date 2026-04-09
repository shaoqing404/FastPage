import json
from datetime import datetime
from pathlib import Path

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
from app.models import ModelProvider, Tenant, TenantMembership, User, Workspace


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
    command.upgrade(_migration_config(), "head")


def _ensure_default_workspace(db: Session, tenant_id: str, created_by: str | None) -> Workspace:
    workspace = db.scalar(
        select(Workspace).where(
            Workspace.tenant_id == tenant_id,
            Workspace.is_default.is_(True),
        )
    )
    if workspace is not None:
        return workspace

    workspace = Workspace(
        id=default_workspace_id_for_tenant(tenant_id),
        tenant_id=tenant_id,
        name="Default Workspace",
        slug="default",
        status="active",
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
        membership.status = "active"
        membership.role = role
        membership.updated_at = datetime.utcnow()
        return membership

    membership = TenantMembership(
        id=f"tm_{tenant_id}_{user_id}"[:64],
        tenant_id=tenant_id,
        user_id=user_id,
        role=role,
        status="active",
        created_by=created_by,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(membership)
    db.flush()
    return membership


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
            continue
        if provider.workspace_id is None:
            provider.workspace_id = default_workspace_id
            provider.updated_at = datetime.utcnow()
            changed = True
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

        user = db.scalar(select(User).where(User.username == settings.admin_username))
        if user is None:
            user = User(
                id="user_default",
                tenant_id=tenant.id,
                username=settings.admin_username,
                password_hash=hash_password(settings.admin_password),
                is_active=True,
            )
            db.add(user)
            db.flush()

        workspace = _ensure_default_workspace(db, tenant.id, user.id if user is not None else None)
        _ensure_membership(db, tenant.id, user.id, "owner", user.id)
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
            if workspace.default_provider_id is None and system_provider.is_default:
                workspace.default_provider_id = system_provider.id
                workspace.updated_at = datetime.utcnow()
            db.commit()
        else:
            _normalize_provider_workspace_scope(db, tenant.id, workspace.id)
            db.commit()
