"""phase4 backfill membership visibility

Revision ID: 20260410_0007
Revises: 20260409_0006
Create Date: 2026-04-10 11:30:00
"""

from __future__ import annotations

from datetime import datetime
import json
import uuid

from alembic import op
import sqlalchemy as sa


revision = "20260410_0007"
down_revision = "20260409_0006"
branch_labels = None
depends_on = None


REVIEW_CATEGORY_WORKSPACE_FOUNDER_GAP = "workspace_founder_gap"
REVIEW_SUBJECT_TYPE_WORKSPACE = "workspace"
WORKSPACE_MEMBERSHIP_STATUS_ACTIVE = "active"
WORKSPACE_VISIBILITY_PRIVATE = "private"
TENANT_MEMBERSHIP_STATUS_ACTIVE = "active"
REVIEW_DETAILS_JSON_EMPTY = "{}"


def _utcnow() -> datetime:
    return datetime.utcnow()


def _membership_id() -> str:
    return f"wm_{uuid.uuid4().hex}"


def _review_item_id() -> str:
    return f"mri_{uuid.uuid4().hex}"


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return inspector.has_table(table_name)


def _has_index(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def _create_review_table(inspector: sa.Inspector) -> None:
    if not _has_table(inspector, "migration_review_items"):
        op.create_table(
            "migration_review_items",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("category", sa.String(length=64), nullable=False),
            sa.Column("subject_type", sa.String(length=64), nullable=False),
            sa.Column("subject_id", sa.String(length=64), nullable=False),
            sa.Column("details_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "category",
                "subject_type",
                "subject_id",
                name="uq_migration_review_items_category_subject",
            ),
        )

    inspector = sa.inspect(op.get_bind())
    for index_name, columns in (
        ("ix_migration_review_items_category", ["category"]),
        ("ix_migration_review_items_subject", ["subject_type", "subject_id"]),
    ):
        if not _has_index(inspector, "migration_review_items", index_name):
            op.create_index(index_name, "migration_review_items", columns, unique=False)
            inspector = sa.inspect(op.get_bind())


def _create_safe_indexes(inspector: sa.Inspector) -> None:
    if not _has_index(
        inspector,
        "workspace_memberships",
        "ix_workspace_memberships_workspace_status_role",
    ):
        op.create_index(
            "ix_workspace_memberships_workspace_status_role",
            "workspace_memberships",
            ["workspace_id", "status", "role"],
            unique=False,
        )


def _load_table(bind: sa.Connection, table_name: str) -> sa.Table:
    metadata = sa.MetaData()
    return sa.Table(table_name, metadata, autoload_with=bind)


def _load_existing_membership_pairs(bind: sa.Connection, workspace_memberships: sa.Table) -> set[tuple[str, str]]:
    return {
        (row["workspace_id"], row["user_id"])
        for row in bind.execute(
            sa.select(workspace_memberships.c.workspace_id, workspace_memberships.c.user_id)
        ).mappings()
    }


def _load_existing_review_keys(bind: sa.Connection, migration_review_items: sa.Table) -> set[tuple[str, str, str]]:
    return {
        (row["category"], row["subject_type"], row["subject_id"])
        for row in bind.execute(
            sa.select(
                migration_review_items.c.category,
                migration_review_items.c.subject_type,
                migration_review_items.c.subject_id,
            )
        ).mappings()
    }


def _choose_default_workspace_founder(
    workspace: sa.RowMapping,
    active_memberships: list[sa.RowMapping],
) -> tuple[sa.RowMapping | None, str | None, bool]:
    owners = [row for row in active_memberships if row["role"] == "owner"]
    admins = [row for row in active_memberships if row["role"] == "admin"]
    created_by = workspace["created_by"]

    if owners:
        created_by_owner = next((row for row in owners if row["user_id"] == created_by), None)
        if created_by_owner is not None:
            return created_by_owner, "created_by_owner", False
        return owners[0], "oldest_owner", False

    if admins:
        return admins[0], "oldest_admin", True

    return None, None, True


def _membership_audit_actor(
    founder_user_id: str | None,
    workspace_created_by: str | None,
    known_user_ids: set[str],
) -> str | None:
    if founder_user_id:
        return founder_user_id
    if workspace_created_by and workspace_created_by in known_user_ids:
        return workspace_created_by
    return None


def _insert_workspace_membership(
    bind: sa.Connection,
    workspace_memberships: sa.Table,
    existing_pairs: set[tuple[str, str]],
    *,
    workspace_id: str,
    user_id: str,
    role: str,
    created_by: str | None,
    created_at: datetime,
    updated_at: datetime,
) -> None:
    pair = (workspace_id, user_id)
    if pair in existing_pairs:
        return

    bind.execute(
        workspace_memberships.insert().values(
            id=_membership_id(),
            workspace_id=workspace_id,
            user_id=user_id,
            role=role,
            status=WORKSPACE_MEMBERSHIP_STATUS_ACTIVE,
            permissions_override_json=REVIEW_DETAILS_JSON_EMPTY,
            created_by=created_by,
            created_at=created_at,
            updated_at=updated_at,
        )
    )
    existing_pairs.add(pair)


def _insert_review_item(
    bind: sa.Connection,
    migration_review_items: sa.Table,
    existing_keys: set[tuple[str, str, str]],
    *,
    category: str,
    subject_type: str,
    subject_id: str,
    details: dict[str, object],
) -> None:
    key = (category, subject_type, subject_id)
    if key in existing_keys:
        return

    bind.execute(
        migration_review_items.insert().values(
            id=_review_item_id(),
            category=category,
            subject_type=subject_type,
            subject_id=subject_id,
            details_json=json.dumps(details, ensure_ascii=False, sort_keys=True),
            created_at=_utcnow(),
        )
    )
    existing_keys.add(key)


def _backfill_default_workspace_memberships(
    bind: sa.Connection,
    workspaces: sa.Table,
    tenant_memberships: sa.Table,
    workspace_memberships: sa.Table,
    migration_review_items: sa.Table,
    existing_pairs: set[tuple[str, str]],
    existing_review_keys: set[tuple[str, str, str]],
    known_user_ids: set[str],
) -> None:
    default_workspaces = bind.execute(
        sa.select(
            workspaces.c.id,
            workspaces.c.tenant_id,
            workspaces.c.created_by,
            workspaces.c.created_at,
            workspaces.c.updated_at,
        )
        .where(workspaces.c.is_default.is_(True))
        .order_by(workspaces.c.created_at.asc(), workspaces.c.id.asc())
    ).mappings().all()

    active_membership_rows = bind.execute(
        sa.select(
            tenant_memberships.c.tenant_id,
            tenant_memberships.c.user_id,
            tenant_memberships.c.role,
            tenant_memberships.c.created_at,
            tenant_memberships.c.updated_at,
        )
        .where(tenant_memberships.c.status == TENANT_MEMBERSHIP_STATUS_ACTIVE)
        .order_by(
            tenant_memberships.c.tenant_id.asc(),
            tenant_memberships.c.created_at.asc(),
            tenant_memberships.c.id.asc(),
        )
    ).mappings().all()

    memberships_by_tenant: dict[str, list[sa.RowMapping]] = {}
    for row in active_membership_rows:
        memberships_by_tenant.setdefault(row["tenant_id"], []).append(row)

    role_map = {
        "admin": "admin",
        "member": "member",
    }

    for workspace in default_workspaces:
        workspace_members = memberships_by_tenant.get(workspace["tenant_id"], [])
        founder_row, founder_source, needs_review = _choose_default_workspace_founder(workspace, workspace_members)
        founder_user_id = founder_row["user_id"] if founder_row is not None else None
        created_by = _membership_audit_actor(founder_user_id, workspace["created_by"], known_user_ids)

        for row in workspace_members:
            role = role_map.get(row["role"], "admin")
            if founder_user_id and row["user_id"] == founder_user_id:
                role = "founder"
            elif row["role"] == "owner":
                role = "admin"

            _insert_workspace_membership(
                bind,
                workspace_memberships,
                existing_pairs,
                workspace_id=workspace["id"],
                user_id=row["user_id"],
                role=role,
                created_by=created_by,
                created_at=row["created_at"] or workspace["created_at"] or _utcnow(),
                updated_at=row["updated_at"] or row["created_at"] or workspace["updated_at"] or _utcnow(),
            )

        if needs_review:
            owner_count = sum(1 for row in workspace_members if row["role"] == "owner")
            admin_count = sum(1 for row in workspace_members if row["role"] == "admin")
            _insert_review_item(
                bind,
                migration_review_items,
                existing_review_keys,
                category=REVIEW_CATEGORY_WORKSPACE_FOUNDER_GAP,
                subject_type=REVIEW_SUBJECT_TYPE_WORKSPACE,
                subject_id=workspace["id"],
                details={
                    "workspace_id": workspace["id"],
                    "tenant_id": workspace["tenant_id"],
                    "is_default": True,
                    "founder_source": founder_source,
                    "selected_user_id": founder_user_id,
                    "reason": (
                        "default workspace founder fell back to earliest active admin"
                        if founder_user_id
                        else "default workspace founder unresolved because no active tenant owner/admin exists"
                    ),
                    "active_owner_count": owner_count,
                    "active_admin_count": admin_count,
                },
            )


def _load_non_default_workspace_member_candidates(
    bind: sa.Connection,
    *,
    documents: sa.Table,
    chat_skills: sa.Table,
    chat_sessions: sa.Table,
    chat_runs: sa.Table,
    knowledge_bases: sa.Table,
    api_keys: sa.Table,
) -> dict[str, dict[str, datetime | None]]:
    signal_queries = (
        sa.select(
            documents.c.workspace_id.label("workspace_id"),
            documents.c.owner_user_id.label("user_id"),
            documents.c.created_at.label("created_at"),
        ).where(documents.c.workspace_id.is_not(None)),
        sa.select(
            chat_skills.c.workspace_id.label("workspace_id"),
            chat_skills.c.owner_user_id.label("user_id"),
            chat_skills.c.created_at.label("created_at"),
        ).where(chat_skills.c.workspace_id.is_not(None)),
        sa.select(
            chat_sessions.c.workspace_id.label("workspace_id"),
            chat_sessions.c.user_id.label("user_id"),
            chat_sessions.c.created_at.label("created_at"),
        ).where(chat_sessions.c.workspace_id.is_not(None)),
        sa.select(
            chat_runs.c.workspace_id.label("workspace_id"),
            chat_runs.c.user_id.label("user_id"),
            chat_runs.c.created_at.label("created_at"),
        ).where(chat_runs.c.workspace_id.is_not(None)),
        sa.select(
            knowledge_bases.c.workspace_id.label("workspace_id"),
            knowledge_bases.c.created_by.label("user_id"),
            knowledge_bases.c.created_at.label("created_at"),
        ),
        sa.select(
            api_keys.c.workspace_id.label("workspace_id"),
            api_keys.c.created_by.label("user_id"),
            api_keys.c.created_at.label("created_at"),
        ).where(api_keys.c.workspace_id.is_not(None)),
    )

    candidates: dict[str, dict[str, datetime | None]] = {}
    for query in signal_queries:
        for row in bind.execute(query).mappings():
            workspace_id = row["workspace_id"]
            user_id = row["user_id"]
            if not workspace_id or not user_id:
                continue
            by_user = candidates.setdefault(workspace_id, {})
            created_at = row["created_at"]
            existing_created_at = by_user.get(user_id)
            if existing_created_at is None or (created_at is not None and created_at < existing_created_at):
                by_user[user_id] = created_at

    return candidates


def _backfill_non_default_workspace_memberships(
    bind: sa.Connection,
    workspaces: sa.Table,
    workspace_memberships: sa.Table,
    migration_review_items: sa.Table,
    existing_pairs: set[tuple[str, str]],
    existing_review_keys: set[tuple[str, str, str]],
    known_user_ids: set[str],
    member_candidates_by_workspace: dict[str, dict[str, datetime | None]],
) -> None:
    non_default_workspaces = bind.execute(
        sa.select(
            workspaces.c.id,
            workspaces.c.tenant_id,
            workspaces.c.created_by,
            workspaces.c.created_at,
            workspaces.c.updated_at,
        )
        .where(workspaces.c.is_default.is_(False))
        .order_by(workspaces.c.created_at.asc(), workspaces.c.id.asc())
    ).mappings().all()

    for workspace in non_default_workspaces:
        founder_user_id = workspace["created_by"] if workspace["created_by"] in known_user_ids else None
        created_by = _membership_audit_actor(founder_user_id, workspace["created_by"], known_user_ids)

        if founder_user_id is not None:
            _insert_workspace_membership(
                bind,
                workspace_memberships,
                existing_pairs,
                workspace_id=workspace["id"],
                user_id=founder_user_id,
                role="founder",
                created_by=created_by,
                created_at=workspace["created_at"] or _utcnow(),
                updated_at=workspace["updated_at"] or workspace["created_at"] or _utcnow(),
            )
        else:
            _insert_review_item(
                bind,
                migration_review_items,
                existing_review_keys,
                category=REVIEW_CATEGORY_WORKSPACE_FOUNDER_GAP,
                subject_type=REVIEW_SUBJECT_TYPE_WORKSPACE,
                subject_id=workspace["id"],
                details={
                    "workspace_id": workspace["id"],
                    "tenant_id": workspace["tenant_id"],
                    "is_default": False,
                    "founder_source": None,
                    "selected_user_id": None,
                    "reason": "non-default workspace founder unresolved because workspace.created_by is missing or not resolvable",
                    "workspace_created_by": workspace["created_by"],
                },
            )

        candidate_users = member_candidates_by_workspace.get(workspace["id"], {})
        for user_id, first_seen_at in sorted(candidate_users.items(), key=lambda item: ((item[1] or datetime.max), item[0])):
            if user_id == founder_user_id:
                continue
            if user_id not in known_user_ids:
                continue
            _insert_workspace_membership(
                bind,
                workspace_memberships,
                existing_pairs,
                workspace_id=workspace["id"],
                user_id=user_id,
                role="member",
                created_by=created_by,
                created_at=first_seen_at or workspace["created_at"] or _utcnow(),
                updated_at=workspace["updated_at"] or first_seen_at or workspace["created_at"] or _utcnow(),
            )


def _backfill_visibility(
    bind: sa.Connection,
    knowledge_bases: sa.Table,
    chat_skills: sa.Table,
) -> None:
    bind.execute(
        knowledge_bases.update().values(visibility=WORKSPACE_VISIBILITY_PRIVATE)
    )
    bind.execute(
        chat_skills.update().values(visibility=WORKSPACE_VISIBILITY_PRIVATE)
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    _create_review_table(inspector)
    inspector = sa.inspect(bind)
    _create_safe_indexes(inspector)

    users = _load_table(bind, "users")
    workspaces = _load_table(bind, "workspaces")
    tenant_memberships = _load_table(bind, "tenant_memberships")
    workspace_memberships = _load_table(bind, "workspace_memberships")
    knowledge_bases = _load_table(bind, "knowledge_bases")
    chat_skills = _load_table(bind, "chat_skills")
    chat_sessions = _load_table(bind, "chat_sessions")
    chat_runs = _load_table(bind, "chat_runs")
    documents = _load_table(bind, "documents")
    api_keys = _load_table(bind, "api_keys")
    migration_review_items = _load_table(bind, "migration_review_items")

    known_user_ids = {
        row["id"]
        for row in bind.execute(sa.select(users.c.id)).mappings()
    }
    existing_pairs = _load_existing_membership_pairs(bind, workspace_memberships)
    existing_review_keys = _load_existing_review_keys(bind, migration_review_items)

    _backfill_default_workspace_memberships(
        bind,
        workspaces,
        tenant_memberships,
        workspace_memberships,
        migration_review_items,
        existing_pairs,
        existing_review_keys,
        known_user_ids,
    )

    member_candidates_by_workspace = _load_non_default_workspace_member_candidates(
        bind,
        documents=documents,
        chat_skills=chat_skills,
        chat_sessions=chat_sessions,
        chat_runs=chat_runs,
        knowledge_bases=knowledge_bases,
        api_keys=api_keys,
    )

    _backfill_non_default_workspace_memberships(
        bind,
        workspaces,
        workspace_memberships,
        migration_review_items,
        existing_pairs,
        existing_review_keys,
        known_user_ids,
        member_candidates_by_workspace,
    )

    _backfill_visibility(bind, knowledge_bases, chat_skills)

    # Intentionally deferred in Batch B1:
    # 1. case-insensitive unique enforcement on users.email:
    #    still high-risk without per-environment duplicate/null remediation.
    # 2. active founder partial unique index:
    #    SQLite/MySQL portability is not stable enough for this batch.
    # 3. invite normalized-email uniqueness:
    #    depends on runtime normalization/storage policy that lands later.


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    if _has_index(
        inspector,
        "workspace_memberships",
        "ix_workspace_memberships_workspace_status_role",
    ):
        op.drop_index(
            "ix_workspace_memberships_workspace_status_role",
            table_name="workspace_memberships",
        )

    inspector = sa.inspect(op.get_bind())
    if _has_table(inspector, "migration_review_items"):
        if _has_index(inspector, "migration_review_items", "ix_migration_review_items_subject"):
            op.drop_index("ix_migration_review_items_subject", table_name="migration_review_items")
        if _has_index(inspector, "migration_review_items", "ix_migration_review_items_category"):
            op.drop_index("ix_migration_review_items_category", table_name="migration_review_items")
        op.drop_table("migration_review_items")

    # Data backfills on workspace memberships / visibility are intentionally not
    # reversed here to avoid deleting post-migration runtime data from tables
    # introduced by the prior phase4 foundation migration.
