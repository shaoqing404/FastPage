"""Phase 4.8 workspace provider uplift.

Revision ID: 20260421_0011
Revises: 20260416_0010
Create Date: 2026-04-21
"""

from alembic import op
import sqlalchemy as sa


revision = "20260421_0011"
down_revision = "20260416_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("model_providers"):
        column_names = {column["name"] for column in inspector.get_columns("model_providers")}
        if "share_mode" not in column_names:
            op.add_column("model_providers", sa.Column("share_mode", sa.String(length=16), nullable=False, server_default="all"))
        if "source_provider_id" not in column_names:
            op.add_column("model_providers", sa.Column("source_provider_id", sa.String(length=64), nullable=True))

        inspector = sa.inspect(bind)
        index_names = {index["name"] for index in inspector.get_indexes("model_providers")}
        if "ix_model_providers_source_provider_id" not in index_names:
            op.create_index("ix_model_providers_source_provider_id", "model_providers", ["source_provider_id"])

        foreign_keys = {foreign_key["constrained_columns"][0] for foreign_key in inspector.get_foreign_keys("model_providers") if foreign_key["constrained_columns"]}
        if "source_provider_id" not in foreign_keys:
            op.create_foreign_key(
                "fk_model_providers_source_provider_id_model_providers",
                "model_providers",
                "model_providers",
                ["source_provider_id"],
                ["id"],
            )

        op.execute(
            sa.text(
                """
                UPDATE model_providers
                SET share_mode = CASE
                    WHEN workspace_id IS NULL THEN 'all'
                    ELSE 'none'
                END
                """
            )
        )
        op.alter_column("model_providers", "share_mode", server_default=None)

    inspector = sa.inspect(bind)
    if not inspector.has_table("provider_workspace_shares"):
        op.create_table(
            "provider_workspace_shares",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("provider_id", sa.String(length=64), nullable=False),
            sa.Column("workspace_id", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["provider_id"], ["model_providers.id"]),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("provider_id", "workspace_id", name="uq_provider_workspace_share"),
        )
        op.create_index("ix_provider_workspace_shares_provider_id", "provider_workspace_shares", ["provider_id"])
        op.create_index("ix_provider_workspace_shares_workspace_id", "provider_workspace_shares", ["workspace_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("provider_workspace_shares"):
        index_names = {index["name"] for index in inspector.get_indexes("provider_workspace_shares")}
        if "ix_provider_workspace_shares_provider_id" in index_names:
            op.drop_index("ix_provider_workspace_shares_provider_id", table_name="provider_workspace_shares")
        if "ix_provider_workspace_shares_workspace_id" in index_names:
            op.drop_index("ix_provider_workspace_shares_workspace_id", table_name="provider_workspace_shares")
        op.drop_table("provider_workspace_shares")

    inspector = sa.inspect(bind)
    if inspector.has_table("model_providers"):
        foreign_key_names = {foreign_key["name"] for foreign_key in inspector.get_foreign_keys("model_providers")}
        if "fk_model_providers_source_provider_id_model_providers" in foreign_key_names:
            op.drop_constraint("fk_model_providers_source_provider_id_model_providers", "model_providers", type_="foreignkey")

        index_names = {index["name"] for index in inspector.get_indexes("model_providers")}
        if "ix_model_providers_source_provider_id" in index_names:
            op.drop_index("ix_model_providers_source_provider_id", table_name="model_providers")

        column_names = {column["name"] for column in inspector.get_columns("model_providers")}
        if "source_provider_id" in column_names:
            op.drop_column("model_providers", "source_provider_id")
        if "share_mode" in column_names:
            op.drop_column("model_providers", "share_mode")
