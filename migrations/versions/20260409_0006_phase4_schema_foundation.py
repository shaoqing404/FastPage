"""phase4 schema foundation

Revision ID: 20260409_0006
Revises: 20260407_0005
Create Date: 2026-04-09 10:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260409_0006"
down_revision = "20260407_0005"
branch_labels = None
depends_on = None


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return inspector.has_table(table_name)


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def _has_index(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def _has_fk(inspector: sa.Inspector, table_name: str, fk_name: str) -> bool:
    return any(fk["name"] == fk_name for fk in inspector.get_foreign_keys(table_name))


def _upgrade_workspace_archive_columns(inspector: sa.Inspector) -> None:
    archived_by_fk = op.f("fk_workspaces_archived_by_users")
    needs_batch = (
        not _has_column(inspector, "workspaces", "archived_at")
        or not _has_column(inspector, "workspaces", "archived_by")
        or not _has_fk(inspector, "workspaces", archived_by_fk)
    )
    if not needs_batch:
        return

    # Use batch mode so SQLite does not rely on unsupported ALTER CONSTRAINT paths.
    with op.batch_alter_table("workspaces", recreate="auto") as batch_op:
        if not _has_column(inspector, "workspaces", "archived_at"):
            batch_op.add_column(sa.Column("archived_at", sa.DateTime(), nullable=True))
        if not _has_column(inspector, "workspaces", "archived_by"):
            batch_op.add_column(sa.Column("archived_by", sa.String(length=64), nullable=True))
        if not _has_fk(inspector, "workspaces", archived_by_fk):
            batch_op.create_foreign_key(archived_by_fk, "users", ["archived_by"], ["id"])


def _downgrade_workspace_archive_columns(inspector: sa.Inspector) -> None:
    archived_by_fk = op.f("fk_workspaces_archived_by_users")
    if _has_index(inspector, "workspaces", op.f("ix_workspaces_archived_by")):
        op.drop_index(op.f("ix_workspaces_archived_by"), table_name="workspaces")
        inspector = sa.inspect(op.get_bind())

    needs_batch = (
        _has_column(inspector, "workspaces", "archived_at")
        or _has_column(inspector, "workspaces", "archived_by")
        or _has_fk(inspector, "workspaces", archived_by_fk)
    )
    if not needs_batch:
        return

    with op.batch_alter_table("workspaces", recreate="auto") as batch_op:
        if _has_fk(inspector, "workspaces", archived_by_fk):
            batch_op.drop_constraint(archived_by_fk, type_="foreignkey")
        if _has_column(inspector, "workspaces", "archived_by"):
            batch_op.drop_column("archived_by")
        if _has_column(inspector, "workspaces", "archived_at"):
            batch_op.drop_column("archived_at")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_column(inspector, "users", "email"):
        op.add_column("users", sa.Column("email", sa.String(length=255), nullable=True))
        inspector = sa.inspect(bind)
    if not _has_index(inspector, "users", op.f("ix_users_email")):
        op.create_index(op.f("ix_users_email"), "users", ["email"], unique=False)
        inspector = sa.inspect(bind)

    if not _has_column(inspector, "users", "can_create_workspace"):
        op.add_column(
            "users",
            sa.Column("can_create_workspace", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        inspector = sa.inspect(bind)

    if not _has_column(inspector, "users", "is_platform_admin"):
        op.add_column(
            "users",
            sa.Column("is_platform_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        inspector = sa.inspect(bind)

    if not _has_column(inspector, "users", "updated_at"):
        op.add_column(
            "users",
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        bind.execute(sa.text("UPDATE users SET updated_at = created_at WHERE created_at IS NOT NULL"))
        inspector = sa.inspect(bind)

    _upgrade_workspace_archive_columns(inspector)
    inspector = sa.inspect(bind)

    if _has_column(inspector, "workspaces", "archived_by") and not _has_index(
        inspector, "workspaces", op.f("ix_workspaces_archived_by")
    ):
        op.create_index(op.f("ix_workspaces_archived_by"), "workspaces", ["archived_by"], unique=False)
        inspector = sa.inspect(bind)

    if not _has_column(inspector, "knowledge_bases", "visibility"):
        op.add_column(
            "knowledge_bases",
            sa.Column("visibility", sa.String(length=32), nullable=False, server_default="private"),
        )
        inspector = sa.inspect(bind)

    if not _has_column(inspector, "chat_skills", "visibility"):
        op.add_column(
            "chat_skills",
            sa.Column("visibility", sa.String(length=32), nullable=False, server_default="private"),
        )
        inspector = sa.inspect(bind)

    if not _has_table(inspector, "workspace_memberships"):
        op.create_table(
            "workspace_memberships",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("workspace_id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.String(length=64), nullable=False),
            sa.Column("role", sa.String(length=32), nullable=False, server_default="member"),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
            sa.Column("permissions_override_json", sa.Text(), nullable=False),
            sa.Column("created_by", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_memberships_workspace_user"),
        )
        inspector = sa.inspect(bind)

    for index_name, columns in (
        (op.f("ix_workspace_memberships_workspace_id"), ["workspace_id"]),
        (op.f("ix_workspace_memberships_user_id"), ["user_id"]),
        (op.f("ix_workspace_memberships_created_by"), ["created_by"]),
    ):
        if not _has_index(inspector, "workspace_memberships", index_name):
            op.create_index(index_name, "workspace_memberships", columns, unique=False)
            inspector = sa.inspect(bind)

    if not _has_table(inspector, "workspace_invites"):
        op.create_table(
            "workspace_invites",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("workspace_id", sa.String(length=64), nullable=False),
            sa.Column("email", sa.String(length=255), nullable=False),
            sa.Column("role", sa.String(length=32), nullable=False, server_default="member"),
            sa.Column("permissions_override_json", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("invited_by", sa.String(length=64), nullable=False),
            sa.Column("accepted_user_id", sa.String(length=64), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("accepted_at", sa.DateTime(), nullable=True),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["accepted_user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["invited_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        inspector = sa.inspect(bind)

    for index_name, columns in (
        (op.f("ix_workspace_invites_workspace_id"), ["workspace_id"]),
        (op.f("ix_workspace_invites_invited_by"), ["invited_by"]),
        (op.f("ix_workspace_invites_accepted_user_id"), ["accepted_user_id"]),
        ("ix_workspace_invites_workspace_email_status", ["workspace_id", "email", "status"]),
    ):
        if not _has_index(inspector, "workspace_invites", index_name):
            op.create_index(index_name, "workspace_invites", columns, unique=False)
            inspector = sa.inspect(bind)

    # TODO(phase4): tighten users.email to a globally unique, case-insensitive constraint
    # after staged backfill/remediation lands. This batch intentionally keeps email nullable
    # and indexed only so current bootstrap/auth flows remain compatible across SQLite/Postgres.
    #
    # TODO(phase4): enforce one active founder per workspace with a partial unique index
    # on workspace_memberships once the supported database path is finalized.
    #
    # TODO(phase4): switch invite lookup to normalized/case-insensitive enforcement
    # (for example via normalized storage or a functional/partial index) in a follow-up batch.


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "workspace_invites"):
        op.drop_table("workspace_invites")
        inspector = sa.inspect(bind)

    if _has_table(inspector, "workspace_memberships"):
        op.drop_table("workspace_memberships")
        inspector = sa.inspect(bind)

    op.drop_column("chat_skills", "visibility")
    op.drop_column("knowledge_bases", "visibility")

    _downgrade_workspace_archive_columns(inspector)

    op.drop_column("users", "updated_at")
    op.drop_column("users", "is_platform_admin")
    op.drop_column("users", "can_create_workspace")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_column("users", "email")
