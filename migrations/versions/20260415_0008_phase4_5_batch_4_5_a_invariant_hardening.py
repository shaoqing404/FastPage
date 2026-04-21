"""phase4.5 batch 4.5-a invariant hardening

Revision ID: 20260415_0008
Revises: 20260410_0007
Create Date: 2026-04-15 11:30:00
"""

from __future__ import annotations

from collections import defaultdict

from alembic import op
import sqlalchemy as sa


revision = "20260415_0008"
down_revision = "20260410_0007"
branch_labels = None
depends_on = None


USERS_EMAIL_INDEX = "ix_users_email"
ACTIVE_FOUNDER_INDEX = "uq_workspace_memberships_active_founder_workspace_id"
PENDING_INVITE_INDEX = "uq_workspace_invites_workspace_pending_normalized_email"


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return inspector.has_table(table_name)


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def _get_index(inspector: sa.Inspector, table_name: str, index_name: str) -> dict[str, object] | None:
    return next((index for index in inspector.get_indexes(table_name) if index["name"] == index_name), None)


def _normalize_email(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None


def _load_table(bind: sa.Connection, table_name: str) -> sa.Table:
    return sa.Table(table_name, sa.MetaData(), autoload_with=bind)


def _format_conflicts(conflicts: list[tuple[str, list[str]]]) -> str:
    samples = [f"{subject} -> {', '.join(item_ids[:3])}" for subject, item_ids in conflicts[:5]]
    return "; ".join(samples)


def _normalize_user_emails(bind: sa.Connection) -> None:
    users = _load_table(bind, "users")
    rows = bind.execute(
        sa.select(users.c.id, users.c.email).where(users.c.email.is_not(None)).order_by(users.c.id.asc())
    ).mappings()

    duplicates: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        normalized = _normalize_email(row["email"])
        if normalized != row["email"]:
            bind.execute(users.update().where(users.c.id == row["id"]).values(email=normalized))
        if normalized is not None:
            duplicates[normalized].append(row["id"])

    conflicts = [(email, user_ids) for email, user_ids in duplicates.items() if len(user_ids) > 1]
    if conflicts:
        raise RuntimeError(
            "Cannot enforce unique normalized user emails; remediate duplicates before upgrading. "
            f"Examples: {_format_conflicts(conflicts)}"
        )


def _normalize_workspace_invite_emails(bind: sa.Connection) -> None:
    invites = _load_table(bind, "workspace_invites")
    rows = bind.execute(
        sa.select(
            invites.c.id,
            invites.c.workspace_id,
            invites.c.email,
            invites.c.status,
        ).order_by(invites.c.workspace_id.asc(), invites.c.id.asc())
    ).mappings()

    blanks: list[tuple[str, list[str]]] = []
    duplicates: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in rows:
        normalized = _normalize_email(row["email"])
        if normalized is None:
            blanks.append((row["workspace_id"], [row["id"]]))
            continue
        if normalized != row["email"]:
            bind.execute(invites.update().where(invites.c.id == row["id"]).values(email=normalized))
        if row["status"] == "pending":
            duplicates[(row["workspace_id"], normalized)].append(row["id"])

    if blanks:
        raise RuntimeError(
            "Cannot enforce normalized workspace invite emails; found blank invite email rows. "
            f"Examples: {_format_conflicts(blanks)}"
        )

    conflicts = [
        (f"{workspace_id}:{email}", invite_ids)
        for (workspace_id, email), invite_ids in duplicates.items()
        if len(invite_ids) > 1
    ]
    if conflicts:
        raise RuntimeError(
            "Cannot enforce one pending invite per normalized email per workspace; remediate duplicates before upgrading. "
            f"Examples: {_format_conflicts(conflicts)}"
        )


def _assert_single_active_founder_per_workspace(bind: sa.Connection) -> None:
    memberships = _load_table(bind, "workspace_memberships")
    rows = bind.execute(
        sa.select(
            memberships.c.workspace_id,
            memberships.c.id,
        )
        .where(
            memberships.c.role == "founder",
            memberships.c.status == "active",
        )
        .order_by(memberships.c.workspace_id.asc(), memberships.c.id.asc())
    ).mappings()

    founders_by_workspace: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        founders_by_workspace[row["workspace_id"]].append(row["id"])

    conflicts = [
        (workspace_id, membership_ids)
        for workspace_id, membership_ids in founders_by_workspace.items()
        if len(membership_ids) > 1
    ]
    if conflicts:
        raise RuntimeError(
            "Cannot enforce one active founder per workspace; remediate duplicate founder memberships before upgrading. "
            f"Examples: {_format_conflicts(conflicts)}"
        )


def _add_active_founder_key_column(inspector: sa.Inspector) -> None:
    if _has_column(inspector, "workspace_memberships", "active_founder_workspace_id"):
        return

    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("workspace_memberships", recreate="always") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "active_founder_workspace_id",
                    sa.String(length=64),
                    sa.Computed(
                        "CASE WHEN role = 'founder' AND status = 'active' THEN workspace_id ELSE NULL END",
                        persisted=True,
                    ),
                    nullable=True,
                )
            )
    else:
        op.add_column(
            "workspace_memberships",
            sa.Column(
                "active_founder_workspace_id",
                sa.String(length=64),
                sa.Computed(
                    "CASE WHEN role = 'founder' AND status = 'active' THEN workspace_id ELSE NULL END",
                    persisted=True,
                ),
                nullable=True,
            )
        )


