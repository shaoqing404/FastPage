"""phase3 compliance api

Revision ID: 20260407_0005
Revises: 20260407_0004
Create Date: 2026-04-07 22:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260407_0005"
down_revision = "20260407_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "compliance_checks",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("knowledge_base_id", sa.String(length=64), nullable=False),
        sa.Column("query_template", sa.Text(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("verdict_policy_json", sa.Text(), nullable=False),
        sa.Column("output_config_json", sa.Text(), nullable=False),
        sa.Column("retrieval_config_json", sa.Text(), nullable=False),
        sa.Column("generation_config_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_compliance_checks_tenant_id"), "compliance_checks", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_compliance_checks_workspace_id"), "compliance_checks", ["workspace_id"], unique=False)
    op.create_index(op.f("ix_compliance_checks_created_by"), "compliance_checks", ["created_by"], unique=False)
    op.create_index(op.f("ix_compliance_checks_status"), "compliance_checks", ["status"], unique=False)
    op.create_index(op.f("ix_compliance_checks_knowledge_base_id"), "compliance_checks", ["knowledge_base_id"], unique=False)

    op.create_table(
        "compliance_runs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("compliance_check_id", sa.String(length=64), nullable=True),
        sa.Column("knowledge_base_id", sa.String(length=64), nullable=False),
        sa.Column("provider_id", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("mode", sa.String(length=64), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("facts_json", sa.Text(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("verdict_policy_json", sa.Text(), nullable=False),
        sa.Column("output_config_json", sa.Text(), nullable=False),
        sa.Column("retrieval_config_json", sa.Text(), nullable=False),
        sa.Column("generation_config_json", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("verdict", sa.String(length=64), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("citations_json", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("gaps_json", sa.Text(), nullable=False),
        sa.Column("conflicts_json", sa.Text(), nullable=False),
        sa.Column("execution_context_json", sa.Text(), nullable=False),
        sa.Column("metrics_json", sa.Text(), nullable=False),
        sa.Column("error_json", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_compliance_runs_tenant_id"), "compliance_runs", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_compliance_runs_workspace_id"), "compliance_runs", ["workspace_id"], unique=False)
    op.create_index(op.f("ix_compliance_runs_user_id"), "compliance_runs", ["user_id"], unique=False)
    op.create_index(op.f("ix_compliance_runs_compliance_check_id"), "compliance_runs", ["compliance_check_id"], unique=False)
    op.create_index(op.f("ix_compliance_runs_knowledge_base_id"), "compliance_runs", ["knowledge_base_id"], unique=False)
    op.create_index(op.f("ix_compliance_runs_provider_id"), "compliance_runs", ["provider_id"], unique=False)
    op.create_index(op.f("ix_compliance_runs_status"), "compliance_runs", ["status"], unique=False)
    op.create_index(op.f("ix_compliance_runs_mode"), "compliance_runs", ["mode"], unique=False)
    op.create_index(op.f("ix_compliance_runs_verdict"), "compliance_runs", ["verdict"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_compliance_runs_verdict"), table_name="compliance_runs")
    op.drop_index(op.f("ix_compliance_runs_mode"), table_name="compliance_runs")
    op.drop_index(op.f("ix_compliance_runs_status"), table_name="compliance_runs")
    op.drop_index(op.f("ix_compliance_runs_provider_id"), table_name="compliance_runs")
    op.drop_index(op.f("ix_compliance_runs_knowledge_base_id"), table_name="compliance_runs")
    op.drop_index(op.f("ix_compliance_runs_compliance_check_id"), table_name="compliance_runs")
    op.drop_index(op.f("ix_compliance_runs_user_id"), table_name="compliance_runs")
    op.drop_index(op.f("ix_compliance_runs_workspace_id"), table_name="compliance_runs")
    op.drop_index(op.f("ix_compliance_runs_tenant_id"), table_name="compliance_runs")
    op.drop_table("compliance_runs")

    op.drop_index(op.f("ix_compliance_checks_knowledge_base_id"), table_name="compliance_checks")
    op.drop_index(op.f("ix_compliance_checks_status"), table_name="compliance_checks")
    op.drop_index(op.f("ix_compliance_checks_created_by"), table_name="compliance_checks")
    op.drop_index(op.f("ix_compliance_checks_workspace_id"), table_name="compliance_checks")
    op.drop_index(op.f("ix_compliance_checks_tenant_id"), table_name="compliance_checks")
    op.drop_table("compliance_checks")
