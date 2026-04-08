import json
from datetime import datetime

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from app.core.config import default_llm_model, get_settings
from app.core.db import Base, engine
from app.core.crypto import encrypt_text
from app.models import ModelProvider, Tenant, User


PHASE2_COLUMN_PATCHES = {
    "model_providers": [
        ("supported_models_json", "TEXT NULL"),
        ("managed_by_system", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ],
    "chat_sessions": [
        ("skill_id", "VARCHAR(64) NULL"),
    ],
    "chat_skills": [
        ("provider_id", "VARCHAR(64) NULL"),
        ("conversation_config_json", "TEXT NULL"),
        ("retrieval_config_json", "TEXT NULL"),
        ("generation_config_json", "TEXT NULL"),
    ],
    "chat_runs": [
        ("session_id", "VARCHAR(64) NULL"),
        ("provider_id", "VARCHAR(64) NULL"),
        ("answer_text", "TEXT NULL"),
        ("answer_with_marker", "TEXT NULL"),
        ("citations_json", "TEXT NULL"),
        ("execution_context_json", "TEXT NULL"),
    ],
}


def _ensure_phase2_columns() -> None:
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table_name, columns in PHASE2_COLUMN_PATCHES.items():
            if not inspector.has_table(table_name):
                continue
            existing = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, ddl in columns:
                if column_name in existing:
                    continue
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}"))
        if inspector.has_table("chat_skills"):
            conn.execute(
                text(
                    "UPDATE chat_skills SET conversation_config_json='{}' WHERE conversation_config_json IS NULL"
                )
            )
            conn.execute(
                text(
                    "UPDATE chat_skills SET retrieval_config_json='{}' WHERE retrieval_config_json IS NULL"
                )
            )
            conn.execute(
                text(
                    "UPDATE chat_skills SET generation_config_json='{}' WHERE generation_config_json IS NULL"
                )
            )
        if inspector.has_table("chat_runs"):
            conn.execute(
                text(
                    "UPDATE chat_runs SET citations_json='[]' WHERE citations_json IS NULL"
                )
            )
            conn.execute(
                text(
                    "UPDATE chat_runs SET execution_context_json='{}' WHERE execution_context_json IS NULL"
                )
            )
        if inspector.has_table("model_providers"):
            rows = conn.execute(
                text("SELECT id, default_model FROM model_providers WHERE supported_models_json IS NULL")
            ).fetchall()
            for row in rows:
                conn.execute(
                    text("UPDATE model_providers SET supported_models_json=:supported_models_json WHERE id=:provider_id"),
                    {
                        "supported_models_json": json.dumps([row.default_model], ensure_ascii=False),
                        "provider_id": row.id,
                    },
                )


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_phase2_columns()
    settings = get_settings()
    with Session(engine) as db:
        tenant = db.get(Tenant, "tenant_default")
        if tenant is None:
            tenant = Tenant(id="tenant_default", name="Default Tenant", status="active")
            db.add(tenant)
        user = db.scalar(select(User).where(User.username == settings.admin_username))
        if user is None:
            db.add(
                User(
                    id="user_default",
                    tenant_id="tenant_default",
                    username=settings.admin_username,
                    password_hash=settings.admin_password,
                    is_active=True,
                )
            )
        db.commit()
        if settings.llm_base_url and settings.llm_api_key:
            system_provider = db.scalar(
                select(ModelProvider).where(
                    ModelProvider.tenant_id == "tenant_default",
                    ModelProvider.managed_by_system.is_(True),
                )
            )
            existing_default_provider = db.scalar(
                select(ModelProvider).where(
                    ModelProvider.tenant_id == "tenant_default",
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
            }
            if system_provider is None:
                db.add(
                    ModelProvider(
                        id="provider_system_default",
                        tenant_id="tenant_default",
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow(),
                        is_default=existing_default_provider is None,
                        **system_payload,
                    )
                )
            else:
                for field, value in system_payload.items():
                    setattr(system_provider, field, value)
                system_provider.updated_at = datetime.utcnow()
            db.commit()