def _add_pending_normalized_email_column(inspector: sa.Inspector) -> None:
    if _has_column(inspector, "workspace_invites", "pending_normalized_email"):
        return

    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("workspace_invites", recreate="always") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "pending_normalized_email",
                    sa.String(length=255),
                    sa.Computed(
                        "CASE WHEN status = 'pending' THEN lower(trim(email)) ELSE NULL END",
                        persisted=True,
                    ),
                    nullable=True,
                )
            )
    else:
        op.add_column(
            "workspace_invites",
            sa.Column(
                "pending_normalized_email",
                sa.String(length=255),
                sa.Computed(
                    "CASE WHEN status = 'pending' THEN lower(trim(email)) ELSE NULL END",
                    persisted=True,
                ),
                nullable=True,
            )
        )


def _upgrade_users_email_index(inspector: sa.Inspector) -> None:
    existing_index = _get_index(inspector, "users", USERS_EMAIL_INDEX)
    if existing_index is not None and not existing_index.get("unique", False):
        op.drop_index(USERS_EMAIL_INDEX, table_name="users")
        inspector = sa.inspect(op.get_bind())
        existing_index = _get_index(inspector, "users", USERS_EMAIL_INDEX)

    if existing_index is None:
        op.create_index(USERS_EMAIL_INDEX, "users", ["email"], unique=True)


def _downgrade_users_email_index(inspector: sa.Inspector) -> None:
    existing_index = _get_index(inspector, "users", USERS_EMAIL_INDEX)
    if existing_index is not None and existing_index.get("unique", False):
        op.drop_index(USERS_EMAIL_INDEX, table_name="users")
        inspector = sa.inspect(op.get_bind())
        existing_index = _get_index(inspector, "users", USERS_EMAIL_INDEX)

    if existing_index is None:
        op.create_index(USERS_EMAIL_INDEX, "users", ["email"], unique=False)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "users"):
        return

    _normalize_user_emails(bind)
    _normalize_workspace_invite_emails(bind)
    _assert_single_active_founder_per_workspace(bind)

    inspector = sa.inspect(bind)
    _upgrade_users_email_index(inspector)

    inspector = sa.inspect(bind)
    _add_active_founder_key_column(inspector)
    inspector = sa.inspect(bind)
    if _get_index(inspector, "workspace_memberships", ACTIVE_FOUNDER_INDEX) is None:
        op.create_index(
            ACTIVE_FOUNDER_INDEX,
            "workspace_memberships",
            ["active_founder_workspace_id"],
            unique=True,
        )

    inspector = sa.inspect(bind)
    _add_pending_normalized_email_column(inspector)
    inspector = sa.inspect(bind)
    if _get_index(inspector, "workspace_invites", PENDING_INVITE_INDEX) is None:
        op.create_index(
            PENDING_INVITE_INDEX,
            "workspace_invites",
            ["workspace_id", "pending_normalized_email"],
            unique=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "workspace_invites") and _get_index(inspector, "workspace_invites", PENDING_INVITE_INDEX) is not None:
        op.drop_index(PENDING_INVITE_INDEX, table_name="workspace_invites")
        inspector = sa.inspect(bind)
    if _has_table(inspector, "workspace_invites") and _has_column(inspector, "workspace_invites", "pending_normalized_email"):
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("workspace_invites", recreate="always") as batch_op:
                batch_op.drop_column("pending_normalized_email")
        else:
            op.drop_column("workspace_invites", "pending_normalized_email")
        inspector = sa.inspect(bind)

    if _has_table(inspector, "workspace_memberships") and _get_index(inspector, "workspace_memberships", ACTIVE_FOUNDER_INDEX) is not None:
        op.drop_index(ACTIVE_FOUNDER_INDEX, table_name="workspace_memberships")
        inspector = sa.inspect(bind)
    if _has_table(inspector, "workspace_memberships") and _has_column(
        inspector, "workspace_memberships", "active_founder_workspace_id"
    ):
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("workspace_memberships", recreate="always") as batch_op:
                batch_op.drop_column("active_founder_workspace_id")
        else:
            op.drop_column("workspace_memberships", "active_founder_workspace_id")
        inspector = sa.inspect(bind)

    if _has_table(inspector, "users"):
        _downgrade_users_email_index(inspector)
