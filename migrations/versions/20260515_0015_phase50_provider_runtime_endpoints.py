"""Phase 5.0 provider runtime endpoints.

Revision ID: 20260515_0015
Revises: 20260427_0014
Create Date: 2026-05-15
"""

from alembic import op
import sqlalchemy as sa


revision = "20260515_0015"
down_revision = "20260427_0014"
branch_labels = None
depends_on = None


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return inspector.has_table(table_name)


def _chat_endpoint_id(provider_id: str) -> str:
    return f"endpoint_{provider_id}_chat"[:64]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "model_provider_endpoints"):
        op.create_table(
            "model_provider_endpoints",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("provider_id", sa.String(length=64), nullable=False),
            sa.Column("capability", sa.String(length=32), nullable=False),
            sa.Column("adapter", sa.String(length=64), nullable=False),
            sa.Column("base_url", sa.String(length=1024), nullable=False),
            sa.Column("model", sa.String(length=255), nullable=False),
            sa.Column("api_key_encrypted", sa.Text(), nullable=True),
            sa.Column("extra_headers_json", sa.Text(), nullable=False),
            sa.Column("config_json", sa.Text(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("health_status", sa.String(length=32), nullable=False, server_default="unknown"),
            sa.Column("last_probe_at", sa.DateTime(), nullable=True),
            sa.Column("last_probe_latency_ms", sa.Integer(), nullable=True),
            sa.Column("last_probe_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["provider_id"], ["model_providers.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_model_provider_endpoints_provider_id", "model_provider_endpoints", ["provider_id"])
        op.create_index("ix_model_provider_endpoints_capability", "model_provider_endpoints", ["capability"])
        op.create_index(
            "ix_model_provider_endpoints_provider_capability",
            "model_provider_endpoints",
            ["provider_id", "capability"],
        )

    inspector = sa.inspect(bind)
    if not _has_table(inspector, "model_providers") or not _has_table(inspector, "model_provider_endpoints"):
        return

    now = sa.func.now()
    providers = bind.execute(
        sa.text(
            """
            SELECT id, base_url, default_model, extra_headers_json, enabled
            FROM model_providers
            """
        )
    ).mappings().all()
    for provider in providers:
        existing = bind.execute(
            sa.text(
                """
                SELECT id
                FROM model_provider_endpoints
                WHERE provider_id = :provider_id AND capability = 'chat'
                LIMIT 1
                """
            ),
            {"provider_id": provider["id"]},
        ).first()
        if existing is not None:
            continue
        bind.execute(
            sa.text(
                """
                INSERT INTO model_provider_endpoints (
                    id, provider_id, capability, adapter, base_url, model,
                    api_key_encrypted, extra_headers_json, config_json,
                    enabled, is_default, health_status,
                    last_probe_at, last_probe_latency_ms, last_probe_error,
                    created_at, updated_at
                )
                VALUES (
                    :id, :provider_id, 'chat', 'openai_chat', :base_url, :model,
                    NULL, :extra_headers_json, '{}',
                    :enabled, 1, 'unknown',
                    NULL, NULL, NULL,
                    :created_at, :updated_at
                )
                """
            ),
            {
                "id": _chat_endpoint_id(str(provider["id"])),
                "provider_id": provider["id"],
                "base_url": provider["base_url"],
                "model": provider["default_model"],
                "extra_headers_json": provider["extra_headers_json"] or "{}",
                "enabled": bool(provider["enabled"]),
                "created_at": bind.execute(sa.select(now)).scalar_one(),
                "updated_at": bind.execute(sa.select(now)).scalar_one(),
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, "model_provider_endpoints"):
        return
    index_names = {index["name"] for index in inspector.get_indexes("model_provider_endpoints")}
    if "ix_model_provider_endpoints_provider_capability" in index_names:
        op.drop_index("ix_model_provider_endpoints_provider_capability", table_name="model_provider_endpoints")
    if "ix_model_provider_endpoints_capability" in index_names:
        op.drop_index("ix_model_provider_endpoints_capability", table_name="model_provider_endpoints")
    if "ix_model_provider_endpoints_provider_id" in index_names:
        op.drop_index("ix_model_provider_endpoints_provider_id", table_name="model_provider_endpoints")
    op.drop_table("model_provider_endpoints")
