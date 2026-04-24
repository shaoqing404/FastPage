import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.principal import Principal
from app.models.compliance import ComplianceCheck, ComplianceRun
from app.models.document import Document, DocumentVersion
from app.models.knowledge_base import KnowledgeBase
from app.services.knowledge_base_service import ensure_workspace_access, get_knowledge_base_or_404, resolve_ready_knowledge_base_manuals
from app.services.pageindex_service import (
    build_context_from_citations_async,
    load_structure_file,
    merge_candidates_round_robin,
    rerank_candidates_async,
    retrieve_candidates_for_manual_async,
    snapshot_outline_diagnostics,
)
from app.services.provider_service import resolve_embedding_config, resolve_provider_config, resolve_rerank_config, validate_provider_model_selection
from app.services.runtime_observation_service import record_run_observation_event
from app.services.task_queue_service import enqueue_compliance_run
from app.services.telemetry_service import (
    embedding_provider_telemetry,
    routing_asset_build_telemetry,
    routing_asset_item,
    telemetry_payload,
)
from pageindex.utils import count_tokens, extract_json, llm_completion


settings = get_settings()
logger = logging.getLogger(__name__)

DEFAULT_VERDICT_POLICY = {
    "allowed_values": ["pass", "fail", "inconclusive", "not_applicable"],
    "default_on_gap": "inconclusive",
}

DEFAULT_OUTPUT_CONFIG = {
    "include_summary": True,
    "include_answer": True,
    "include_evidence": True,
    "include_gaps": True,
    "include_conflicts": True,
}

DEFAULT_RETRIEVAL_CONFIG = {
    "per_document_top_k": 5,
    "global_top_k": 8,
    "selection_mode": "outline_llm",
    "rerank_mode": "auto",
    "max_context_pages": 20,
    "max_context_tokens": 12000,
}

TERMINAL_COMPLIANCE_STATUSES = {"completed", "failed", "cancelled"}
ACTIVE_COMPLIANCE_STATUSES = {"retrieving", "answering"}

DEFAULT_GENERATION_CONFIG = {
    "temperature": 0,
}


def _json_loads(text: str | None, fallback):
    if not text:
        return fallback
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return fallback


def _json_dumps(payload: Any) -> str:
    return json.dumps(jsonable_encoder(payload), ensure_ascii=False)


def _coerce_positive_int(name: str, value: Any) -> int:
    try:
        coerced = int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{name} must be an integer") from exc
    if coerced <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{name} must be greater than 0")
    return coerced


def _coerce_non_negative_float(name: str, value: Any) -> float:
    try:
        coerced = float(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{name} must be a number") from exc
    if coerced < 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{name} must be non-negative")
    return coerced


def _normalize_verdict_policy(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = {**DEFAULT_VERDICT_POLICY, **dict(payload or {})}
    allowed_values = [str(value).strip() for value in data.get("allowed_values") or [] if str(value).strip()]
    if not allowed_values:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="verdict_policy.allowed_values cannot be empty")
    default_on_gap = str(data.get("default_on_gap") or "").strip()
    if not default_on_gap:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="verdict_policy.default_on_gap is required")
    if default_on_gap not in allowed_values:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="verdict_policy.default_on_gap must be included in allowed_values",
        )
    return {
        "allowed_values": allowed_values,
        "default_on_gap": default_on_gap,
    }


