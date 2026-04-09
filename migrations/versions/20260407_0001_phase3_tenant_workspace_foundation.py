"""phase3 tenant workspace foundation

Revision ID: 20260407_0001
Revises:
Create Date: 2026-04-07 14:30:00
"""

from __future__ import annotations

from datetime import datetime

from alembic import op
import sqlalchemy as sa


revision = "20260407_0001"
down_revision = None
branch_labels = None
depends_on = None


PHASE2_COLUMN_PATCHES = {
    "model_providers": [
        ("supported_models_json", sa.Text(), True),
        ("managed_by_system", sa.Boolean(), False),
    ],
    "chat_sessions": [
        ("skill_id", sa.String(length=64), True),
    ],
    "chat_skills": [
        ("provider_id", sa.String(length=64), True),
        ("conversation_config_json", sa.Text(), True),
        ("retrieval_config_json", sa.Text(), True),
        ("generation_config_json", sa.Text(), True),
    ],
    "chat_runs": [
        ("session_id", sa.String(length=64), True),
        ("provider_id", sa.String(length=64), True),
        ("answer_text", sa.Text(), True),
        ("answer_with_marker", sa.Text(), True),
        ("citations_json", sa.Text(), True),
        ("execution_context_json", sa.Text(), True),
    ],
}

WORKSPACE_COLUMNS = {
    "api_keys": "workspace_id",
    "documents": "workspace_id",
    "parse_jobs": "workspace_id",
    "chat_skills": "workspace_id",
    "chat_sessions": "workspace_id",
    "chat_messages": "workspace_id",
    "chat_runs": "workspace_id",
    "model_providers": "workspace_id",
}


