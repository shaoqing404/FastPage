import json
import time
import uuid
from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.principal import Principal
from app.models.compliance import ComplianceCheck, ComplianceRun
from app.models.document import DocumentVersion
from app.models.knowledge_base import KnowledgeBase
from app.services.document_service import list_accessible_documents_by_ids
from app.services.knowledge_base_service import ensure_workspace_access, get_knowledge_base_or_404
from app.services.pageindex_service import build_answer_context, choose_relevant_nodes, load_structure_file
from app.services.provider_service import normalize_execution_model, resolve_provider_config
from app.services.storage_service import local_artifact_path
from pageindex.utils import count_tokens, extract_json, llm_completion


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
    "max_context_pages": 20,
    "max_context_tokens": 12000,
}

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
    return json.dumps(payload, ensure_ascii=False)


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
    normalized = {
        "per_document_top_k": _coerce_positive_int("per_document_top_k", data.get("per_document_top_k")),
        "global_top_k": _coerce_positive_int("global_top_k", data.get("global_top_k")),
        "selection_mode": selection_mode,
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
        "created_at": check.created_at,
        "updated_at": check.updated_at,
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
        "created_at": run.created_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
    }


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
    principal: Principal,
    workspace_id: str,
    knowledge_base: KnowledgeBase,
) -> list[dict[str, Any]]:
    bindings = [binding for binding in knowledge_base.documents if binding.enabled]
    if not bindings:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Knowledge base has no enabled manuals")

    documents = list_accessible_documents_by_ids(db, principal, [binding.document_id for binding in bindings])
    documents_by_id = {document.id: document for document in documents}
    if len(documents_by_id) != len(bindings):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="One or more knowledge base documents are not accessible")

    resolved_manuals: list[dict[str, Any]] = []
    for binding in bindings:
        document = documents_by_id[binding.document_id]
        version_id = binding.pinned_version_id or document.active_version_id
        if not version_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Document {document.id} has no resolved version for compliance execution",
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
                detail=f"Document {document.id} version {version.id} is not ready for compliance querying",
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

    retrieve_started = time.perf_counter()
    resolved_manuals = _resolve_manuals_for_knowledge_base(db, principal, run.workspace_id, knowledge_base)
    documents_considered = len(resolved_manuals)
    candidate_sections: list[dict[str, Any]] = []
    documents_with_hits = 0
    for manual in resolved_manuals:
        structure = load_structure_file(manual["version"].parsed_structure_path)
        selected_nodes = choose_relevant_nodes(
            structure,
            run.question,
            run.model,
            request_options=retrieval_request_options,
            stats_hook=stats_hook,
            top_k=int(retrieval_config["per_document_top_k"]),
            selection_mode=str(retrieval_config["selection_mode"]),
        )
        if selected_nodes:
            documents_with_hits += 1
        for node in selected_nodes:
            candidate_sections.append(
                {
                    "knowledge_base_id": run.knowledge_base_id,
                    "document": manual["document"],
                    "version": manual["version"],
                    "document_label": manual["document_label"],
                    "version_label": manual["version_label"],
                    "node": node,
                }
            )
    retrieve_ms = int((time.perf_counter() - retrieve_started) * 1000)
    citations_with_internal = _normalize_citations(candidate_sections, int(retrieval_config["global_top_k"]))
    citations = _strip_internal_citation_fields(citations_with_internal)
    resolved_mode = "single_manual" if len(resolved_manuals) == 1 else "multi_manual_federated"

    execution_context = {
        "workspace_id": run.workspace_id,
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
        },
        "merge": {
            "strategy": "sequential_kb_merge",
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
    _resolve_manuals_for_knowledge_base(db, principal, workspace_id, knowledge_base)
    provider_config = resolve_provider_config(
        db,
        principal.tenant_id,
        explicit_provider_id=payload.provider_id,
        workspace_id=workspace_id,
    )
    resolved_model = normalize_execution_model(
        provider_config.get("provider_type"),
        payload.model or provider_config.get("default_model"),
    )
    if not resolved_model:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No model resolved for this compliance run")
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
    try:
        return _execute_compliance_run(
            db,
            principal=principal,
            run=run,
            knowledge_base=knowledge_base,
            query_template=None,
            provider_config=provider_config,
        )
    except HTTPException as exc:
        return _fail_run(
            db,
            run,
            code="run_conflict",
            message=str(exc.detail),
            details={"status_code": exc.status_code, "knowledge_base_id": knowledge_base.id},
        )
    except Exception as exc:  # pragma: no cover - upstream runtime failure path
        return _fail_run(
            db,
            run,
            code="provider_unavailable",
            message=str(exc),
            details={"knowledge_base_id": knowledge_base.id},
        )


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
    _resolve_manuals_for_knowledge_base(db, principal, workspace_id, knowledge_base)
    provider_config = resolve_provider_config(
        db,
        principal.tenant_id,
        explicit_provider_id=payload.provider_id,
        workspace_id=workspace_id,
    )
    resolved_model = normalize_execution_model(
        provider_config.get("provider_type"),
        payload.model or provider_config.get("default_model"),
    )
    if not resolved_model:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No model resolved for this compliance run")

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
    try:
        return _execute_compliance_run(
            db,
            principal=principal,
            run=run,
            knowledge_base=knowledge_base,
            query_template=check.query_template,
            provider_config=provider_config,
        )
    except HTTPException as exc:
        return _fail_run(
            db,
            run,
            code="run_conflict",
            message=str(exc.detail),
            details={
                "status_code": exc.status_code,
                "knowledge_base_id": knowledge_base.id,
                "compliance_check_id": check.id,
            },
        )
    except Exception as exc:  # pragma: no cover - upstream runtime failure path
        return _fail_run(
            db,
            run,
            code="provider_unavailable",
            message=str(exc),
            details={"knowledge_base_id": knowledge_base.id, "compliance_check_id": check.id},
        )
