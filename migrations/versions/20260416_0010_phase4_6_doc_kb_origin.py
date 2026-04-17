"""Add uploaded_via_kb_id to documents table.

Revision ID: 20260416_0010
Revises: 20260416_0009
Create Date: 2026-04-16
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "20260416_0010"
down_revision = "20260416_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("documents"):
        return

    column_names = {column["name"] for column in inspector.get_columns("documents")}
    if "uploaded_via_kb_id" not in column_names:
        op.add_column("documents", sa.Column("uploaded_via_kb_id", sa.String(64), nullable=True))

    inspector = sa.inspect(bind)
    index_names = {index["name"] for index in inspector.get_indexes("documents")}
    if "ix_documents_uploaded_via_kb_id" not in index_names:
        op.create_index("ix_documents_uploaded_via_kb_id", "documents", ["uploaded_via_kb_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("documents"):
        return

    index_names = {index["name"] for index in inspector.get_indexes("documents")}
    if "ix_documents_uploaded_via_kb_id" in index_names:
        op.drop_index("ix_documents_uploaded_via_kb_id", table_name="documents")

    column_names = {column["name"] for column in inspector.get_columns("documents")}
    if "uploaded_via_kb_id" in column_names:
        op.drop_column("documents", "uploaded_via_kb_id")