def _normalize_output_config(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = {**DEFAULT_OUTPUT_CONFIG, **dict(payload or {})}
    return {
        "include_summary": bool(data.get("include_summary", True)),
        "include_answer": bool(data.get("include_answer", True)),
        "include_evidence": bool(data.get("include_evidence", True)),
        "include_gaps": bool(data.get("include_gaps", True)),
        "include_conflicts": bool(data.get("include_conflicts", True)),
    }


def _normalize_retrieval_config(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = {**DEFAULT_RETRIEVAL_CONFIG, **dict(payload or {})}
    selection_mode = str(data.get("selection_mode") or DEFAULT_RETRIEVAL_CONFIG["selection_mode"])
    if selection_mode not in {"outline_llm", "lexical_fallback"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="selection_mode must be one of: outline_llm, lexical_fallback",
        )
    rerank_mode = str(data.get("rerank_mode") or DEFAULT_RETRIEVAL_CONFIG["rerank_mode"]).strip().lower()
    if rerank_mode not in {"auto", "off", "provider", "system"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="rerank_mode must be one of: auto, off, provider, system",
        )
    normalized = {
        "per_document_top_k": _coerce_positive_int("per_document_top_k", data.get("per_document_top_k")),
        "global_top_k": _coerce_positive_int("global_top_k", data.get("global_top_k")),
        "selection_mode": selection_mode,
        "rerank_mode": rerank_mode,
        "max_context_pages": None,
        "max_context_tokens": None,
    }
    if data.get("max_context_pages") not in (None, ""):
        normalized["max_context_pages"] = _coerce_positive_int("max_context_pages", data.get("max_context_pages"))
    if data.get("max_context_tokens") not in (None, ""):
        normalized["max_context_tokens"] = _coerce_positive_int("max_context_tokens", data.get("max_context_tokens"))
    return normalized


def _normalize_generation_config(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = {**DEFAULT_GENERATION_CONFIG, **dict(payload or {})}
    temperature = data.get("temperature")
    normalized_temperature = None if temperature in (None, "") else _coerce_non_negative_float("temperature", temperature)
    if normalized_temperature is not None and normalized_temperature > 2:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="temperature must be between 0 and 2")
    return {
        "temperature": normalized_temperature,
    }


def serialize_compliance_check(check: ComplianceCheck) -> dict[str, Any]:
    return {
        "id": check.id,
        "tenant_id": check.tenant_id,
        "workspace_id": check.workspace_id,
        "name": check.name,
        "description": check.description,
        "status": check.status,
        "target": {
            "mode": "knowledge_base",
            "knowledge_base_id": check.knowledge_base_id,
        },
        "query_template": check.query_template,
        "instructions": check.instructions,
        "verdict_policy": _json_loads(check.verdict_policy_json, DEFAULT_VERDICT_POLICY),
        "output_config": _json_loads(check.output_config_json, DEFAULT_OUTPUT_CONFIG),
        "retrieval_config": _json_loads(check.retrieval_config_json, DEFAULT_RETRIEVAL_CONFIG),
        "generation_config": _json_loads(check.generation_config_json, DEFAULT_GENERATION_CONFIG),
        "created_by": check.created_by,
        "created_at": check.created_at.isoformat() if check.created_at else None,
        "updated_at": check.updated_at.isoformat() if check.updated_at else None,
    }


def serialize_compliance_run(run: ComplianceRun) -> dict[str, Any]:
    facts = _json_loads(run.facts_json, {})
    return {
        "id": run.id,
        "tenant_id": run.tenant_id,
        "workspace_id": run.workspace_id,
        "user_id": run.user_id,
        "compliance_check_id": run.compliance_check_id,
        "target": {
            "mode": "knowledge_base",
            "knowledge_base_id": run.knowledge_base_id,
        },
        "status": run.status,
        "mode": run.mode,
        "provider_id": run.provider_id,
        "model": run.model,
        "input": {
            "question": run.question,
            "facts": facts,
        },
        "summary": run.summary,
        "answer": run.answer,
        "verdict": run.verdict,
        "confidence": run.confidence,
        "citations": _json_loads(run.citations_json, []),
        "evidence": _json_loads(run.evidence_json, []),
        "gaps": _json_loads(run.gaps_json, []),
        "conflicts": _json_loads(run.conflicts_json, []),
        "execution_context": _json_loads(run.execution_context_json, {}),
        "metrics": _json_loads(run.metrics_json, {}),
        "error": _json_loads(run.error_json, None),
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


async def _record_compliance_observation(
    run: ComplianceRun,
    *,
    event_type: str,
    step: str | None = None,
    status_value: str | None = None,
    payload: dict | None = None,
) -> None:
    await record_run_observation_event(
        run_kind="compliance",
        run_id=run.id,
        tenant_id=run.tenant_id,
        workspace_id=run.workspace_id,
        event_type=event_type,
        step=step,
        status_value=status_value,
        payload=payload,
    )


async def _record_compliance_step_started(run: ComplianceRun, step: str, payload: dict | None = None) -> None:
    await _record_compliance_observation(run, event_type="step_started", step=step, status_value=run.status, payload=payload)


async def _record_compliance_step_completed(run: ComplianceRun, step: str, payload: dict | None = None) -> None:
    await _record_compliance_observation(run, event_type="step_completed", step=step, status_value=run.status, payload=payload)


def _routing_asset_item_for_version(document_id: str, version: DocumentVersion) -> dict[str, Any]:
    return routing_asset_item(
        document_id=document_id,
        version_id=version.id,
        routing_index_status=getattr(version, "routing_index_status", None),
        routing_index_path=getattr(version, "routing_index_path", None),
        routing_index_version=getattr(version, "routing_asset_schema_version", None),
    )


def _routing_asset_items_for_manuals(manuals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for manual in manuals:
        document = manual.get("document")
        version = manual.get("version")
        if document is None or version is None:
            continue
        items.append(_routing_asset_item_for_version(document.id, version))
    return items


def mark_orphaned_compliance_runs_for_retry(db: Session) -> list[str]:
    cutoff = datetime.utcnow() - timedelta(seconds=settings.compliance_run_lease_timeout_seconds)
    stale_runs = db.scalars(
        select(ComplianceRun).where(
            ComplianceRun.status.in_(ACTIVE_COMPLIANCE_STATUSES | {"queued"}),
            ComplianceRun.heartbeat_at.is_not(None),
            ComplianceRun.heartbeat_at < cutoff,
        )
    ).all()
    requeued_ids: list[str] = []
    for run in stale_runs:
        run.status = "queued"
        run.worker_node_code = None
        run.claimed_at = None
        run.heartbeat_at = datetime.utcnow()
        metrics = _json_loads(run.metrics_json, {})
        metrics["error"] = {"code": "worker_lease_expired", "message": "worker lease expired; requeued"}
        run.metrics_json = _json_dumps(metrics)
        requeued_ids.append(run.id)
    if requeued_ids:
        db.commit()
    return requeued_ids


def list_compliance_checks(db: Session, principal: Principal, workspace_id: str) -> list[ComplianceCheck]:
    ensure_workspace_access(principal, workspace_id)
    return db.scalars(
        select(ComplianceCheck)
        .where(
            ComplianceCheck.tenant_id == principal.tenant_id,
            ComplianceCheck.workspace_id == workspace_id,
        )
        .order_by(ComplianceCheck.created_at.desc())
    ).all()


def get_compliance_check_or_404(db: Session, principal: Principal, workspace_id: str, check_id: str) -> ComplianceCheck:
    ensure_workspace_access(principal, workspace_id)
    check = db.scalar(
        select(ComplianceCheck).where(
            ComplianceCheck.id == check_id,
            ComplianceCheck.tenant_id == principal.tenant_id,
            ComplianceCheck.workspace_id == workspace_id,
        )
    )
    if check is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Compliance check not found")
    return check


def create_compliance_check(db: Session, principal: Principal, workspace_id: str, payload) -> ComplianceCheck:
    ensure_workspace_access(principal, workspace_id)
    get_knowledge_base_or_404(db, principal, workspace_id, payload.target.knowledge_base_id)
    now = datetime.utcnow()
    check = ComplianceCheck(
        id=str(uuid.uuid4()),
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        created_by=principal.user_id,
        name=payload.name,
        description=payload.description,
        status=payload.status,
        knowledge_base_id=payload.target.knowledge_base_id,
        query_template=payload.query_template,
        instructions=payload.instructions,
        verdict_policy_json=_json_dumps(_normalize_verdict_policy(payload.verdict_policy.model_dump())),
        output_config_json=_json_dumps(_normalize_output_config(payload.output_config.model_dump())),
        retrieval_config_json=_json_dumps(_normalize_retrieval_config(payload.retrieval_config.model_dump())),
        generation_config_json=_json_dumps(_normalize_generation_config(payload.generation_config.model_dump())),
        created_at=now,
        updated_at=now,
    )
    db.add(check)
    db.commit()
    db.refresh(check)
    return check


def update_compliance_check(db: Session, principal: Principal, workspace_id: str, check_id: str, payload) -> ComplianceCheck:
    check = get_compliance_check_or_404(db, principal, workspace_id, check_id)
    update_dict = payload.model_dump(exclude_unset=True)
    if "status" in update_dict and update_dict["status"] is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="status cannot be null")
    if "target" in update_dict and update_dict["target"] is not None:
        get_knowledge_base_or_404(db, principal, workspace_id, update_dict["target"]["knowledge_base_id"])
        check.knowledge_base_id = update_dict["target"]["knowledge_base_id"]
    if "verdict_policy" in update_dict and update_dict["verdict_policy"] is not None:
        check.verdict_policy_json = _json_dumps(_normalize_verdict_policy(update_dict.pop("verdict_policy")))
    if "output_config" in update_dict and update_dict["output_config"] is not None:
        check.output_config_json = _json_dumps(_normalize_output_config(update_dict.pop("output_config")))
    if "retrieval_config" in update_dict and update_dict["retrieval_config"] is not None:
        check.retrieval_config_json = _json_dumps(_normalize_retrieval_config(update_dict.pop("retrieval_config")))
    if "generation_config" in update_dict and update_dict["generation_config"] is not None:
        check.generation_config_json = _json_dumps(_normalize_generation_config(update_dict.pop("generation_config")))
    update_dict.pop("target", None)
    for field, value in update_dict.items():
        setattr(check, field, value)
    check.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(check)
    return check


def delete_compliance_check(db: Session, principal: Principal, workspace_id: str, check_id: str) -> None:
    check = get_compliance_check_or_404(db, principal, workspace_id, check_id)
    db.delete(check)
    db.commit()


def list_compliance_runs(
    db: Session,
    principal: Principal,
    workspace_id: str,
    *,
    status_value: str | None = None,
    compliance_check_id: str | None = None,
    mode: str | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
) -> list[ComplianceRun]:
    ensure_workspace_access(principal, workspace_id)
    stmt = select(ComplianceRun).where(
        ComplianceRun.tenant_id == principal.tenant_id,
        ComplianceRun.workspace_id == workspace_id,
    )
    if status_value:
        stmt = stmt.where(ComplianceRun.status == status_value)
    if compliance_check_id:
        stmt = stmt.where(ComplianceRun.compliance_check_id == compliance_check_id)
    if mode:
        stmt = stmt.where(ComplianceRun.mode == mode)
    if created_after:
        stmt = stmt.where(ComplianceRun.created_at >= created_after)
    if created_before:
        stmt = stmt.where(ComplianceRun.created_at <= created_before)
    return db.scalars(stmt.order_by(ComplianceRun.created_at.desc())).all()


def get_compliance_run_or_404(db: Session, principal: Principal, workspace_id: str, run_id: str) -> ComplianceRun:
    ensure_workspace_access(principal, workspace_id)
    run = db.scalar(
        select(ComplianceRun).where(
            ComplianceRun.id == run_id,
            ComplianceRun.tenant_id == principal.tenant_id,
            ComplianceRun.workspace_id == workspace_id,
        )
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Compliance run not found")
    return run


def _resolve_manuals_for_knowledge_base(
    db: Session,
    workspace_id: str,
    knowledge_base: KnowledgeBase,
) -> list[dict[str, Any]]:
    bindings = [binding for binding in knowledge_base.documents if binding.enabled]
    if not bindings:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Knowledge base has no enabled manuals")

    documents = db.scalars(select(Document).where(Document.id.in_([binding.document_id for binding in bindings]))).all()
    documents_by_id = {document.id: document for document in documents}
    if len(documents_by_id) != len(bindings):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="One or more knowledge base documents are not accessible")

    resolved_manuals: list[dict[str, Any]] = []
    for binding in sorted(bindings, key=lambda item: (item.sort_order, item.created_at or datetime.min, item.document_id)):
        document = documents_by_id[binding.document_id]
        version_id = binding.pinned_version_id or document.active_version_id
        if not version_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Document {document.id} has no resolved version for querying",
            )
        version = db.get(DocumentVersion, version_id)
        if version is None or version.document_id != document.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Resolved version {version_id} was not found for document {document.id}",
            )
        if version.parse_status != "index_ready" or not version.parsed_structure_path:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Document {document.id} version {version.id} is not ready for querying",
            )
        resolved_manuals.append(
            {
                "binding": binding,
                "document": document,
                "version": version,
                "document_label": binding.label or document.display_name,
                "version_label": f"v{version.version_no}",
                "workspace_id": workspace_id,
            }
        )
    return resolved_manuals


