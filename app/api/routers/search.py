import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_principal
from app.core.db import get_db
from app.core.principal import Principal
from app.core.config import get_settings
from app.schemas.search import FastSearchRequest, FastSearchResponse, FastSearchNode
from app.services.chat_service import resolve_document_version
from app.services.node_shadow_service import run_fast_search
from app.services.node_embedding_service import EsNodeDenseSearchBackend

router = APIRouter(prefix="/api/v1", tags=["search"])
logger = logging.getLogger(__name__)

@router.post("/search/fast", response_model=FastSearchResponse)
async def fast_search(
    payload: FastSearchRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    # Resolve document and version checking permissions implicitly
    try:
        document, version = resolve_document_version(db, principal, payload.document_id, payload.version_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

    settings_obj = get_settings()
    dense_search_backend = EsNodeDenseSearchBackend()

    result = run_fast_search(
        db=db,
        principal=principal,
        document=document,
        version=version,
        query=payload.query,
        top_k=payload.node_top_k,
        include_snippets=payload.include_snippets,
        dense_search_backend=dense_search_backend,
        settings_obj=settings_obj,
        allow_runtime_pdf_fallback=payload.allow_runtime_pdf_fallback,
    )

    nodes = [FastSearchNode(**node) for node in result["nodes"]]

    return FastSearchResponse(
        mode=result["mode"],
        node_top_k=result["node_top_k"],
        latency_ms=result["latency_ms"],
        server_total_latency_ms=result.get("server_total_latency_ms"),
        corpus_load_latency_ms=result.get("corpus_load_latency_ms"),
        content_enrich_latency_ms=result.get("content_enrich_latency_ms"),
        dense_search_latency_ms=result.get("dense_search_latency_ms"),
        node_score_latency_ms=result.get("node_score_latency_ms"),
        legacy_node_shadow_latency_ms=result.get("legacy_node_shadow_latency_ms"),
        nodes=nodes,
        boundary_flags=result["boundary_flags"],
        fallback_recommendation=result["fallback_recommendation"],
        active_backend=result.get("active_backend"),
        fallback_reason=result.get("fallback_reason"),
        requested_dense_source=result.get("requested_dense_source"),
        dense_source=result.get("dense_source"),
        query_embedding_computed=bool(result.get("query_embedding_computed")),
        query_embedding_dimensions=result.get("query_embedding_dimensions"),
        artifact_count=result.get("artifact_count"),
        artifact_exact_scan_executed=bool(result.get("artifact_exact_scan_executed")),
        es_executed=bool(result.get("es_executed")),
        section_text_participated=bool(result.get("section_text_participated")),
        section_text_node_count=int(result.get("section_text_node_count") or 0),
        section_text_source=result.get("section_text_source"),
        section_text_degraded_reason=result.get("section_text_degraded_reason"),
        runtime_pdf_fallback_allowed=bool(result.get("runtime_pdf_fallback_allowed")),
    )
