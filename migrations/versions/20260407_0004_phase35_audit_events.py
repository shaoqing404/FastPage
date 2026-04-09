"""phase3.5 audit events

Revision ID: 20260407_0004
Revises: 20260407_0003
Create Date: 2026-04-07 21:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260407_0004"
down_revision = "20260407_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=True),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("result", sa.String(length=32), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("meta_json", sa.Text(), nullable=True),
    )
    op.create_index("ix_audit_events_timestamp", "audit_events", ["timestamp"])
    op.create_index("ix_audit_events_tenant_id", "audit_events", ["tenant_id"])
    op.create_index("ix_audit_events_tenant_action", "audit_events", ["tenant_id", "action"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_tenant_action", table_name="audit_events")
    op.drop_index("ix_audit_events_tenant_id", table_name="audit_events")
    op.drop_index("ix_audit_events_timestamp", table_name="audit_events")
    op.drop_table("audit_events")