def _build_compliance_prompt(
    *,
    query_template: str | None,
    question: str,
    facts: dict[str, Any],
    instructions: str | None,
    verdict_policy: dict[str, Any],
    citations: list[dict[str, Any]],
    context_blocks: list[str],
) -> str:
    query_template_block = f"Check definition:\n{query_template.strip()}\n\n" if query_template else ""
    instructions_block = f"Additional instructions:\n{instructions.strip()}\n\n" if instructions else ""
    citations_index = "\n".join(
        f"- {citation['citation_id']} | {citation.get('document_label') or citation['document_id']} | "
        f"{citation.get('title') or 'untitled'} | pages {citation.get('page_start')}-{citation.get('page_end')}"
        for citation in citations
    )
    facts_json = json.dumps(facts or {}, ensure_ascii=False, indent=2)
    context_text = "\n\n".join(context_blocks)
    return f"""
You are a compliance analysis engine. Use only the cited manual excerpts below.

{query_template_block}User question:
{question}

Structured facts:
{facts_json}

{instructions_block}Allowed verdicts:
{json.dumps(verdict_policy.get("allowed_values", []), ensure_ascii=False)}

If the evidence is incomplete, use this default verdict:
{verdict_policy.get("default_on_gap")}

Available citations:
{citations_index}

Source excerpts:
{context_text}

Return JSON only in this exact shape:
{{
  "summary": "short summary",
  "answer": "full machine-friendly answer",
  "verdict": "one allowed verdict",
  "confidence": 0.0,
  "evidence": [
    {{
      "kind": "supporting",
      "statement": "fact grounded in the cited manuals",
      "citation_ids": ["cit_1"]
    }}
  ],
  "gaps": [
    {{
      "type": "insufficient_evidence",
      "statement": "what the manuals do not establish",
      "severity": "high",
      "related_citation_ids": []
    }}
  ],
  "conflicts": [
    {{
      "type": "cross_manual_conflict",
      "summary": "describe the conflict",
      "citation_ids": ["cit_1", "cit_2"],
      "resolution_status": "unresolved"
    }}
  ]
}}

Rules:
- Do not invent citations or manual text.
- Every evidence item must include at least one valid citation_id.
- Gaps and conflicts may use an empty citation list only when no cited excerpt supports them directly.
- Keep summary and answer factual, concise, and grounded in the excerpts.
- Set confidence to a number between 0 and 1 when possible.
""".strip()


def _normalize_citations(candidates: list[dict[str, Any]], global_top_k: int) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates[:global_top_k], start=1):
        node = candidate["node"]
        document = candidate["document"]
        version = candidate["version"]
        citation_id = f"cit_{index}"
        normalized.append(
            {
                "citation_id": citation_id,
                "knowledge_base_id": candidate["knowledge_base_id"],
                "document_id": document.id,
                "version_id": version.id,
                "node_id": node.get("node_id"),
                "page_start": node.get("start_index"),
                "page_end": node.get("end_index"),
                "title": node.get("title"),
                "snippet_id": f"{document.id}:{version.id}:{node.get('node_id')}",
                "document_label": candidate["document_label"],
                "version_label": candidate["version_label"],
                "_node": node,
                "_storage_path": version.storage_path,
            }
        )
    return normalized


def _build_context_blocks(
    *,
    citations: list[dict[str, Any]],
    model: str,
    max_context_pages: int | None,
    max_context_tokens: int | None,
) -> list[str]:
    remaining_pages = max_context_pages
    remaining_tokens = max_context_tokens
    blocks: list[str] = []
    for citation in citations:
        if remaining_pages is not None and remaining_pages <= 0:
            break
        if remaining_tokens is not None and remaining_tokens <= 0:
            break
        node = citation["_node"]
        with local_artifact_path(citation["_storage_path"]) as pdf_path:
            excerpt = build_answer_context(
                [node],
                str(pdf_path),
                model,
                max_context_pages=remaining_pages,
                max_context_tokens=remaining_tokens,
            )
        if not excerpt.strip():
            continue
        blocks.append(
            "\n".join(
                [
                    f"[{citation['citation_id']}]",
                    f"source: {citation.get('document_label') or citation['document_id']} ({citation['version_label']})",
                    f"pages: {citation.get('page_start')}-{citation.get('page_end')}",
                    f"title: {citation.get('title') or 'untitled'}",
                    excerpt,
                ]
            )
        )
        if remaining_pages is not None and citation.get("page_start") is not None and citation.get("page_end") is not None:
            remaining_pages -= int(citation["page_end"]) - int(citation["page_start"]) + 1
        if remaining_tokens is not None:
            remaining_tokens -= count_tokens(excerpt, model=model)
    return blocks


def _build_gap_on_empty_evidence(verdict_policy: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]]]:
    summary = "No sufficiently relevant cited manual evidence was retrieved from the knowledge base."
    answer = "The run is inconclusive because the current KB retrieval did not yield grounded evidence for a compliance verdict."
    gaps = [
        {
            "gap_id": "gap_1",
            "type": "insufficient_evidence",
            "statement": "No retrieved manual excerpts were strong enough to support a grounded compliance answer.",
            "severity": "high",
            "related_citation_ids": [],
        }
    ]
    return summary, answer, gaps


def _sanitize_verdict(verdict: Any, verdict_policy: dict[str, Any]) -> str:
    allowed_values = verdict_policy.get("allowed_values") or DEFAULT_VERDICT_POLICY["allowed_values"]
    verdict_str = str(verdict or "").strip()
    if verdict_str in allowed_values:
        return verdict_str
    return verdict_policy.get("default_on_gap", DEFAULT_VERDICT_POLICY["default_on_gap"])


