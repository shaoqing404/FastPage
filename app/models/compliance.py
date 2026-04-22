from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ComplianceCheck(Base):
    __tablename__ = "compliance_checks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id"), nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False, index=True)
    knowledge_base_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    query_template: Mapped[str] = mapped_column(Text, nullable=False)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    verdict_policy_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    output_config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    retrieval_config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    generation_config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class ComplianceRun(Base):
    __tablename__ = "compliance_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), nullable=False, index=True)
    compliance_check_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    knowledge_base_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="accepted", nullable=False, index=True)
    cancel_requested: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    mode: Mapped[str] = mapped_column(String(64), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    facts_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    verdict_policy_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    output_config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    retrieval_config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    generation_config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    verdict: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    citations_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    gaps_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    conflicts_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    execution_context_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    metrics_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    error_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    worker_node_code: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
