"""phase4.6 user must_change_password

Revision ID: 20260416_0009
Revises: 20260415_0008
Create Date: 2026-04-16 15:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260416_0009"
down_revision = "20260415_0008"
branch_labels = None
depends_on = None


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return inspector.has_table(table_name)


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return any(c["name"] == column_name for c in inspector.get_columns(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "users"):
        return

    if _has_column(inspector, "users", "must_change_password"):
        return

    dialect = bind.dialect.name
    if dialect == "sqlite":
        with op.batch_alter_table("users") as batch_op:
            batch_op.add_column(
                sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.text("0"))
            )
    else:
        op.add_column(
            "users",
            sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "users"):
        return

    if not _has_column(inspector, "users", "must_change_password"):
        return

    dialect = bind.dialect.name
    if dialect == "sqlite":
        with op.batch_alter_table("users") as batch_op:
            batch_op.drop_column("must_change_password")
    else:
        op.drop_column("users", "must_change_password")
