"""Use LONGTEXT for runtime observation payloads on MySQL.

Revision ID: 20260427_0014
Revises: 20260423_0013
Create Date: 2026-04-27
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260427_0014"
down_revision = "20260423_0013"
branch_labels = None
depends_on = None


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("run_observation_events"):
        return
    if not _has_column(inspector, "run_observation_events", "payload_json"):
        return
    with op.batch_alter_table("run_observation_events", recreate="auto") as batch_op:
        batch_op.alter_column(
            "payload_json",
            existing_type=sa.Text(),
            type_=sa.Text().with_variant(mysql.LONGTEXT(), "mysql"),
            existing_nullable=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("run_observation_events"):
        return
    if not _has_column(inspector, "run_observation_events", "payload_json"):
        return
    with op.batch_alter_table("run_observation_events", recreate="auto") as batch_op:
        batch_op.alter_column(
            "payload_json",
            existing_type=sa.Text().with_variant(mysql.LONGTEXT(), "mysql"),
            type_=sa.Text(),
            existing_nullable=False,
        )
