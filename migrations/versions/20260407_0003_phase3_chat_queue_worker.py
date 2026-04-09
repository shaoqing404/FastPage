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


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def _has_index(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def _has_fk(inspector: sa.Inspector, table_name: str, fk_name: str) -> bool:
    return any(fk["name"] == fk_name for fk in inspector.get_foreign_keys(table_name))


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    conn = op.get_bind()

    plain_columns = [
        ("version_id", sa.String(length=64), True, None),
        ("cancel_requested", sa.Boolean(), False, sa.false()),
        ("cancel_reason", sa.Text(), True, None),
        ("last_error", sa.Text(), True, None),
        ("worker_node_code", sa.String(length=255), True, None),
        ("claimed_at", sa.DateTime(), True, None),
        ("heartbeat_at", sa.DateTime(), True, None),
    ]
    for name, column_type, nullable, server_default in plain_columns:
        if _has_column(inspector, "chat_runs", name):
            continue
        op.add_column("chat_runs", sa.Column(name, column_type, nullable=nullable, server_default=server_default))
        inspector = sa.inspect(op.get_bind())

    json_text_columns = [
        "request_config_json",
        "conversation_config_json",
        "retrieval_config_json",
        "generation_config_json",
    ]
    for name in json_text_columns:
        if not _has_column(inspector, "chat_runs", name):
            op.add_column("chat_runs", sa.Column(name, sa.Text(), nullable=True))
            inspector = sa.inspect(op.get_bind())
        conn.execute(sa.text(f"UPDATE chat_runs SET {name}='{{}}' WHERE {name} IS NULL"))
        op.alter_column("chat_runs", name, existing_type=sa.Text(), nullable=False)

    fk_name = op.f("fk_chat_runs_version_id_document_versions")
    if not _has_fk(inspector, "chat_runs", fk_name):
        op.create_foreign_key(fk_name, "chat_runs", "document_versions", ["version_id"], ["id"])
        inspector = sa.inspect(op.get_bind())

    for index_name, columns in (
        (op.f("ix_chat_runs_version_id"), ["version_id"]),
        (op.f("ix_chat_runs_cancel_requested"), ["cancel_requested"]),
        (op.f("ix_chat_runs_worker_node_code"), ["worker_node_code"]),
    ):
        if not _has_index(inspector, "chat_runs", index_name):
            op.create_index(index_name, "chat_runs", columns, unique=False)
            inspector = sa.inspect(op.get_bind())

    if _has_column(inspector, "chat_runs", "cancel_requested"):
        op.alter_column("chat_runs", "cancel_requested", server_default=None)

    if not _has_column(inspector, "chat_sessions", "active_run_id"):
        op.add_column("chat_sessions", sa.Column("active_run_id", sa.String(length=64), nullable=True))
        inspector = sa.inspect(op.get_bind())

    session_fk_name = op.f("fk_chat_sessions_active_run_id_chat_runs")
    if not _has_fk(inspector, "chat_sessions", session_fk_name):
        op.create_foreign_key(session_fk_name, "chat_sessions", "chat_runs", ["active_run_id"], ["id"])
        inspector = sa.inspect(op.get_bind())

    session_index_name = op.f("ix_chat_sessions_active_run_id")
    if not _has_index(inspector, "chat_sessions", session_index_name):
        op.create_index(session_index_name, "chat_sessions", ["active_run_id"], unique=False)
        inspector = sa.inspect(op.get_bind())

    if not _has_index(inspector, "chat_messages", "uq_chat_messages_session_sequence_no"):
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
