from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ComplianceTarget(BaseModel):
    mode: Literal["knowledge_base"] = "knowledge_base"
    knowledge_base_id: str


class ComplianceVerdictPolicy(BaseModel):
    allowed_values: list[str] = Field(
        default_factory=lambda: ["pass", "fail", "inconclusive", "not_applicable"]
    )
    default_on_gap: str = "inconclusive"


class ComplianceOutputConfig(BaseModel):
    include_summary: bool = True
    include_answer: bool = True
    include_evidence: bool = True
    include_gaps: bool = True
    include_conflicts: bool = True


class ComplianceRetrievalConfig(BaseModel):
    per_document_top_k: int = 5
    global_top_k: int = 8
    selection_mode: Literal["outline_llm", "lexical_fallback"] = "outline_llm"
    max_context_pages: int | None = 20
    max_context_tokens: int | None = 12000


class ComplianceGenerationConfig(BaseModel):
    temperature: float | None = 0


class ComplianceCheckCreate(BaseModel):
    name: str
    description: str | None = None
    status: str = "active"
    target: ComplianceTarget
    query_template: str
    instructions: str | None = None
    verdict_policy: ComplianceVerdictPolicy = Field(default_factory=ComplianceVerdictPolicy)
    output_config: ComplianceOutputConfig = Field(default_factory=ComplianceOutputConfig)
    retrieval_config: ComplianceRetrievalConfig = Field(default_factory=ComplianceRetrievalConfig)
    generation_config: ComplianceGenerationConfig = Field(default_factory=ComplianceGenerationConfig)


class ComplianceCheckUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None
    target: ComplianceTarget | None = None
    query_template: str | None = None
    instructions: str | None = None
    verdict_policy: ComplianceVerdictPolicy | None = None
    output_config: ComplianceOutputConfig | None = None
    retrieval_config: ComplianceRetrievalConfig | None = None
    generation_config: ComplianceGenerationConfig | None = None


class ComplianceCheckOut(BaseModel):
    id: str
    tenant_id: str
    workspace_id: str
    name: str
    description: str | None
    status: str
    target: ComplianceTarget
    query_template: str
    instructions: str | None
    verdict_policy: dict[str, Any]
    output_config: dict[str, Any]
    retrieval_config: dict[str, Any]
    generation_config: dict[str, Any]
    created_by: str
    created_at: datetime
    updated_at: datetime


class ComplianceRunInput(BaseModel):
    question: str
    facts: dict[str, Any] = Field(default_factory=dict)


class ComplianceRunCreate(BaseModel):
    execution_mode: Literal["sync"] = "sync"
    input: ComplianceRunInput
    target: ComplianceTarget
    instructions: str | None = None
    verdict_policy: ComplianceVerdictPolicy = Field(default_factory=ComplianceVerdictPolicy)
    output_config: ComplianceOutputConfig = Field(default_factory=ComplianceOutputConfig)
    retrieval_config: ComplianceRetrievalConfig = Field(default_factory=ComplianceRetrievalConfig)
    generation_config: ComplianceGenerationConfig = Field(default_factory=ComplianceGenerationConfig)
    provider_id: str | None = None
    model: str | None = None


class ComplianceRunFromCheckCreate(BaseModel):
    execution_mode: Literal["sync"] = "sync"
    input: ComplianceRunInput
    provider_id: str | None = None
    model: str | None = None
    instructions: str | None = None
    verdict_policy: ComplianceVerdictPolicy | None = None
    output_config: ComplianceOutputConfig | None = None
    retrieval_config: ComplianceRetrievalConfig | None = None
    generation_config: ComplianceGenerationConfig | None = None


class ComplianceCitationOut(BaseModel):
    citation_id: str
    knowledge_base_id: str
    document_id: str
    version_id: str
    node_id: str | None
    page_start: int | None
    page_end: int | None
    title: str | None
    snippet_id: str
    document_label: str | None
    version_label: str | None


class ComplianceEvidenceOut(BaseModel):
    evidence_id: str
    kind: str
    statement: str
    citation_ids: list[str]
    provenance: list[ComplianceCitationOut] = Field(default_factory=list)
    source_count: int


class ComplianceGapOut(BaseModel):
    gap_id: str
    type: str
    statement: str
    severity: str
    related_citation_ids: list[str] = Field(default_factory=list)


class ComplianceConflictOut(BaseModel):
    conflict_id: str
    type: str
    summary: str
    citation_ids: list[str] = Field(default_factory=list)
    resolution_status: str


class ComplianceRunOut(BaseModel):
    id: str
    tenant_id: str
    workspace_id: str
    user_id: str
    compliance_check_id: str | None
    target: ComplianceTarget
    status: str
    mode: str
    provider_id: str | None
    model: str
    input: ComplianceRunInput
    summary: str | None
    answer: str | None
    verdict: str | None
    confidence: float | None
    citations: list[ComplianceCitationOut]
    evidence: list[ComplianceEvidenceOut]
    gaps: list[ComplianceGapOut]
    conflicts: list[ComplianceConflictOut]
    execution_context: dict[str, Any]
    metrics: dict[str, Any]
    error: dict[str, Any] | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
