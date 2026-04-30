"""phase4.10 routing index schema foundation

Revision ID: 20260423_0013
Revises: 20260422_0012
Create Date: 2026-04-23 09:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260423_0013"
down_revision = "20260422_0012"
branch_labels = None
depends_on = None


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def _has_index(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def _has_unique_constraint(inspector: sa.Inspector, table_name: str, constraint_name: str) -> bool:
    return any(constraint["name"] == constraint_name for constraint in inspector.get_unique_constraints(table_name))


def _add_document_version_routing_columns(bind: sa.Connection, inspector: sa.Inspector) -> None:
    if not inspector.has_table("document_versions"):
        return

    columns = (
        ("routing_index_status", sa.String(length=32), False, "uploaded"),
        ("routing_index_path", sa.Text(), True, None),
        ("routing_index_error", sa.Text(), True, None),
        ("routing_index_version", sa.String(length=32), False, "v1"),
    )
    for name, column_type, nullable, server_default in columns:
        if _has_column(inspector, "document_versions", name):
            continue
        op.add_column(
            "document_versions",
            sa.Column(name, column_type, nullable=nullable, server_default=server_default),
        )
        inspector = sa.inspect(bind)

    index_name = op.f("ix_document_versions_routing_index_status")
    if not _has_index(inspector, "document_versions", index_name):
        op.create_index(index_name, "document_versions", ["routing_index_status"], unique=False)


def _create_document_routing_nodes(bind: sa.Connection, inspector: sa.Inspector) -> None:
    if not inspector.has_table("document_routing_nodes"):
        op.create_table(
            "document_routing_nodes",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("document_id", sa.String(length=64), nullable=False),
            sa.Column("version_id", sa.String(length=64), nullable=False),
            sa.Column("node_id", sa.String(length=255), nullable=False),
            sa.Column("parent_node_id", sa.String(length=255), nullable=True),
            sa.Column("depth", sa.Integer(), nullable=False),
            sa.Column("title", sa.Text(), nullable=True),
            sa.Column("breadcrumb", sa.Text(), nullable=True),
            sa.Column("page_start", sa.Integer(), nullable=True),
            sa.Column("page_end", sa.Integer(), nullable=True),
            sa.Column("route_summary", sa.Text(), nullable=True),
            sa.Column("contrastive_summary", sa.Text(), nullable=True),
            sa.Column("aliases_json", sa.Text(), nullable=True),
            sa.Column("keywords_json", sa.Text(), nullable=True),
            sa.Column("manual_profile_text", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
            sa.ForeignKeyConstraint(["version_id"], ["document_versions.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("version_id", "node_id", name="uq_document_routing_nodes_version_node"),
        )
        inspector = sa.inspect(bind)

    unique_name = "uq_document_routing_nodes_version_node"
    if not _has_unique_constraint(inspector, "document_routing_nodes", unique_name):
        # SQLite cannot add a unique constraint in place, so this batch path keeps the
        # new table portable if a partially created table ever reaches this migration.
        with op.batch_alter_table("document_routing_nodes", recreate="auto") as batch_op:
            batch_op.create_unique_constraint(unique_name, ["version_id", "node_id"])
        inspector = sa.inspect(bind)

    for index_name, columns in (
        (op.f("ix_document_routing_nodes_document_version"), ["document_id", "version_id"]),
        (op.f("ix_document_routing_nodes_version_parent_node"), ["version_id", "parent_node_id"]),
        (op.f("ix_document_routing_nodes_version_depth"), ["version_id", "depth"]),
    ):
        if not _has_index(inspector, "document_routing_nodes", index_name):
            op.create_index(index_name, "document_routing_nodes", columns, unique=False)
            inspector = sa.inspect(bind)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    _add_document_version_routing_columns(bind, inspector)
    inspector = sa.inspect(bind)
    _create_document_routing_nodes(bind, inspector)


def _drop_document_version_routing_columns(bind: sa.Connection, inspector: sa.Inspector) -> None:
    if not inspector.has_table("document_versions"):
        return

    index_name = op.f("ix_document_versions_routing_index_status")
    if _has_index(inspector, "document_versions", index_name):
        op.drop_index(index_name, table_name="document_versions")
        inspector = sa.inspect(bind)

    routing_columns = ("routing_index_status", "routing_index_path", "routing_index_error", "routing_index_version")
    if any(_has_column(inspector, "document_versions", column_name) for column_name in routing_columns):
        with op.batch_alter_table("document_versions", recreate="auto") as batch_op:
            for column_name in routing_columns:
                if _has_column(inspector, "document_versions", column_name):
                    batch_op.drop_column(column_name)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("document_routing_nodes"):
        for index_name in (
            op.f("ix_document_routing_nodes_version_depth"),
            op.f("ix_document_routing_nodes_version_parent_node"),
            op.f("ix_document_routing_nodes_document_version"),
        ):
            if _has_index(inspector, "document_routing_nodes", index_name):
                op.drop_index(index_name, table_name="document_routing_nodes")
                inspector = sa.inspect(bind)
        op.drop_table("document_routing_nodes")
        inspector = sa.inspect(bind)

    _drop_document_version_routing_columns(bind, inspector)