def _default_workspace_id_for_tenant(tenant_id: str) -> str:
    suffix = tenant_id.replace("-", "_")
    return f"workspace_default_{suffix}"[:64]


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return inspector.has_table(table_name)


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def _has_index(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def _add_column_if_missing(
    inspector: sa.Inspector,
    table_name: str,
    column_name: str,
    column_type: sa.TypeEngine,
    nullable: bool,
) -> None:
    if not _has_table(inspector, table_name) or _has_column(inspector, table_name, column_name):
        return
    op.add_column(table_name, sa.Column(column_name, column_type, nullable=nullable))


def _create_index_if_missing(inspector: sa.Inspector, table_name: str, columns: list[str]) -> None:
    index_name = op.f(f"ix_{table_name}_{'_'.join(columns)}")
    if _has_table(inspector, table_name) and not _has_index(inspector, table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=False)


def _create_baseline_schema() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("username", sa.String(length=128), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )

    op.create_table(
        "revoked_tokens",
        sa.Column("jti", sa.String(length=128), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("jti"),
    )

    op.create_table(
        "model_providers",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=True),
        sa.Column("provider_type", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("base_url", sa.String(length=1024), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=False),
        sa.Column("default_model", sa.String(length=255), nullable=False),
        sa.Column("supported_models_json", sa.Text(), nullable=False),
        sa.Column("extra_headers_json", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("managed_by_system", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("default_provider_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["default_provider_id"], ["model_providers.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_workspaces_tenant_slug"),
    )

    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("key_prefix", sa.String(length=24), nullable=False),
        sa.Column("key_hash", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=True),
        sa.Column("owner_user_id", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("source_filename", sa.String(length=512), nullable=False),
        sa.Column("active_version_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "document_versions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("file_hash", sa.String(length=255), nullable=False),
        sa.Column("parse_status", sa.String(length=32), nullable=False),
        sa.Column("parsed_structure_path", sa.Text(), nullable=True),
        sa.Column("parse_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "parse_jobs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=True),
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("version_id", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("current_step", sa.String(length=64), nullable=True),
        sa.Column("progress_percent", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["version_id"], ["document_versions.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "chat_skills",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=True),
        sa.Column("owner_user_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("document_scope_type", sa.String(length=32), nullable=False),
        sa.Column("provider_id", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("request_config_json", sa.Text(), nullable=False),
        sa.Column("conversation_config_json", sa.Text(), nullable=False),
        sa.Column("retrieval_config_json", sa.Text(), nullable=False),
        sa.Column("generation_config_json", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["provider_id"], ["model_providers.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=True),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("skill_id", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["skill_id"], ["chat_skills.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "chat_runs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=True),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("document_id", sa.String(length=64), nullable=True),
        sa.Column("skill_id", sa.String(length=64), nullable=True),
        sa.Column("provider_id", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("answer_text", sa.Text(), nullable=True),
        sa.Column("answer_with_marker", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("selected_sections_json", sa.Text(), nullable=False),
        sa.Column("citations_json", sa.Text(), nullable=False),
        sa.Column("execution_context_json", sa.Text(), nullable=False),
        sa.Column("metrics_json", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["provider_id"], ["model_providers.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"]),
        sa.ForeignKeyConstraint(["skill_id"], ["chat_skills.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=True),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["chat_runs.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "chat_skill_documents",
        sa.Column("skill_id", sa.String(length=64), nullable=False),
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["skill_id"], ["chat_skills.id"]),
        sa.PrimaryKeyConstraint("skill_id", "document_id"),
    )

    op.create_table(
        "tenant_memberships",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="member"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_tenant_memberships_tenant_user"),
    )

    inspector = sa.inspect(op.get_bind())
    for table_name, columns in (
        ("users", ["tenant_id"]),
        ("users", ["username"]),
        ("api_keys", ["tenant_id"]),
        ("api_keys", ["workspace_id"]),
        ("api_keys", ["key_prefix"]),
        ("api_keys", ["status"]),
        ("api_keys", ["created_by"]),
        ("model_providers", ["tenant_id"]),
        ("model_providers", ["workspace_id"]),
        ("model_providers", ["provider_type"]),
        ("documents", ["tenant_id"]),
        ("documents", ["workspace_id"]),
        ("documents", ["owner_user_id"]),
        ("documents", ["status"]),
        ("document_versions", ["document_id"]),
        ("document_versions", ["parse_status"]),
        ("parse_jobs", ["tenant_id"]),
        ("parse_jobs", ["workspace_id"]),
        ("parse_jobs", ["document_id"]),
        ("parse_jobs", ["version_id"]),
        ("parse_jobs", ["status"]),
        ("chat_skills", ["tenant_id"]),
        ("chat_skills", ["workspace_id"]),
        ("chat_skills", ["owner_user_id"]),
        ("chat_skills", ["provider_id"]),
        ("chat_sessions", ["tenant_id"]),
        ("chat_sessions", ["workspace_id"]),
        ("chat_sessions", ["user_id"]),
        ("chat_sessions", ["skill_id"]),
        ("chat_runs", ["tenant_id"]),
        ("chat_runs", ["workspace_id"]),
        ("chat_runs", ["user_id"]),
        ("chat_runs", ["session_id"]),
        ("chat_runs", ["document_id"]),
        ("chat_runs", ["skill_id"]),
        ("chat_runs", ["provider_id"]),
        ("chat_runs", ["status"]),
        ("chat_messages", ["session_id"]),
        ("chat_messages", ["tenant_id"]),
        ("chat_messages", ["workspace_id"]),
        ("chat_messages", ["user_id"]),
        ("chat_messages", ["run_id"]),
        ("workspaces", ["tenant_id"]),
        ("workspaces", ["created_by"]),
        ("workspaces", ["default_provider_id"]),
        ("tenant_memberships", ["tenant_id"]),
        ("tenant_memberships", ["user_id"]),
        ("tenant_memberships", ["created_by"]),
    ):
        _create_index_if_missing(inspector, table_name, columns)
        inspector = sa.inspect(op.get_bind())


def _create_missing_tables(inspector: sa.Inspector) -> None:
    existing_tables = set(inspector.get_table_names()) - {"alembic_version"}
    if existing_tables:
        return
    _create_baseline_schema()


def _ensure_phase2_columns(inspector: sa.Inspector) -> None:
    for table_name, columns in PHASE2_COLUMN_PATCHES.items():
        if not _has_table(inspector, table_name):
            continue
        for column_name, column_type, nullable in columns:
            _add_column_if_missing(inspector, table_name, column_name, column_type, nullable)

    conn = op.get_bind()
    if _has_table(inspector, "chat_skills"):
        conn.execute(sa.text("UPDATE chat_skills SET conversation_config_json='{}' WHERE conversation_config_json IS NULL"))
        conn.execute(sa.text("UPDATE chat_skills SET retrieval_config_json='{}' WHERE retrieval_config_json IS NULL"))
        conn.execute(sa.text("UPDATE chat_skills SET generation_config_json='{}' WHERE generation_config_json IS NULL"))
    if _has_table(inspector, "chat_runs"):
        conn.execute(sa.text("UPDATE chat_runs SET citations_json='[]' WHERE citations_json IS NULL"))
        conn.execute(sa.text("UPDATE chat_runs SET execution_context_json='{}' WHERE execution_context_json IS NULL"))
    if _has_table(inspector, "model_providers") and _has_column(inspector, "model_providers", "supported_models_json"):
        rows = conn.execute(
            sa.text("SELECT id, default_model FROM model_providers WHERE supported_models_json IS NULL")
        ).mappings()
        for row in rows:
            conn.execute(
                sa.text(
                    "UPDATE model_providers "
                    "SET supported_models_json=:supported_models_json "
                    "WHERE id=:provider_id"
                ),
                {
                    "supported_models_json": f'["{row["default_model"]}"]',
                    "provider_id": row["id"],
                },
            )


def _ensure_workspace_tables(inspector: sa.Inspector) -> None:
    if not _has_table(inspector, "workspaces"):
        op.create_table(
            "workspaces",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("slug", sa.String(length=128), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_by", sa.String(length=64), nullable=True),
            sa.Column("default_provider_id", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["default_provider_id"], ["model_providers.id"]),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "slug", name="uq_workspaces_tenant_slug"),
        )
        op.create_index(op.f("ix_workspaces_tenant_id"), "workspaces", ["tenant_id"], unique=False)
        op.create_index(op.f("ix_workspaces_created_by"), "workspaces", ["created_by"], unique=False)
        op.create_index(op.f("ix_workspaces_default_provider_id"), "workspaces", ["default_provider_id"], unique=False)

    if not _has_table(inspector, "tenant_memberships"):
        op.create_table(
            "tenant_memberships",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.String(length=64), nullable=False),
            sa.Column("role", sa.String(length=32), nullable=False, server_default="member"),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
            sa.Column("created_by", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "user_id", name="uq_tenant_memberships_tenant_user"),
        )
        op.create_index(op.f("ix_tenant_memberships_tenant_id"), "tenant_memberships", ["tenant_id"], unique=False)
        op.create_index(op.f("ix_tenant_memberships_user_id"), "tenant_memberships", ["user_id"], unique=False)
        op.create_index(op.f("ix_tenant_memberships_created_by"), "tenant_memberships", ["created_by"], unique=False)


def _ensure_workspace_columns(inspector: sa.Inspector) -> None:
    for table_name, column_name in WORKSPACE_COLUMNS.items():
        if not _has_table(inspector, table_name):
            continue
        _add_column_if_missing(inspector, table_name, column_name, sa.String(length=64), True)
        inspector = sa.inspect(op.get_bind())
        index_name = f"ix_{table_name}_{column_name}"
        if not _has_index(inspector, table_name, index_name):
            op.create_index(index_name, table_name, [column_name], unique=False)


def _backfill_default_workspaces(inspector: sa.Inspector) -> None:
    if not _has_table(inspector, "tenants") or not _has_table(inspector, "workspaces"):
        return

    conn = op.get_bind()
    tenants = conn.execute(sa.text("SELECT id FROM tenants")).mappings().all()
    for tenant in tenants:
        tenant_id = tenant["id"]
        workspace_id = _default_workspace_id_for_tenant(tenant_id)
        existing_workspace = conn.execute(
            sa.text(
                "SELECT id FROM workspaces WHERE tenant_id=:tenant_id AND is_default = :is_default LIMIT 1"
            ),
            {"tenant_id": tenant_id, "is_default": True},
        ).scalar_one_or_none()
        if existing_workspace is not None:
            workspace_id = existing_workspace
        else:
            created_by = conn.execute(
                sa.text(
                    "SELECT id FROM users WHERE tenant_id=:tenant_id ORDER BY created_at ASC, id ASC LIMIT 1"
                ),
                {"tenant_id": tenant_id},
            ).scalar_one_or_none()
            default_provider_id = None
            if _has_table(inspector, "model_providers"):
                default_provider_id = conn.execute(
                    sa.text(
                        "SELECT id FROM model_providers "
                        "WHERE tenant_id=:tenant_id AND is_default = :is_default "
                        "ORDER BY created_at ASC LIMIT 1"
                    ),
                    {"tenant_id": tenant_id, "is_default": True},
                ).scalar_one_or_none()
            conn.execute(
                sa.text(
                    "INSERT INTO workspaces "
                    "(id, tenant_id, name, slug, status, is_default, created_by, default_provider_id, created_at, updated_at) "
                    "VALUES "
                    "(:id, :tenant_id, :name, :slug, :status, :is_default, :created_by, :default_provider_id, :created_at, :updated_at)"
                ),
                {
                    "id": workspace_id,
                    "tenant_id": tenant_id,
                    "name": "Default Workspace",
                    "slug": "default",
                    "status": "active",
                    "is_default": True,
                    "created_by": created_by,
                    "default_provider_id": default_provider_id,
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                },
            )


def _backfill_tenant_memberships(inspector: sa.Inspector) -> None:
    if not _has_table(inspector, "tenant_memberships") or not _has_table(inspector, "users"):
        return

    conn = op.get_bind()
    tenants = conn.execute(sa.text("SELECT id FROM tenants")).mappings().all()
    for tenant in tenants:
        tenant_id = tenant["id"]
        user_rows = conn.execute(
            sa.text(
                "SELECT id FROM users WHERE tenant_id=:tenant_id ORDER BY created_at ASC, id ASC"
            ),
            {"tenant_id": tenant_id},
        ).mappings().all()
        for index, row in enumerate(user_rows):
            user_id = row["id"]
            existing = conn.execute(
                sa.text(
                    "SELECT id FROM tenant_memberships WHERE tenant_id=:tenant_id AND user_id=:user_id LIMIT 1"
                ),
                {"tenant_id": tenant_id, "user_id": user_id},
            ).scalar_one_or_none()
            if existing is not None:
                continue
            conn.execute(
                sa.text(
                    "INSERT INTO tenant_memberships "
                    "(id, tenant_id, user_id, role, status, created_by, created_at, updated_at) "
                    "VALUES "
                    "(:id, :tenant_id, :user_id, :role, :status, :created_by, :created_at, :updated_at)"
                ),
                {
                    "id": f"tm_{tenant_id}_{user_id}"[:64],
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "role": "owner" if index == 0 else "member",
                    "status": "active",
                    "created_by": user_rows[0]["id"] if user_rows else None,
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                },
            )


def _backfill_workspace_scoped_resources(inspector: sa.Inspector) -> None:
    conn = op.get_bind()
    tenants = conn.execute(sa.text("SELECT id FROM tenants")).mappings().all() if _has_table(inspector, "tenants") else []
    for tenant in tenants:
        tenant_id = tenant["id"]
        workspace_id = conn.execute(
            sa.text(
                "SELECT id FROM workspaces WHERE tenant_id=:tenant_id AND is_default = :is_default LIMIT 1"
            ),
            {"tenant_id": tenant_id, "is_default": True},
        ).scalar_one_or_none()
        if workspace_id is None:
            continue
        for table_name in (
            "api_keys",
            "documents",
            "parse_jobs",
            "chat_skills",
            "chat_sessions",
            "chat_messages",
            "chat_runs",
        ):
            if not _has_table(inspector, table_name) or not _has_column(inspector, table_name, "workspace_id"):
                continue
            conn.execute(
                sa.text(
                    f"UPDATE {table_name} SET workspace_id=:workspace_id "
                    "WHERE tenant_id=:tenant_id AND workspace_id IS NULL"
                ),
                {"workspace_id": workspace_id, "tenant_id": tenant_id},
            )
        if _has_table(inspector, "model_providers") and _has_column(inspector, "model_providers", "workspace_id"):
            conn.execute(
                sa.text(
                    "UPDATE model_providers SET workspace_id=NULL "
                    "WHERE tenant_id=:tenant_id AND managed_by_system = :managed_by_system"
                ),
                {"tenant_id": tenant_id, "managed_by_system": True},
            )
            conn.execute(
                sa.text(
                    "UPDATE model_providers SET workspace_id=:workspace_id "
                    "WHERE tenant_id=:tenant_id "
                    "AND managed_by_system = :managed_by_system "
                    "AND workspace_id IS NULL"
                ),
                {
                    "workspace_id": workspace_id,
                    "tenant_id": tenant_id,
                    "managed_by_system": False,
                },
            )


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    _create_missing_tables(inspector)
    inspector = sa.inspect(op.get_bind())

    _ensure_phase2_columns(inspector)
    inspector = sa.inspect(op.get_bind())

    _ensure_workspace_tables(inspector)
    inspector = sa.inspect(op.get_bind())

    _ensure_workspace_columns(inspector)
    inspector = sa.inspect(op.get_bind())

    _backfill_default_workspaces(inspector)
    _backfill_tenant_memberships(inspector)
    _backfill_workspace_scoped_resources(inspector)


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for this baseline migration")
