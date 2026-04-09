"""phase3 chat queue worker

Revision ID: 20260407_0003
Revises: 20260407_0002
Create Date: 2026-04-07 20:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260407_0003"
down_revision = "20260407_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_runs", sa.Column("version_id", sa.String(length=64), nullable=True))
    op.add_column("chat_runs", sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("chat_runs", sa.Column("cancel_reason", sa.Text(), nullable=True))
    op.add_column("chat_runs", sa.Column("request_config_json", sa.Text(), nullable=False, server_default="{}"))
    op.add_column("chat_runs", sa.Column("conversation_config_json", sa.Text(), nullable=False, server_default="{}"))
    op.add_column("chat_runs", sa.Column("retrieval_config_json", sa.Text(), nullable=False, server_default="{}"))
    op.add_column("chat_runs", sa.Column("generation_config_json", sa.Text(), nullable=False, server_default="{}"))
    op.add_column("chat_runs", sa.Column("last_error", sa.Text(), nullable=True))
    op.add_column("chat_runs", sa.Column("worker_node_code", sa.String(length=255), nullable=True))
    op.add_column("chat_runs", sa.Column("claimed_at", sa.DateTime(), nullable=True))
    op.add_column("chat_runs", sa.Column("heartbeat_at", sa.DateTime(), nullable=True))
    op.create_foreign_key(
        op.f("fk_chat_runs_version_id_document_versions"),
        "chat_runs",
        "document_versions",
        ["version_id"],
        ["id"],
    )
    op.create_index(op.f("ix_chat_runs_version_id"), "chat_runs", ["version_id"], unique=False)
    op.create_index(op.f("ix_chat_runs_cancel_requested"), "chat_runs", ["cancel_requested"], unique=False)
    op.create_index(op.f("ix_chat_runs_worker_node_code"), "chat_runs", ["worker_node_code"], unique=False)

    op.alter_column("chat_runs", "cancel_requested", server_default=None)
    op.alter_column("chat_runs", "request_config_json", server_default=None)
    op.alter_column("chat_runs", "conversation_config_json", server_default=None)
    op.alter_column("chat_runs", "retrieval_config_json", server_default=None)
    op.alter_column("chat_runs", "generation_config_json", server_default=None)

    op.add_column("chat_sessions", sa.Column("active_run_id", sa.String(length=64), nullable=True))
    op.create_foreign_key(
        op.f("fk_chat_sessions_active_run_id_chat_runs"),
        "chat_sessions",
        "chat_runs",
        ["active_run_id"],
        ["id"],
    )
    op.create_index(op.f("ix_chat_sessions_active_run_id"), "chat_sessions", ["active_run_id"], unique=False)

    op.create_index(
        "uq_chat_messages_session_sequence_no",
        "chat_messages",
        ["session_id", "sequence_no"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_chat_messages_session_sequence_no", table_name="chat_messages")

    op.drop_index(op.f("ix_chat_sessions_active_run_id"), table_name="chat_sessions")
    op.drop_constraint(op.f("fk_chat_sessions_active_run_id_chat_runs"), "chat_sessions", type_="foreignkey")
    op.drop_column("chat_sessions", "active_run_id")

    op.drop_index(op.f("ix_chat_runs_worker_node_code"), table_name="chat_runs")
    op.drop_index(op.f("ix_chat_runs_cancel_requested"), table_name="chat_runs")
    op.drop_index(op.f("ix_chat_runs_version_id"), table_name="chat_runs")
    op.drop_constraint(op.f("fk_chat_runs_version_id_document_versions"), "chat_runs", type_="foreignkey")
    op.drop_column("chat_runs", "heartbeat_at")
    op.drop_column("chat_runs", "claimed_at")
    op.drop_column("chat_runs", "worker_node_code")
    op.drop_column("chat_runs", "last_error")
    op.drop_column("chat_runs", "generation_config_json")
    op.drop_column("chat_runs", "retrieval_config_json")
    op.drop_column("chat_runs", "conversation_config_json")
    op.drop_column("chat_runs", "request_config_json")
    op.drop_column("chat_runs", "cancel_reason")
    op.drop_column("chat_runs", "cancel_requested")
    op.drop_column("chat_runs", "version_id")
