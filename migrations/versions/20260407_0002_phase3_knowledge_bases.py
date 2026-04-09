"""phase3 knowledge bases

Revision ID: 20260407_0002
Revises: 20260407_0001
Create Date: 2026-04-07 16:00:00
"""

from __future__ import annotations

from datetime import datetime
import json
import uuid

from alembic import op
import sqlalchemy as sa


revision = "20260407_0002"
down_revision = "20260407_0001"
branch_labels = None
depends_on = None


def _default_workspace_id_for_tenant(tenant_id: str) -> str:
    suffix = tenant_id.replace("-", "_")
    return f"workspace_default_{suffix}"[:64]


def upgrade() -> None:
    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("retrieval_profile_json", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_knowledge_bases_tenant_id"), "knowledge_bases", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_knowledge_bases_workspace_id"), "knowledge_bases", ["workspace_id"], unique=False)
    op.create_index(op.f("ix_knowledge_bases_status"), "knowledge_bases", ["status"], unique=False)
    op.create_index(op.f("ix_knowledge_bases_created_by"), "knowledge_bases", ["created_by"], unique=False)

    op.create_table(
        "knowledge_base_documents",
        sa.Column("knowledge_base_id", sa.String(length=64), nullable=False),
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("pinned_version_id", sa.String(length=64), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_bases.id"]),
        sa.ForeignKeyConstraint(["pinned_version_id"], ["document_versions.id"]),
        sa.PrimaryKeyConstraint("knowledge_base_id", "document_id"),
    )
    op.create_index(
        op.f("ix_knowledge_base_documents_pinned_version_id"),
        "knowledge_base_documents",
        ["pinned_version_id"],
        unique=False,
    )

    op.add_column("chat_skills", sa.Column("knowledge_base_id", sa.String(length=64), nullable=True))
    op.create_index(op.f("ix_chat_skills_knowledge_base_id"), "chat_skills", ["knowledge_base_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_chat_skills_knowledge_base_id_knowledge_bases"),
        "chat_skills",
        "knowledge_bases",
        ["knowledge_base_id"],
        ["id"],
    )

    bind = op.get_bind()
    metadata = sa.MetaData()
    chat_skills = sa.Table("chat_skills", metadata, autoload_with=bind)
    chat_skill_documents = sa.Table("chat_skill_documents", metadata, autoload_with=bind)
    knowledge_bases = sa.Table("knowledge_bases", metadata, autoload_with=bind)
    knowledge_base_documents = sa.Table("knowledge_base_documents", metadata, autoload_with=bind)

    skills = bind.execute(
        sa.select(
            chat_skills.c.id,
            chat_skills.c.tenant_id,
            chat_skills.c.workspace_id,
            chat_skills.c.owner_user_id,
            chat_skills.c.name,
            chat_skills.c.created_at,
            chat_skills.c.updated_at,
        )
    ).mappings().all()

    skill_document_rows = bind.execute(
        sa.select(
            chat_skill_documents.c.skill_id,
            chat_skill_documents.c.document_id,
        ).order_by(chat_skill_documents.c.skill_id.asc(), chat_skill_documents.c.document_id.asc())
    ).mappings().all()
    documents_by_skill: dict[str, list[str]] = {}
    for row in skill_document_rows:
        documents_by_skill.setdefault(row["skill_id"], []).append(row["document_id"])

    for skill in skills:
        document_ids = documents_by_skill.get(skill["id"], [])
        if not document_ids:
            continue
        workspace_id = skill["workspace_id"] or _default_workspace_id_for_tenant(skill["tenant_id"])
        timestamp = skill["updated_at"] or skill["created_at"] or datetime.utcnow()
        knowledge_base_id = str(uuid.uuid4())
        bind.execute(
            knowledge_bases.insert().values(
                id=knowledge_base_id,
                tenant_id=skill["tenant_id"],
                workspace_id=workspace_id,
                name=f"{skill['name']} knowledge base"[:255],
                description="Auto-migrated compatibility knowledge base for existing skill bindings",
                status="active",
                retrieval_profile_json=json.dumps({}, ensure_ascii=False),
                created_by=skill["owner_user_id"],
                created_at=skill["created_at"] or timestamp,
                updated_at=timestamp,
            )
        )
        for sort_order, document_id in enumerate(document_ids):
            bind.execute(
                knowledge_base_documents.insert().values(
                    knowledge_base_id=knowledge_base_id,
                    document_id=document_id,
                    pinned_version_id=None,
                    enabled=True,
                    label=None,
                    sort_order=sort_order,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
            )
        bind.execute(
            chat_skills.update().where(chat_skills.c.id == skill["id"]).values(knowledge_base_id=knowledge_base_id)
        )

    op.alter_column("knowledge_base_documents", "enabled", server_default=None)
    op.alter_column("knowledge_base_documents", "sort_order", server_default=None)


def downgrade() -> None:
    op.drop_constraint(op.f("fk_chat_skills_knowledge_base_id_knowledge_bases"), "chat_skills", type_="foreignkey")
    op.drop_index(op.f("ix_chat_skills_knowledge_base_id"), table_name="chat_skills")
    op.drop_column("chat_skills", "knowledge_base_id")

    op.drop_index(op.f("ix_knowledge_base_documents_pinned_version_id"), table_name="knowledge_base_documents")
    op.drop_table("knowledge_base_documents")

    op.drop_index(op.f("ix_knowledge_bases_created_by"), table_name="knowledge_bases")
    op.drop_index(op.f("ix_knowledge_bases_status"), table_name="knowledge_bases")
    op.drop_index(op.f("ix_knowledge_bases_workspace_id"), table_name="knowledge_bases")
    op.drop_index(op.f("ix_knowledge_bases_tenant_id"), table_name="knowledge_bases")
    op.drop_table("knowledge_bases")