def _normalize_confidence(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    if confidence < 0:
        return 0.0
    if confidence > 1:
        return 1.0
    return confidence


def _attach_evidence_provenance(
    evidence_items: list[dict[str, Any]],
    citations_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(evidence_items, start=1):
        citation_ids = [citation_id for citation_id in item.get("citation_ids") or [] if citation_id in citations_by_id]
        if not citation_ids:
            continue
        provenance = [citations_by_id[citation_id] for citation_id in citation_ids]
        normalized.append(
            {
                "evidence_id": item.get("evidence_id") or f"ev_{index}",
                "kind": str(item.get("kind") or "supporting"),
                "statement": str(item.get("statement") or "").strip(),
                "citation_ids": citation_ids,
                "provenance": provenance,
                "source_count": len(provenance),
            }
        )
    return [item for item in normalized if item["statement"]]


def _normalize_gaps(gap_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(gap_items, start=1):
        statement = str(item.get("statement") or "").strip()
        if not statement:
            continue
        normalized.append(
            {
                "gap_id": item.get("gap_id") or f"gap_{index}",
                "type": str(item.get("type") or "insufficient_evidence"),
                "statement": statement,
                "severity": str(item.get("severity") or "medium"),
                "related_citation_ids": [str(citation_id) for citation_id in item.get("related_citation_ids") or []],
            }
        )
    return normalized


def _normalize_conflicts(conflict_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(conflict_items, start=1):
        summary = str(item.get("summary") or "").strip()
        if not summary:
            continue
        normalized.append(
            {
                "conflict_id": item.get("conflict_id") or f"conf_{index}",
                "type": str(item.get("type") or "interpretation_conflict"),
                "summary": summary,
                "citation_ids": [str(citation_id) for citation_id in item.get("citation_ids") or []],
                "resolution_status": str(item.get("resolution_status") or "unresolved"),
            }
        )
    return normalized


def _strip_internal_citation_fields(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            key: value
            for key, value in citation.items()
            if not key.startswith("_")
        }
        for citation in citations
    ]


def _build_failed_error(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "details": details or {},
    }


def _execute_compliance_run(
    db: Session,
    *,
    principal: Principal,
    run: ComplianceRun,
    knowledge_base: KnowledgeBase,
    query_template: str | None,
    provider_config: dict[str, Any],
) -> ComplianceRun:
    started = time.perf_counter()
    run.status = "retrieving"
    run.started_at = datetime.utcnow()
    db.commit()

    retrieval_config = _json_loads(run.retrieval_config_json, DEFAULT_RETRIEVAL_CONFIG)
    generation_config = _json_loads(run.generation_config_json, DEFAULT_GENERATION_CONFIG)
    verdict_policy = _json_loads(run.verdict_policy_json, DEFAULT_VERDICT_POLICY)
    facts = _json_loads(run.facts_json, {})
    embedding_mode = retrieval_config.get("embedding_mode")
    embedding_config = resolve_embedding_config(
        provider_config=provider_config,
        embedding_mode=embedding_mode,
    )
    embedding_telemetry = embedding_provider_telemetry(
        requested_mode=embedding_mode,
        embedding_config=embedding_config,
    )

    usage_totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "successful_llm_calls": 0,
    }

    def stats_hook(event: dict) -> None:
        if not event.get("ok"):
            return
        usage = event.get("usage") or {}
        usage_totals["successful_llm_calls"] += 1
        usage_totals["input_tokens"] += int(usage.get("prompt_tokens") or 0)
        usage_totals["output_tokens"] += int(usage.get("completion_tokens") or 0)
        total_tokens = usage.get("total_tokens")
        if total_tokens is None:
            total_tokens = int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0)
        usage_totals["total_tokens"] += int(total_tokens or 0)

    request_options = {
        "api_base": provider_config["base_url"],
        "api_key": provider_config["api_key"],
        "extra_headers": provider_config.get("extra_headers") or {},
    }
    retrieval_request_options = {
        **request_options,
    }
    generation_request_options = {
        **request_options,
        **dict(generation_config or {}),
    }

    run.model = validate_provider_model_selection(
        provider_id=provider_config.get("provider_id"),
        provider_type=provider_config.get("provider_type"),
        provider_name=provider_config.get("name"),
        default_model=provider_config.get("default_model"),
        supported_models=provider_config.get("supported_models"),
        model=run.model,
        subject="Compliance run model",
    )
    db.commit()

    retrieve_started = time.perf_counter()
    resolved_manuals = _resolve_manuals_for_knowledge_base(db, run.workspace_id, knowledge_base)
    routing_asset_telemetry = routing_asset_build_telemetry(
        items=_routing_asset_items_for_manuals(resolved_manuals),
        mode="live_retrieval_diagnostic",
        dry_run=False,
        backfill=False,
        attempted=False,
    )
    documents_considered = len(resolved_manuals)
    candidate_sections: list[dict[str, Any]] = []
    per_manual_candidates: list[list[dict[str, Any]]] = []
    documents_with_hits = 0
    retrieval_warnings: list[str] = []
    outline_diagnostics: dict[str, Any] = {
        "requested_top_k": int(retrieval_config["per_document_top_k"]),
        "selection_mode": retrieval_config["selection_mode"],
        "manuals": [],
        "warnings": [],
    }
    for manual in resolved_manuals:
        diagnostics: dict[str, Any] = {}
        structure = load_structure_file(manual["version"].parsed_structure_path)
        selected_nodes = choose_relevant_nodes(
            structure,
            run.question,
            run.model,
            request_options=retrieval_request_options,
            stats_hook=stats_hook,
            top_k=int(retrieval_config["per_document_top_k"]),
            selection_mode=str(retrieval_config["selection_mode"]),
            diagnostics=diagnostics,
        )
        if selected_nodes:
            documents_with_hits += 1
        manual_candidates: list[dict[str, Any]] = []
        outline_diagnostics["manuals"].append(
            snapshot_outline_diagnostics(
                {
                    "document_id": manual["document"].id,
                    "version_id": manual["version"].id,
                    "document_label": manual["document_label"],
                    "version_label": manual["version_label"],
                },
                diagnostics,
                candidate_count=len(selected_nodes),
            )
        )
        for warning in outline_diagnostics["manuals"][-1].get("warnings", []):
            if isinstance(warning, str) and warning not in outline_diagnostics["warnings"]:
                outline_diagnostics["warnings"].append(warning)
        for warning in diagnostics.get("warnings", []):
            if isinstance(warning, str) and warning not in retrieval_warnings:
                retrieval_warnings.append(warning)
        for node in selected_nodes:
            manual_candidates.append(
                {
                    "knowledge_base_id": run.knowledge_base_id,
                    "document": manual["document"],
                    "version": manual["version"],
                    "document_label": manual["document_label"],
                    "version_label": manual["version_label"],
                    "node": node,
                }
            )
        per_manual_candidates.append(manual_candidates)
        candidate_sections.extend(manual_candidates)
    retrieve_ms = int((time.perf_counter() - retrieve_started) * 1000)
    outline_diagnostics["manual_count"] = len(resolved_manuals)
    outline_diagnostics["documents_considered"] = documents_considered
    outline_diagnostics["documents_with_hits"] = documents_with_hits
    outline_diagnostics["selection_strategy"] = (
        outline_diagnostics["manuals"][0].get("selection_strategy") if outline_diagnostics["manuals"] else None
    )
    outline_diagnostics["json_repair_applied"] = any(
        bool(entry.get("json_repair_applied")) for entry in outline_diagnostics["manuals"]
    )
    outline_diagnostics["json_repair_succeeded"] = any(
        bool(entry.get("json_repair_succeeded")) for entry in outline_diagnostics["manuals"]
    )
    manual_merged_candidates = merge_candidates_round_robin(per_manual_candidates, int(retrieval_config["global_top_k"]))
    citations_with_internal = _normalize_citations(manual_merged_candidates, int(retrieval_config["global_top_k"]))
    citations = _strip_internal_citation_fields(citations_with_internal)
    resolved_mode = "single_manual" if len(resolved_manuals) == 1 else "multi_manual_federated"

    execution_context = {
        "workspace_id": run.workspace_id,
        "telemetry": telemetry_payload(
            embedding_provider=embedding_telemetry,
            routing_asset_build=routing_asset_telemetry,
        ),
        "target": {
            "requested_mode": "knowledge_base",
            "resolved_mode": resolved_mode,
            "knowledge_base_id": run.knowledge_base_id,
        },
        "resolved_manuals": [
            {
                "document_id": manual["document"].id,
                "version_id": manual["version"].id,
                "label": manual["document_label"],
                "version_label": manual["version_label"],
            }
            for manual in resolved_manuals
        ],
        "retrieval": {
            "per_document_top_k": retrieval_config["per_document_top_k"],
            "global_top_k": retrieval_config["global_top_k"],
            "selection_mode": retrieval_config["selection_mode"],
            "documents_considered": documents_considered,
            "documents_with_hits": documents_with_hits,
            "warnings": retrieval_warnings,
            "diagnostics": {
                "outline": outline_diagnostics,
            },
        },
        "merge": {
            "strategy": "round_robin_manual_merge",
            "candidate_count": len(candidate_sections),
            "selected_citation_count": len(citations),
        },
        "generation": {
            "provider_id": run.provider_id,
            "model": run.model,
            "temperature": generation_config.get("temperature"),
        },
    }

    if not citations_with_internal:
        summary, answer, gaps = _build_gap_on_empty_evidence(verdict_policy)
        total_ms = int((time.perf_counter() - started) * 1000)
        run.mode = resolved_mode
        run.status = "completed"
        run.summary = summary
        run.answer = answer
        run.verdict = verdict_policy["default_on_gap"]
        run.confidence = None
        run.citations_json = "[]"
        run.evidence_json = "[]"
        run.gaps_json = _json_dumps(gaps)
        run.conflicts_json = "[]"
        run.execution_context_json = _json_dumps(execution_context)
        run.metrics_json = _json_dumps(
            {
                "retrieve_ms": retrieve_ms,
                "merge_ms": 0,
                "answer_ms": 0,
                "total_ms": total_ms,
                "manual_count": documents_considered,
                "documents_considered": documents_considered,
                "documents_with_hits": documents_with_hits,
                "global_selected_section_count": 0,
                **usage_totals,
            }
        )
        run.finished_at = datetime.utcnow()
        run.error_json = None
        db.commit()
        db.refresh(run)
        return run

    merge_started = time.perf_counter()
    context_blocks = _build_context_blocks(
        citations=citations_with_internal,
        model=run.model,
        max_context_pages=retrieval_config.get("max_context_pages"),
        max_context_tokens=retrieval_config.get("max_context_tokens"),
    )
    merge_ms = int((time.perf_counter() - merge_started) * 1000)

    if not context_blocks:
        summary, answer, gaps = _build_gap_on_empty_evidence(verdict_policy)
        total_ms = int((time.perf_counter() - started) * 1000)
        run.mode = resolved_mode
        run.status = "completed"
        run.summary = summary
        run.answer = answer
        run.verdict = verdict_policy["default_on_gap"]
        run.confidence = None
        run.citations_json = _json_dumps(citations)
        run.evidence_json = "[]"
        run.gaps_json = _json_dumps(gaps)
        run.conflicts_json = "[]"
        run.execution_context_json = _json_dumps(execution_context)
        run.metrics_json = _json_dumps(
            {
                "retrieve_ms": retrieve_ms,
                "merge_ms": merge_ms,
                "answer_ms": 0,
                "total_ms": total_ms,
                "manual_count": documents_considered,
                "documents_considered": documents_considered,
                "documents_with_hits": documents_with_hits,
                "global_selected_section_count": len(citations),
                **usage_totals,
            }
        )
        run.finished_at = datetime.utcnow()
        run.error_json = None
        db.commit()
        db.refresh(run)
        return run

    run.status = "answering"
    db.commit()

    answer_started = time.perf_counter()
    response = llm_completion(
        model=run.model,
        prompt=_build_compliance_prompt(
            query_template=query_template,
            question=run.question,
            facts=facts,
            instructions=run.instructions,
            verdict_policy=verdict_policy,
            citations=citations,
            context_blocks=context_blocks,
        ),
        raise_on_error=True,
        request_options=generation_request_options,
        stats_hook=stats_hook,
    )
    answer_ms = int((time.perf_counter() - answer_started) * 1000)
    payload = extract_json(response)
    if not isinstance(payload, dict):
        payload = {}

    citations_by_id = {citation["citation_id"]: citation for citation in citations}
    evidence = _attach_evidence_provenance(payload.get("evidence") or [], citations_by_id)
    gaps = _normalize_gaps(payload.get("gaps") or [])
    conflicts = _normalize_conflicts(payload.get("conflicts") or [])
    if not evidence and not gaps:
        _, _, gaps = _build_gap_on_empty_evidence(verdict_policy)

    total_ms = int((time.perf_counter() - started) * 1000)
    run.mode = resolved_mode
    run.status = "completed"
    run.summary = str(payload.get("summary") or "").strip() or "Compliance analysis completed."
    run.answer = str(payload.get("answer") or "").strip() or run.summary
    run.verdict = _sanitize_verdict(payload.get("verdict"), verdict_policy)
    run.confidence = _normalize_confidence(payload.get("confidence"))
    run.citations_json = _json_dumps(citations)
    run.evidence_json = _json_dumps(evidence)
    run.gaps_json = _json_dumps(gaps)
    run.conflicts_json = _json_dumps(conflicts)
    run.execution_context_json = _json_dumps(execution_context)
    run.metrics_json = _json_dumps(
        {
            "retrieve_ms": retrieve_ms,
            "merge_ms": merge_ms,
            "answer_ms": answer_ms,
            "total_ms": total_ms,
            "manual_count": documents_considered,
            "documents_considered": documents_considered,
            "documents_with_hits": documents_with_hits,
            "global_selected_section_count": len(citations),
            **usage_totals,
        }
    )
    run.error_json = None
    run.finished_at = datetime.utcnow()
    db.commit()
    db.refresh(run)
    return run


def _fail_run(db: Session, run: ComplianceRun, *, code: str, message: str, details: dict[str, Any] | None = None) -> ComplianceRun:
    run.status = "failed"
    run.error_json = _json_dumps(_build_failed_error(code, message, details))
    run.finished_at = datetime.utcnow()
    metrics = _json_loads(run.metrics_json, {})
    metrics["error"] = {
        "code": code,
        "message": message,
    }
    run.metrics_json = _json_dumps(metrics)
    db.commit()
    db.refresh(run)
    return run


def _create_pending_run(
    *,
    principal: Principal,
    workspace_id: str,
    compliance_check_id: str | None,
    knowledge_base_id: str,
    provider_id: str | None,
    model: str,
    question: str,
    facts: dict[str, Any],
    instructions: str | None,
    verdict_policy: dict[str, Any],
    output_config: dict[str, Any],
    retrieval_config: dict[str, Any],
    generation_config: dict[str, Any],
) -> ComplianceRun:
    return ComplianceRun(
        id=str(uuid.uuid4()),
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        user_id=principal.user_id,
        compliance_check_id=compliance_check_id,
        knowledge_base_id=knowledge_base_id,
        provider_id=provider_id,
        model=model,
        status="accepted",
        mode="single_manual",
        question=question,
        facts_json=_json_dumps(facts),
        instructions=instructions,
        verdict_policy_json=_json_dumps(verdict_policy),
        output_config_json=_json_dumps(output_config),
        retrieval_config_json=_json_dumps(retrieval_config),
        generation_config_json=_json_dumps(generation_config),
        summary=None,
        answer=None,
        verdict=None,
        confidence=None,
        citations_json="[]",
        evidence_json="[]",
        gaps_json="[]",
        conflicts_json="[]",
        execution_context_json="{}",
        metrics_json="{}",
        error_json=None,
        started_at=None,
        finished_at=None,
        created_at=datetime.utcnow(),
    )


def create_compliance_run(db: Session, principal: Principal, workspace_id: str, payload) -> ComplianceRun:
    ensure_workspace_access(principal, workspace_id)
    knowledge_base = get_knowledge_base_or_404(db, principal, workspace_id, payload.target.knowledge_base_id)
    _resolve_manuals_for_knowledge_base(db, workspace_id, knowledge_base)
    provider_config = resolve_provider_config(
        db,
        principal.tenant_id,
        explicit_provider_id=payload.provider_id,
        workspace_id=workspace_id,
    )
    resolved_model = validate_provider_model_selection(
        provider_id=provider_config.get("provider_id"),
        provider_type=provider_config.get("provider_type"),
        provider_name=provider_config.get("name"),
        default_model=provider_config.get("default_model"),
        supported_models=provider_config.get("supported_models"),
        model=payload.model,
        subject="Compliance run model",
    )
    run = _create_pending_run(
        principal=principal,
        workspace_id=workspace_id,
        compliance_check_id=None,
        knowledge_base_id=knowledge_base.id,
        provider_id=provider_config.get("provider_id"),
        model=resolved_model,
        question=payload.input.question,
        facts=payload.input.facts,
        instructions=payload.instructions,
        verdict_policy=_normalize_verdict_policy(payload.verdict_policy.model_dump()),
        output_config=_normalize_output_config(payload.output_config.model_dump()),
        retrieval_config=_normalize_retrieval_config(payload.retrieval_config.model_dump()),
        generation_config=_normalize_generation_config(payload.generation_config.model_dump()),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    run.status = "queued"
    run.heartbeat_at = datetime.utcnow()
    db.commit()
    db.refresh(run)
    enqueue_compliance_run(run.id)
    return run


def create_compliance_run_from_check(
    db: Session,
    principal: Principal,
    workspace_id: str,
    check_id: str,
    payload,
) -> ComplianceRun:
    check = get_compliance_check_or_404(db, principal, workspace_id, check_id)
    if check.status != "active":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Compliance check is not active")

    knowledge_base = get_knowledge_base_or_404(db, principal, workspace_id, check.knowledge_base_id)
    _resolve_manuals_for_knowledge_base(db, workspace_id, knowledge_base)
    provider_config = resolve_provider_config(
        db,
        principal.tenant_id,
        explicit_provider_id=payload.provider_id,
        workspace_id=workspace_id,
    )
    resolved_model = validate_provider_model_selection(
        provider_id=provider_config.get("provider_id"),
        provider_type=provider_config.get("provider_type"),
        provider_name=provider_config.get("name"),
        default_model=provider_config.get("default_model"),
        supported_models=provider_config.get("supported_models"),
        model=payload.model,
        subject="Compliance run model",
    )

    verdict_policy = _normalize_verdict_policy(
        payload.verdict_policy.model_dump() if payload.verdict_policy is not None else _json_loads(check.verdict_policy_json, {})
    )
    output_config = _normalize_output_config(
        payload.output_config.model_dump() if payload.output_config is not None else _json_loads(check.output_config_json, {})
    )
    retrieval_config = _normalize_retrieval_config(
        payload.retrieval_config.model_dump()
        if payload.retrieval_config is not None
        else _json_loads(check.retrieval_config_json, {})
    )
    generation_config = _normalize_generation_config(
        payload.generation_config.model_dump()
        if payload.generation_config is not None
        else _json_loads(check.generation_config_json, {})
    )

    run = _create_pending_run(
        principal=principal,
        workspace_id=workspace_id,
        compliance_check_id=check.id,
        knowledge_base_id=check.knowledge_base_id,
        provider_id=provider_config.get("provider_id"),
        model=resolved_model,
        question=payload.input.question,
        facts=payload.input.facts,
        instructions=payload.instructions if payload.instructions is not None else check.instructions,
        verdict_policy=verdict_policy,
        output_config=output_config,
        retrieval_config=retrieval_config,
        generation_config=generation_config,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    run.status = "queued"
    run.heartbeat_at = datetime.utcnow()
    db.commit()
    db.refresh(run)
    enqueue_compliance_run(run.id)
    return run


def _touch_compliance_heartbeat(db: Session, run: ComplianceRun) -> ComplianceRun:
    run.heartbeat_at = datetime.utcnow()
    db.commit()
    db.refresh(run)
    return run


async def _retry_compliance_async(step_name: str, operation, *, run: ComplianceRun) -> Any:
    attempt = 0
    while True:
        try:
            return await operation()
        except Exception as exc:
            attempt += 1
            if attempt > settings.run_step_max_retries:
                raise
            await _record_compliance_observation(
                run,
                event_type="step_failed",
                step=step_name,
                status_value=run.status,
                payload={
                    "attempt": attempt,
                    "retrying": True,
                    "error": str(exc),
                    "next_retry_delay_ms": settings.run_step_retry_base_ms * (2 ** (attempt - 1)),
                },
            )
            await asyncio.sleep((settings.run_step_retry_base_ms * (2 ** (attempt - 1))) / 1000)


def _compliance_citation_from_candidate(candidate: dict, *, knowledge_base_id: str, index: int) -> dict:
    return {
        "citation_id": f"cit_{index}",
        "knowledge_base_id": knowledge_base_id,
        "document_id": candidate.get("document_id"),
        "version_id": candidate.get("version_id"),
        "node_id": candidate.get("node_id"),
        "page_start": candidate.get("page_start"),
        "page_end": candidate.get("page_end"),
        "title": candidate.get("title"),
        "snippet_id": f"{candidate.get('document_id')}:{candidate.get('version_id')}:{candidate.get('node_id')}",
        "document_label": candidate.get("document_label"),
        "version_label": candidate.get("version_label"),
        "_node": candidate.get("_node"),
        "_storage_path": candidate.get("_storage_path"),
    }


async def _finalize_compliance_run(
    db: Session,
    run: ComplianceRun,
    *,
    status_value: str,
    error_payload: dict[str, Any] | None = None,
) -> ComplianceRun:
    run.status = status_value
    run.finished_at = datetime.utcnow()
    run.worker_node_code = None
    run.claimed_at = None
    run.heartbeat_at = datetime.utcnow()
    if error_payload is not None:
        run.error_json = _json_dumps(error_payload)
        metrics = _json_loads(run.metrics_json, {})
        metrics["error"] = error_payload
        run.metrics_json = _json_dumps(metrics)
    db.commit()
    db.refresh(run)
    await _record_compliance_observation(
        run,
        event_type="run_completed" if status_value == "completed" else "run_failed",
        status_value=status_value,
        payload=serialize_compliance_run(run) if status_value == "completed" else error_payload,
    )
    return run


async def run_compliance_run(run_id: str) -> None:
    db = SessionLocal()
    try:
        requeued_ids = mark_orphaned_compliance_runs_for_retry(db)
        for stale_run_id in requeued_ids:
            enqueue_compliance_run(stale_run_id)

        run = db.get(ComplianceRun, run_id)
        if run is None or run.status in TERMINAL_COMPLIANCE_STATUSES:
            return

        now = datetime.utcnow()
        run.status = "retrieving"
        run.started_at = run.started_at or now
        run.claimed_at = now
        run.heartbeat_at = now
        run.worker_node_code = settings.worker_node_code
        run.error_json = None
        db.commit()
        db.refresh(run)
        queue_ms = (
            max(int((run.started_at - run.created_at).total_seconds() * 1000), 0)
            if run.started_at and run.created_at
            else 0
        )
        await _record_compliance_observation(
            run,
            event_type="run_status",
            status_value=run.status,
            payload={"queue_ms": queue_ms, "worker_node_code": run.worker_node_code},
        )

        knowledge_base = db.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.id == run.knowledge_base_id,
                KnowledgeBase.tenant_id == run.tenant_id,
                KnowledgeBase.workspace_id == run.workspace_id,
            )
        )
        if knowledge_base is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge base not found")
        provider_config = resolve_provider_config(
            db,
            run.tenant_id,
            explicit_provider_id=run.provider_id,
            workspace_id=run.workspace_id,
        )
        run.model = validate_provider_model_selection(
            provider_id=provider_config.get("provider_id"),
            provider_type=provider_config.get("provider_type"),
            provider_name=provider_config.get("name"),
            default_model=provider_config.get("default_model"),
            supported_models=provider_config.get("supported_models"),
            model=run.model,
            subject="Compliance run model",
        )
        db.commit()
        db.refresh(run)

        retrieval_config = _json_loads(run.retrieval_config_json, DEFAULT_RETRIEVAL_CONFIG)
        generation_config = _json_loads(run.generation_config_json, DEFAULT_GENERATION_CONFIG)
        verdict_policy = _json_loads(run.verdict_policy_json, DEFAULT_VERDICT_POLICY)
        facts = _json_loads(run.facts_json, {})
        embedding_mode = retrieval_config.get("embedding_mode")
        embedding_config = resolve_embedding_config(
            provider_config=provider_config,
            embedding_mode=embedding_mode,
        )
        embedding_telemetry = embedding_provider_telemetry(
            requested_mode=embedding_mode,
            embedding_config=embedding_config,
        )
        await _record_compliance_observation(
            run,
            event_type="run_status",
            status_value=run.status,
            payload={"telemetry": telemetry_payload(embedding_provider=embedding_telemetry)},
        )
        query_template = None
        if run.compliance_check_id:
            check = db.get(ComplianceCheck, run.compliance_check_id)
            query_template = check.query_template if check is not None else None

        usage_totals = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "successful_llm_calls": 0,
        }

        def stats_hook(event: dict) -> None:
            if not event.get("ok"):
                return
            usage = event.get("usage") or {}
            usage_totals["successful_llm_calls"] += 1
            usage_totals["input_tokens"] += int(usage.get("prompt_tokens") or 0)
            usage_totals["output_tokens"] += int(usage.get("completion_tokens") or 0)
            total_tokens = usage.get("total_tokens")
            if total_tokens is None:
                total_tokens = int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0)
            usage_totals["total_tokens"] += int(total_tokens or 0)

        request_options = {
            "api_base": provider_config["base_url"],
            "api_key": provider_config["api_key"],
            "extra_headers": provider_config.get("extra_headers") or {},
        }

        retrieve_started = time.perf_counter()
        await _record_compliance_step_started(run, "resolve_manuals")
        resolved_manuals = _resolve_manuals_for_knowledge_base(db, run.workspace_id, knowledge_base)
        if len(resolved_manuals) > settings.run_max_manuals:
            raise RuntimeError(f"Compliance run resolved too many manuals ({len(resolved_manuals)}). Maximum allowed is {settings.run_max_manuals}.")
        routing_asset_telemetry = routing_asset_build_telemetry(
            items=_routing_asset_items_for_manuals(resolved_manuals),
            mode="live_retrieval_diagnostic",
            dry_run=False,
            backfill=False,
            attempted=False,
        )
        await _record_compliance_step_completed(
            run,
            "resolve_manuals",
            {
                "manual_count": len(resolved_manuals),
                "telemetry": telemetry_payload(routing_asset_build=routing_asset_telemetry),
            },
        )

        await _record_compliance_step_started(run, "load_structures")
        manuals_with_structure = resolved_manuals
        await _record_compliance_step_completed(run, "load_structures", {"manual_count": len(manuals_with_structure), "lazy_loaded": True})

        candidate_top_k = max(int(retrieval_config["global_top_k"]) * 3, 12, int(retrieval_config["per_document_top_k"]))
        semaphore = asyncio.Semaphore(max(1, min(settings.retrieval_max_concurrency, len(manuals_with_structure))))
        retrieval_warnings: list[str] = []
        outline_diagnostics: dict[str, Any] = {
            "requested_top_k": candidate_top_k,
            "selection_mode": retrieval_config["selection_mode"],
            "manuals": [],
            "warnings": [],
        }
        await _record_compliance_step_started(
            run,
            "retrieve_candidates",
            {"manual_count": len(manuals_with_structure), "candidate_top_k": candidate_top_k},
        )

        async def retrieve_manual_candidates(manual: dict) -> list[dict]:
            diagnostics: dict[str, Any] = {}

            async def operation():
                async with semaphore:
                    structure = load_structure_file(manual["version"].parsed_structure_path)
                    candidates = await retrieve_candidates_for_manual_async(
                        structure,
                        run.question,
                        run.model,
                        request_options=request_options,
                        stats_hook=stats_hook,
                        candidate_top_k=candidate_top_k,
                        selection_mode=str(retrieval_config["selection_mode"]),
                        diagnostics=diagnostics,
                    )
                    del structure
                    return candidates

            candidates = await _retry_compliance_async("retrieve_candidates", operation, run=run)
            outline_diagnostics["manuals"].append(
                snapshot_outline_diagnostics(
                    {
                        "document_id": manual["document"].id,
                        "version_id": manual["version"].id,
                        "document_label": manual["document_label"],
                        "version_label": manual["version_label"],
                    },
                    diagnostics,
                    candidate_count=len(candidates),
                )
            )
            for warning in outline_diagnostics["manuals"][-1].get("warnings", []):
                if isinstance(warning, str) and warning not in outline_diagnostics["warnings"]:
                    outline_diagnostics["warnings"].append(warning)
            for warning in diagnostics.get("warnings", []):
                if isinstance(warning, str) and warning not in retrieval_warnings:
                    retrieval_warnings.append(warning)
            return [
                {
                    "candidate_id": f"{manual['document'].id}:{manual['version'].id}:{index}",
                    "document_id": manual["document"].id,
                    "version_id": manual["version"].id,
                    "document_label": manual["document_label"],
                    "version_label": manual["version_label"],
                    "title": candidate.get("title"),
                    "node_id": candidate.get("node_id"),
                    "page_start": candidate.get("start_index"),
                    "page_end": candidate.get("end_index"),
                    "_node": candidate.get("node"),
                    "_storage_path": manual["version"].storage_path,
                }
                for index, candidate in enumerate(candidates, start=1)
            ]

        per_manual_candidates = await asyncio.gather(*(retrieve_manual_candidates(manual) for manual in manuals_with_structure))
        candidate_sections = [candidate for candidates in per_manual_candidates for candidate in candidates]
        documents_with_hits = sum(1 for candidates in per_manual_candidates if candidates)
        outline_diagnostics["manual_count"] = len(manuals_with_structure)
        outline_diagnostics["documents_considered"] = len(manuals_with_structure)
        outline_diagnostics["documents_with_hits"] = documents_with_hits
        outline_diagnostics["selection_strategy"] = (
            outline_diagnostics["manuals"][0].get("selection_strategy") if outline_diagnostics["manuals"] else None
        )
        outline_diagnostics["json_repair_applied"] = any(
            bool(entry.get("json_repair_applied")) for entry in outline_diagnostics["manuals"]
        )
        outline_diagnostics["json_repair_succeeded"] = any(
            bool(entry.get("json_repair_succeeded")) for entry in outline_diagnostics["manuals"]
        )
        manual_merged_candidates = merge_candidates_round_robin(per_manual_candidates, int(retrieval_config["global_top_k"]))
        await _record_compliance_step_completed(
            run,
            "retrieve_candidates",
            {
                "candidate_count": len(candidate_sections),
                "documents_with_hits": documents_with_hits,
                "outline_diagnostics": outline_diagnostics,
            },
        )

        rerank_mode = str(retrieval_config.get("rerank_mode") or "auto")
        rerank_config = resolve_rerank_config(provider_config=provider_config, rerank_mode=rerank_mode)
        rerank_repair_diagnostics: dict[str, Any] = {}
        rerank_warning = None
        reranked_candidates = manual_merged_candidates
        rerank_meta = {
            "applied": False,
            "mode": "round_robin_manual_merge",
            "candidate_count": len(candidate_sections),
            "selected_count": len(reranked_candidates),
        }
        await _record_compliance_step_started(
            run,
            "rerank",
            {
                "requested_mode": rerank_mode,
                "resolved_mode": rerank_config.get("resolved_mode"),
                "enabled": rerank_config.get("enabled"),
                "candidate_count": len(candidate_sections),
            },
        )
        if candidate_sections and rerank_config.get("enabled"):
            async def rerank_operation():
                return await rerank_candidates_async(
                    run.question,
                    candidate_sections,
                    rerank_config.get("model"),
                    request_options={
                        "api_base": rerank_config.get("base_url"),
                        "api_key": rerank_config.get("api_key"),
                        "provider_type": rerank_config.get("provider_type"),
                    },
                    stats_hook=stats_hook,
                    top_k=int(retrieval_config["global_top_k"]),
                    diagnostics=rerank_repair_diagnostics,
                )

            try:
                reranked_candidates, rerank_meta = await _retry_compliance_async("rerank", rerank_operation, run=run)
            except Exception as exc:
                reranked_candidates = manual_merged_candidates
                rerank_meta = {
                    "applied": False,
                    "mode": "fallback_round_robin_manual_merge_after_error",
                    "candidate_count": len(candidate_sections),
                    "selected_count": len(reranked_candidates),
                }
                rerank_warning = f"Rerank failed and fell back to round-robin manual merge: {exc}"
                retrieval_warnings.append(rerank_warning)
        citations_with_internal = [
            _compliance_citation_from_candidate(candidate, knowledge_base_id=run.knowledge_base_id, index=index)
            for index, candidate in enumerate(reranked_candidates, start=1)
        ]
        citations = _strip_internal_citation_fields(citations_with_internal)
        await _record_compliance_step_completed(
            run,
            "rerank",
            {
                "selected_count": len(citations),
                "rerank_applied": rerank_meta.get("applied"),
                "rerank_model": rerank_config.get("model"),
                "rerank_provider_source": rerank_config.get("provider_source"),
                "rerank_warning": rerank_warning,
                "rerank_diagnostics": {
                    "meta": rerank_meta,
                    "repair": rerank_repair_diagnostics,
                },
            },
        )

        await _record_compliance_step_started(run, "build_context", {"citation_count": len(citations)})
        context_blocks = await build_context_from_citations_async(
            citations_with_internal,
            model=run.model,
            max_context_pages=retrieval_config.get("max_context_pages"),
            max_context_tokens=retrieval_config.get("max_context_tokens"),
        )
        merge_ms = 0
        await _record_compliance_step_completed(run, "build_context", {"context_block_count": len(context_blocks)})

        retrieve_ms = int((time.perf_counter() - retrieve_started) * 1000)
        resolved_mode = "single_manual" if len(resolved_manuals) == 1 else "multi_manual_federated"
        execution_context = {
            "workspace_id": run.workspace_id,
            "telemetry": telemetry_payload(
                embedding_provider=embedding_telemetry,
                routing_asset_build=routing_asset_telemetry,
            ),
            "target": {
                "requested_mode": "knowledge_base",
                "resolved_mode": resolved_mode,
                "knowledge_base_id": run.knowledge_base_id,
            },
            "resolved_manuals": [
                {
                    "document_id": manual["document"].id,
                    "version_id": manual["version"].id,
                    "label": manual["document_label"],
                    "version_label": manual["version_label"],
                }
                for manual in resolved_manuals
            ],
            "retrieval": {
                "per_document_top_k": retrieval_config["per_document_top_k"],
                "global_top_k": retrieval_config["global_top_k"],
                "selection_mode": retrieval_config["selection_mode"],
                "rerank_mode": rerank_mode,
                "rerank_resolved_mode": rerank_config.get("resolved_mode"),
                "documents_considered": len(resolved_manuals),
                "documents_with_hits": documents_with_hits,
                "rerank_warning": rerank_warning,
                "warnings": retrieval_warnings,
                "diagnostics": {
                    "outline": outline_diagnostics,
                    "rerank": {
                        "meta": rerank_meta,
                        "repair": rerank_repair_diagnostics,
                    },
                },
            },
            "merge": {
                "strategy": "rerank_merge" if rerank_meta.get("applied") else "round_robin_manual_merge",
                "candidate_count": len(candidate_sections),
                "selected_citation_count": len(citations),
                "fallback_mode": None if rerank_meta.get("applied") else rerank_meta.get("mode"),
            },
            "generation": {
                "provider_id": run.provider_id,
                "model": run.model,
                "temperature": generation_config.get("temperature"),
            },
        }

        if not citations_with_internal or not context_blocks:
            summary, answer, gaps = _build_gap_on_empty_evidence(verdict_policy)
            run.mode = resolved_mode
            run.summary = summary
            run.answer = answer
            run.verdict = verdict_policy["default_on_gap"]
            run.confidence = None
            run.citations_json = _json_dumps(citations)
            run.evidence_json = "[]"
            run.gaps_json = _json_dumps(gaps)
            run.conflicts_json = "[]"
            run.execution_context_json = _json_dumps(execution_context)
            run.metrics_json = _json_dumps(
                {
                    "queue_ms": queue_ms,
                    "retrieve_ms": retrieve_ms,
                    "merge_ms": merge_ms,
                    "answer_ms": 0,
                    "total_ms": retrieve_ms,
                    "wall_clock_ms": queue_ms + retrieve_ms,
                    "manual_count": len(resolved_manuals),
                    "documents_considered": len(resolved_manuals),
                    "documents_with_hits": documents_with_hits,
                    "global_selected_section_count": len(citations),
                    **usage_totals,
                }
            )
            await _finalize_compliance_run(db, run, status_value="completed")
            return

        run.status = "answering"
        db.commit()
        db.refresh(run)
        await _record_compliance_observation(run, event_type="run_status", status_value=run.status, payload={"execution_context": execution_context})
        await _record_compliance_step_started(run, "final_answer", {"model": run.model})

        answer_started = time.perf_counter()
        response = await asyncio.to_thread(
            llm_completion,
            run.model,
            _build_compliance_prompt(
                query_template=query_template,
                question=run.question,
                facts=facts,
                instructions=run.instructions,
                verdict_policy=verdict_policy,
                citations=citations,
                context_blocks=context_blocks,
            ),
            None,
            False,
            True,
            {**request_options, **dict(generation_config or {})},
            None,
            "compliance_final_answer",
            stats_hook,
        )
        answer_ms = int((time.perf_counter() - answer_started) * 1000)
        payload = extract_json(response)
        if not isinstance(payload, dict):
            payload = {}

        citations_by_id = {citation["citation_id"]: citation for citation in citations}
        evidence = _attach_evidence_provenance(payload.get("evidence") or [], citations_by_id)
        gaps = _normalize_gaps(payload.get("gaps") or [])
        conflicts = _normalize_conflicts(payload.get("conflicts") or [])
        if not evidence and not gaps:
            _, _, gaps = _build_gap_on_empty_evidence(verdict_policy)

        total_ms = retrieve_ms + merge_ms + answer_ms
        run.mode = resolved_mode
        run.summary = str(payload.get("summary") or "").strip() or "Compliance analysis completed."
        run.answer = str(payload.get("answer") or "").strip() or run.summary
        run.verdict = _sanitize_verdict(payload.get("verdict"), verdict_policy)
        run.confidence = _normalize_confidence(payload.get("confidence"))
        run.citations_json = _json_dumps(citations)
        run.evidence_json = _json_dumps(evidence)
        run.gaps_json = _json_dumps(gaps)
        run.conflicts_json = _json_dumps(conflicts)
        run.execution_context_json = _json_dumps(execution_context)
        run.metrics_json = _json_dumps(
            {
                "queue_ms": queue_ms,
                "retrieve_ms": retrieve_ms,
                "merge_ms": merge_ms,
                "answer_ms": answer_ms,
                "total_ms": total_ms,
                "wall_clock_ms": queue_ms + total_ms,
                "manual_count": len(resolved_manuals),
                "documents_considered": len(resolved_manuals),
                "documents_with_hits": documents_with_hits,
                "global_selected_section_count": len(citations),
                **usage_totals,
            }
        )
        await _record_compliance_step_completed(run, "final_answer", {"answer_ms": answer_ms, "answer_chars": len(run.answer or "")})
        await _record_compliance_step_started(run, "persist_result")
        await _record_compliance_step_completed(run, "persist_result", {"citations_count": len(citations)})
        await _finalize_compliance_run(db, run, status_value="completed")
    except HTTPException as exc:
        run = db.get(ComplianceRun, run_id)
        if run is not None:
            await _finalize_compliance_run(
                db,
                run,
                status_value="failed",
                error_payload=_build_failed_error("run_conflict", str(exc.detail), {"status_code": exc.status_code}),
            )
    except Exception as exc:  # pragma: no cover - runtime path
        logger.exception("compliance_run_failed run_id=%s", run_id)
        run = db.get(ComplianceRun, run_id)
        if run is not None:
            await _finalize_compliance_run(
                db,
                run,
                status_value="failed",
                error_payload=_build_failed_error("provider_unavailable", str(exc)),
            )
    finally:
        db.close()
