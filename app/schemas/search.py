from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class FastSearchRequest(BaseModel):
    document_id: str = Field(..., description="The ID of the document to search within")
    version_id: str = Field(..., description="The version ID of the document")
    query: str = Field(..., description="The search query")
    node_top_k: int = Field(10, ge=5, le=20, description="Number of top nodes to retrieve")
    include_snippets: bool = Field(True, description="Whether to include snippets in the response")
    allow_runtime_pdf_fallback: bool = Field(
        False,
        description="Debug-only fallback that allows runtime PDF extraction when ES section text is missing",
    )

class FastSearchNode(BaseModel):
    node_id: str
    title: Optional[str]
    page_start: Optional[int]
    page_end: Optional[int]
    score: float
    source: str
    snippet: Optional[str] = None
    summary: Optional[str] = None

class FastSearchResponse(BaseModel):
    mode: str = Field(..., description="The search mode used, e.g., hybrid, sparse_only")
    node_top_k: int
    latency_ms: int
    server_total_latency_ms: Optional[int] = Field(None, description="End-to-end backend Fast Search latency")
    corpus_load_latency_ms: Optional[int] = Field(None, description="DB node corpus load latency")
    content_enrich_latency_ms: Optional[int] = Field(None, description="Section text enrichment latency")
    dense_search_latency_ms: Optional[int] = Field(None, description="Dense backend latency, including query embedding and ES search")
    node_score_latency_ms: Optional[int] = Field(None, description="Local lexical/hybrid scoring latency")
    legacy_node_shadow_latency_ms: Optional[int] = Field(None, description="Legacy node shadow scoring latency field")
    nodes: List[FastSearchNode]
    boundary_flags: List[str] = Field(..., description="List of boundary flags, e.g., ['complex_query']")
    fallback_recommendation: Optional[str] = Field(None, description="Recommendation if boundary flags are hit or fallback occurred")
    active_backend: Optional[str] = Field(None, description="The active backend used, e.g., es_shadow or lexical_fallback")
    fallback_reason: Optional[str] = Field(None, description="Reason for fallback if any")
    requested_dense_source: Optional[str] = Field(None, description="The requested dense source")
    dense_source: Optional[str] = Field(None, description="The actual dense source used")
    query_embedding_computed: bool = Field(False, description="Whether query embedding was computed")
    query_embedding_dimensions: Optional[int] = Field(None, description="Query embedding vector dimensions")
    artifact_count: Optional[int] = Field(None, description="Legacy diagnostic count of embedding artifacts considered")
    artifact_exact_scan_executed: bool = Field(False, description="Legacy diagnostic; artifact exact scan is not a production runtime backend")
    es_executed: bool = Field(False, description="Whether ES search executed")
    section_text_participated: bool = Field(False, description="Whether section text participated in scoring")
    section_text_node_count: int = Field(0, description="Number of nodes with section text available")
    section_text_source: Optional[str] = Field(None, description="Runtime source for section text, e.g. es_shadow or missing")
    section_text_degraded_reason: Optional[str] = Field(None, description="Why section text was unavailable or degraded")
    runtime_pdf_fallback_allowed: bool = Field(False, description="Whether debug runtime PDF fallback was allowed")
