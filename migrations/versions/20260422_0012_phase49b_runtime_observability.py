"""Phase 4.9B runtime observability and compliance worker support.

Revision ID: 20260422_0012
Revises: 20260421_0011
Create Date: 2026-04-22
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260422_0012"
down_revision = "20260421_0011"
branch_labels = None
depends_on = None


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def _has_index(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("compliance_runs"):
        plain_columns = [
            ("cancel_requested", sa.Boolean(), False, sa.false()),
            ("cancel_reason", sa.Text(), True, None),
            ("worker_node_code", sa.String(length=255), True, None),
            ("claimed_at", sa.DateTime(), True, None),
            ("heartbeat_at", sa.DateTime(), True, None),
        ]
        for name, column_type, nullable, server_default in plain_columns:
            if _has_column(inspector, "compliance_runs", name):
                continue
            op.add_column(
                "compliance_runs",
                sa.Column(name, column_type, nullable=nullable, server_default=server_default),
            )
            inspector = sa.inspect(bind)
        with op.batch_alter_table("compliance_runs", recreate="auto") as batch_op:
            if _has_column(inspector, "compliance_runs", "cancel_requested"):
                batch_op.alter_column("cancel_requested", existing_type=sa.Boolean(), server_default=None)
        inspector = sa.inspect(bind)
        for index_name, columns in (
            (op.f("ix_compliance_runs_cancel_requested"), ["cancel_requested"]),
            (op.f("ix_compliance_runs_worker_node_code"), ["worker_node_code"]),
        ):
            if not _has_index(inspector, "compliance_runs", index_name):
                op.create_index(index_name, "compliance_runs", columns, unique=False)
                inspector = sa.inspect(bind)

    if not inspector.has_table("run_observation_events"):
        op.create_table(
            "run_observation_events",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("run_kind", sa.String(length=32), nullable=False),
            sa.Column("run_id", sa.String(length=64), nullable=False),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("workspace_id", sa.String(length=64), nullable=True),
            sa.Column("sequence_no", sa.Integer(), nullable=False),
            sa.Column("event_type", sa.String(length=64), nullable=False),
            sa.Column("step", sa.String(length=64), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=True),
            sa.Column("payload_json", sa.Text().with_variant(mysql.LONGTEXT(), "mysql"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_run_observation_events_run_kind"), "run_observation_events", ["run_kind"], unique=False)
        op.create_index(op.f("ix_run_observation_events_run_id"), "run_observation_events", ["run_id"], unique=False)
        op.create_index(op.f("ix_run_observation_events_tenant_id"), "run_observation_events", ["tenant_id"], unique=False)
        op.create_index(op.f("ix_run_observation_events_workspace_id"), "run_observation_events", ["workspace_id"], unique=False)
        op.create_index(op.f("ix_run_observation_events_event_type"), "run_observation_events", ["event_type"], unique=False)
        op.create_index(op.f("ix_run_observation_events_step"), "run_observation_events", ["step"], unique=False)
        op.create_index(op.f("ix_run_observation_events_status"), "run_observation_events", ["status"], unique=False)
        op.create_index(op.f("ix_run_observation_events_created_at"), "run_observation_events", ["created_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("run_observation_events"):
        for index_name in (
            op.f("ix_run_observation_events_created_at"),
            op.f("ix_run_observation_events_status"),
            op.f("ix_run_observation_events_step"),
            op.f("ix_run_observation_events_event_type"),
            op.f("ix_run_observation_events_workspace_id"),
            op.f("ix_run_observation_events_tenant_id"),
            op.f("ix_run_observation_events_run_id"),
            op.f("ix_run_observation_events_run_kind"),
        ):
            if _has_index(inspector, "run_observation_events", index_name):
                op.drop_index(index_name, table_name="run_observation_events")
                inspector = sa.inspect(bind)
        op.drop_table("run_observation_events")
        inspector = sa.inspect(bind)

    if inspector.has_table("compliance_runs"):
        for index_name in (
            op.f("ix_compliance_runs_worker_node_code"),
            op.f("ix_compliance_runs_cancel_requested"),
        ):
            if _has_index(inspector, "compliance_runs", index_name):
                op.drop_index(index_name, table_name="compliance_runs")
                inspector = sa.inspect(bind)
        with op.batch_alter_table("compliance_runs", recreate="auto") as batch_op:
            for column_name in ("heartbeat_at", "claimed_at", "worker_node_code", "cancel_reason", "cancel_requested"):
                if _has_column(inspector, "compliance_runs", column_name):
                    batch_op.drop_column(column_name)
