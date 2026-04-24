import asyncio
import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from pageindex.page_index import page_index_main
from app.services.storage_service import local_artifact_path
from pageindex.utils import (
    ConfigLoader,
    count_tokens,
    extract_json,
    ensure_run_reuse_cache,
    get_page_tokens,
    get_text_of_pdf_pages_with_labels,
    is_fatal_llm_model_error,
    llm_completion,
    structure_to_list,
)
from app.services.storage_service import read_json_artifact
from app.models.routing_asset_contract import (
    ROUTING_ASSET_DEFERRED,
    ROUTING_ASSET_PENDING,
    ROUTING_ASSET_READY,
    ROUTING_ASSET_SCHEMA_VERSION,
    normalize_routing_index_payload,
    routing_asset_readiness_defaults,
)


logger = logging.getLogger(__name__)

ROUTING_BUILD_MODE_DISABLED = "disabled"
ROUTING_BUILD_MODE_DRY_RUN = "dry_run"
ROUTING_BUILD_MODE_ENABLED = "enabled"
ROUTING_BUILD_MODES = {
    ROUTING_BUILD_MODE_DISABLED,
    ROUTING_BUILD_MODE_DRY_RUN,
    ROUTING_BUILD_MODE_ENABLED,
}

ROUTING_SYNC_PARSE_JOB_STEPS = (
    "parse_pdf_to_structure",
    "write_document_structure",
    "build_base_routing_nodes",
    "compute_summary_coverage",
    "run_disabled_or_dry_run_hook_stubs",
    "write_routing_index",
    "replace_document_routing_node_rows",
)
ROUTING_ASYNC_BACKFILL_STEPS = (
    "route_doc_materialization",
    "synthetic_query_generation",
    "embedding_backfill",
)


@dataclass(frozen=True)
class RoutingBuildOptions:
    route_docs_mode: str = ROUTING_BUILD_MODE_DISABLED
    synthetic_queries_mode: str = ROUTING_BUILD_MODE_DISABLED
    embeddings_mode: str = ROUTING_BUILD_MODE_DISABLED

    @classmethod
    def disabled(cls) -> "RoutingBuildOptions":
        return cls()


def parse_pdf_to_structure(pdf_path: str, model: str) -> dict:
    opt = ConfigLoader().load(
        {
            "model": model,
            "if_add_doc_description": "no",
            "if_add_node_text": "no",
            "if_add_node_id": "yes",
        }
    )
    return page_index_main(pdf_path, opt)


def _normalize_routing_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_routing_build_mode(value: Any) -> str:
    text = _normalize_routing_text(value)
    if text is None:
        return ROUTING_BUILD_MODE_DISABLED
    normalized = text.lower().replace("-", "_")
    if normalized in {"0", "false", "no", "off", "disable", "disabled"}:
        return ROUTING_BUILD_MODE_DISABLED
    if normalized in {"dryrun", "dry_run", "dry"}:
        return ROUTING_BUILD_MODE_DRY_RUN
    if normalized in {"1", "true", "yes", "on", "enable", "enabled", "persist", "materialize", "build"}:
        return ROUTING_BUILD_MODE_ENABLED
    if normalized in ROUTING_BUILD_MODES:
        return normalized
    logger.warning("Unknown routing build mode %r; using disabled", value)
    return ROUTING_BUILD_MODE_DISABLED


def routing_build_options_from_settings(settings_obj: Any) -> RoutingBuildOptions:
    return normalize_routing_build_options(
        RoutingBuildOptions(
            route_docs_mode=getattr(settings_obj, "routing_route_docs_build_mode", None),
            synthetic_queries_mode=getattr(settings_obj, "routing_synthetic_queries_build_mode", None),
            embeddings_mode=getattr(settings_obj, "routing_embeddings_build_mode", None),
        )
    )


def normalize_routing_build_options(build_options: RoutingBuildOptions | None = None) -> RoutingBuildOptions:
    if build_options is None:
        return RoutingBuildOptions.disabled()
    return RoutingBuildOptions(
        route_docs_mode=_normalize_routing_build_mode(build_options.route_docs_mode),
        synthetic_queries_mode=_normalize_routing_build_mode(build_options.synthetic_queries_mode),
        embeddings_mode=_normalize_routing_build_mode(build_options.embeddings_mode),
    )


def _routing_breadcrumb(document_label: str | None, ancestors: list[str]) -> str | None:
    breadcrumb_parts: list[str] = []
    normalized_label = _normalize_routing_text(document_label)
    if normalized_label:
        breadcrumb_parts.append(normalized_label)
    breadcrumb_parts.extend(part for part in ancestors if part)
    if not breadcrumb_parts:
        return None
    return " / ".join(breadcrumb_parts)


def _collect_routing_index_nodes(
    nodes: list[dict] | dict | None,
    *,
    document_label: str | None,
    parent_node_id: str | None = None,
    depth: int = 0,
    ancestors: list[str] | None = None,
    collected: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if collected is None:
        collected = []
    if not nodes:
        return collected

    node_list = nodes if isinstance(nodes, list) else [nodes]
    ancestor_titles = list(ancestors or [])
    for node in node_list:
        node_id = _normalize_routing_text(node.get("node_id"))
        title = _normalize_routing_text(node.get("title"))
        current_titles = ancestor_titles + ([title] if title else [])
        collected.append(
            {
                "node_id": node_id,
                "parent_node_id": parent_node_id,
                "depth": depth,
                "title": title,
                "breadcrumb": _routing_breadcrumb(document_label, current_titles),
                "page_start": node.get("start_index"),
                "page_end": node.get("end_index"),
                "route_summary": _normalize_routing_text(node.get("summary")),
                "contrastive_summary": None,
                "aliases_json": None,
                "keywords_json": None,
                "manual_profile_text": None,
            }
        )
        child_nodes = node.get("nodes") or []
        if child_nodes:
            _collect_routing_index_nodes(
                child_nodes,
                document_label=document_label,
                parent_node_id=node_id,
                depth=depth + 1,
                ancestors=current_titles,
                collected=collected,
            )
    return collected


def compute_summary_coverage(routing_nodes: list[dict[str, Any]]) -> dict[str, Any]:
    total_nodes = len(routing_nodes)
    missing_summary_node_ids: list[str | None] = []
    summary_count = 0

    for node in routing_nodes:
        if _normalize_routing_text(node.get("route_summary")):
            summary_count += 1
            continue
        missing_summary_node_ids.append(_normalize_routing_text(node.get("node_id")))

    missing_summary_count = total_nodes - summary_count
    if total_nodes == 0:
        coverage_ratio = 1.0
        coverage_state = "empty"
    else:
        coverage_ratio = round(summary_count / total_nodes, 4)
        if missing_summary_count == 0:
            coverage_state = "complete"
        elif summary_count > 0:
            coverage_state = "partial"
        else:
            coverage_state = "missing"

    return {
        "total_nodes": total_nodes,
        "summary_count": summary_count,
        "missing_summary_count": missing_summary_count,
        "coverage_ratio": coverage_ratio,
        "coverage_state": coverage_state,
        "has_any_summary": summary_count > 0,
        "all_nodes_have_summary": missing_summary_count == 0,
        "missing_summary_node_ids": missing_summary_node_ids,
    }


def build_route_doc_for_routing_node(node: dict[str, Any]) -> dict[str, Any]:
    node_id = _normalize_routing_text(node.get("node_id"))
    title = _normalize_routing_text(node.get("title"))
    breadcrumb = _normalize_routing_text(node.get("breadcrumb"))
    summary = _normalize_routing_text(node.get("route_summary"))
    page_start = node.get("page_start")
    page_end = node.get("page_end")

    text_parts = []
    if breadcrumb:
        text_parts.append(f"Path: {breadcrumb}")
    elif title:
        text_parts.append(f"Title: {title}")
    if page_start is not None or page_end is not None:
        text_parts.append(f"Pages: {page_start or ''}-{page_end or ''}".strip())
    if summary:
        text_parts.append(f"Summary: {summary}")

    return {
        "route_doc_id": f"{node_id}:route_doc" if node_id else None,
        "node_id": node_id,
        "title": title,
        "breadcrumb": breadcrumb,
        "page_start": page_start,
        "page_end": page_end,
        "text": "\n".join(text_parts) or None,
        "summary_available": summary is not None,
    }


def build_route_docs_for_routing_nodes(routing_nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [build_route_doc_for_routing_node(node) for node in routing_nodes]


def _disabled_hook_result(stage: str) -> dict[str, Any]:
    return {
        "stage": stage,
        "mode": ROUTING_BUILD_MODE_DISABLED,
        "status": "disabled",
        "readiness": ROUTING_ASSET_DEFERRED,
        "execution": "async_backfill",
        "asset_count": 0,
    }


def _build_route_docs_hook_result(
    routing_nodes: list[dict[str, Any]],
    *,
    mode: str,
) -> tuple[dict[str, Any], list[dict[str, Any]] | None]:
    if mode == ROUTING_BUILD_MODE_DISABLED:
        return _disabled_hook_result("route_docs"), None

    route_docs = build_route_docs_for_routing_nodes(routing_nodes)
    if mode == ROUTING_BUILD_MODE_DRY_RUN:
        return (
            {
                "stage": "route_docs",
                "mode": mode,
                "status": "dry_run",
                "readiness": ROUTING_ASSET_DEFERRED,
                "execution": "sync_parse_job_dry_run",
                "asset_count": 0,
                "candidate_count": len(route_docs),
                "sample_route_doc": route_docs[0] if route_docs else None,
            },
            None,
        )

    return (
        {
            "stage": "route_docs",
            "mode": mode,
            "status": "ready",
            "readiness": ROUTING_ASSET_READY,
            "execution": "sync_parse_job",
            "asset_count": len(route_docs),
        },
        route_docs,
    )


def _build_stub_hook_result(stage: str, *, mode: str, node_count: int) -> dict[str, Any]:
    if mode == ROUTING_BUILD_MODE_DISABLED:
        return _disabled_hook_result(stage)
    if mode == ROUTING_BUILD_MODE_DRY_RUN:
        return {
            "stage": stage,
            "mode": mode,
            "status": "dry_run",
            "readiness": ROUTING_ASSET_DEFERRED,
            "execution": "sync_parse_job_dry_run",
            "asset_count": 0,
            "candidate_count": 0,
            "eligible_node_count": node_count,
        }
    return {
        "stage": stage,
        "mode": mode,
        "status": "pending_backfill",
        "readiness": ROUTING_ASSET_PENDING,
        "execution": "async_backfill",
        "asset_count": 0,
        "eligible_node_count": node_count,
    }


def _routing_build_metadata(
    routing_nodes: list[dict[str, Any]],
    *,
    build_options: RoutingBuildOptions,
) -> tuple[dict[str, Any], dict[str, str], dict[str, Any]]:
    summary_coverage = compute_summary_coverage(routing_nodes)
    route_docs_result, route_docs = _build_route_docs_hook_result(
        routing_nodes,
        mode=build_options.route_docs_mode,
    )
    synthetic_queries_result = _build_stub_hook_result(
        "synthetic_queries",
        mode=build_options.synthetic_queries_mode,
        node_count=len(routing_nodes),
    )
    embeddings_result = _build_stub_hook_result(
        "embeddings",
        mode=build_options.embeddings_mode,
        node_count=len(routing_nodes),
    )

    readiness = routing_asset_readiness_defaults(base_nodes_state=ROUTING_ASSET_READY)
    readiness["route_docs"] = route_docs_result["readiness"]
    readiness["synthetic_queries"] = synthetic_queries_result["readiness"]
    readiness["embeddings"] = embeddings_result["readiness"]

    metadata = {
        "schema_version": "routing_build_metadata_v1",
        "summary_coverage": summary_coverage,
        "hook_results": {
            "route_docs": route_docs_result,
            "synthetic_queries": synthetic_queries_result,
            "embeddings": embeddings_result,
        },
        "execution_plan": {
            "sync_parse_job_steps": list(ROUTING_SYNC_PARSE_JOB_STEPS),
            "async_backfill_steps": list(ROUTING_ASYNC_BACKFILL_STEPS),
        },
    }
    extra_payload: dict[str, Any] = {}
    if route_docs is not None:
        extra_payload["route_docs"] = route_docs
    return metadata, readiness, extra_payload


def build_routing_index_payload(
    structure: list[dict] | dict,
    *,
    document_label: str,
    document_id: str,
    version_id: str,
    source_doc_name: str | None = None,
    routing_index_version: str = ROUTING_ASSET_SCHEMA_VERSION,
    build_options: RoutingBuildOptions | None = None,
) -> dict[str, Any]:
    effective_build_options = normalize_routing_build_options(build_options)
    normalized_label = _normalize_routing_text(document_label) or _normalize_routing_text(source_doc_name)
    routing_nodes = _collect_routing_index_nodes(
        structure,
        document_label=normalized_label,
    )
    build_metadata, readiness, extra_payload = _routing_build_metadata(
        routing_nodes,
        build_options=effective_build_options,
    )
    payload = {
        "schema_version": routing_index_version or ROUTING_ASSET_SCHEMA_VERSION,
        "routing_index_version": routing_index_version or ROUTING_ASSET_SCHEMA_VERSION,
        "document_label": normalized_label,
        "source_doc_name": _normalize_routing_text(source_doc_name),
        "document_id": document_id,
        "version_id": version_id,
        "node_count": len(routing_nodes),
        "readiness": readiness,
        "build_metadata": build_metadata,
        "nodes": routing_nodes,
    }
    payload.update(extra_payload)
    return normalize_routing_index_payload(payload)


def build_outline_prompt(structure: list[dict], question: str, *, top_k: int | None = None) -> str:
    lines = []
    for node in structure_to_list(structure):
        lines.append(
            f"{node.get('node_id', '')} | {node.get('start_index')}-{node.get('end_index')} | {node.get('title', '')}"
        )
    outline_text = "\n".join(lines)
    selection_limit = max(1, int(top_k or 5))
    return f"""
You are selecting the most relevant sections of a PDF outline for answering a user question.

Question:
{question}

Outline entries:
{outline_text}

Return JSON only in this format:
{{
  "node_ids": ["0001", "0002"],
  "why": "short reason"
}}

Rules:
- Select between 1 and {selection_limit} node_ids.
- Prefer the most specific nodes over broad parent nodes.
- Only use node_ids that appear in the outline list.
"""


def build_json_repair_prompt(raw_response: str, schema_hint: str) -> str:
    return f"""
You are repairing a model response so it becomes valid JSON.

Target JSON shape:
{schema_hint}

Rules:
- Return JSON only.
- Do not wrap the JSON in markdown fences.
- Preserve the original meaning when possible.
- If the original response does not contain enough information, return the smallest valid JSON that matches the target shape.

Original response:
{raw_response}
"""


def _record_diagnostic(diagnostics: dict | None, message: str) -> None:
    if diagnostics is None:
        return
    warnings = diagnostics.setdefault("warnings", [])
    if message not in warnings:
        warnings.append(message)


def extract_json_with_repair(
    *,
    raw_response: str,
    model: str,
    request_options: dict | None = None,
    trace_hook=None,
    stats_hook=None,
    trace_label: str,
    schema_hint: str,
    expected_keys: tuple[str, ...],
) -> tuple[dict, dict]:
    payload = extract_json(raw_response, log_errors=False)
    if isinstance(payload, dict) and any(key in payload for key in expected_keys):
        return payload, {"repair_applied": False, "repair_succeeded": False}

    logger.warning("%s returned non-JSON or missing keys; attempting JSON repair", trace_label)
    try:
        repaired_response = llm_completion(
            model=model,
            prompt=build_json_repair_prompt(raw_response, schema_hint),
            raise_on_error=True,
            request_options=request_options,
            trace_hook=trace_hook,
            trace_label=f"{trace_label}_json_repair",
            stats_hook=stats_hook,
        )
    except Exception as exc:
        if is_fatal_llm_model_error(exc):
            raise
        logger.warning("%s JSON repair failed: %s", trace_label, exc)
        return {}, {"repair_applied": True, "repair_succeeded": False}

    repaired_payload = extract_json(repaired_response, log_errors=False)
    if isinstance(repaired_payload, dict) and any(key in repaired_payload for key in expected_keys):
        logger.warning("%s JSON repair succeeded", trace_label)
        return repaired_payload, {"repair_applied": True, "repair_succeeded": True}

    logger.warning("%s JSON repair still returned invalid JSON", trace_label)
    return {}, {"repair_applied": True, "repair_succeeded": False}


def choose_relevant_nodes_lexical(structure: list[dict], question: str, top_k: int) -> list[dict]:
    flat_nodes = [node for node in structure_to_list(structure) if node.get("node_id")]
    lowered_tokens = [token for token in question.lower().split() if token]
    scored = []
    for node in flat_nodes:
        title = (node.get("title") or "").lower()
        score = sum(1 for token in lowered_tokens if token in title)
        if score > 0:
            scored.append((score, node))
    scored.sort(key=lambda item: item[0], reverse=True)
    selected = [node for _, node in scored[:top_k]]
    if not selected:
        selected = flat_nodes[:top_k]
    return selected


def choose_relevant_nodes(
    structure: list[dict],
    question: str,
    model: str,
    request_options: dict | None = None,
    trace_hook=None,
    stats_hook=None,
    top_k: int = 5,
    selection_mode: str = "outline_llm",
    diagnostics: dict | None = None,
) -> list[dict]:
    flat_nodes = {node["node_id"]: node for node in structure_to_list(structure) if node.get("node_id")}
    if diagnostics is not None:
        diagnostics["requested_top_k"] = top_k
        diagnostics["available_node_count"] = len(flat_nodes)
    if selection_mode == "lexical_fallback":
        if diagnostics is not None:
            diagnostics["outline_selection_strategy"] = "lexical_fallback"
        selected = choose_relevant_nodes_lexical(structure, question, top_k)
        if diagnostics is not None:
            diagnostics["selected_count"] = len(selected)
            diagnostics["selected_node_ids"] = [node.get("node_id") for node in selected if node.get("node_id")]
        return selected
    try:
        response = llm_completion(
            model=model,
            prompt=build_outline_prompt(structure, question, top_k=top_k),
            raise_on_error=True,
            request_options=request_options,
            trace_hook=trace_hook,
            trace_label="outline_selection",
            stats_hook=stats_hook,
        )
    except Exception as exc:
        if is_fatal_llm_model_error(exc):
            raise
        _record_diagnostic(diagnostics, "大纲选段模型调用失败，已自动回退到关键词选段。")
        if diagnostics is not None:
            diagnostics["outline_selection_strategy"] = "lexical_fallback_after_llm_error"
        selected = choose_relevant_nodes_lexical(structure, question, top_k)
        if diagnostics is not None:
            diagnostics["selected_count"] = len(selected)
            diagnostics["selected_node_ids"] = [node.get("node_id") for node in selected if node.get("node_id")]
        return selected
    payload, repair_meta = extract_json_with_repair(
        raw_response=response,
        model=model,
        request_options=request_options,
        trace_hook=trace_hook,
        stats_hook=stats_hook,
        trace_label="outline_selection",
        schema_hint='{"node_ids": ["0001"], "why": "short reason"}',
        expected_keys=("node_ids",),
    )
    if repair_meta.get("repair_succeeded"):
        _record_diagnostic(diagnostics, "大纲选段返回的 JSON 不规范，系统已自动修复后继续运行。")
    elif repair_meta.get("repair_applied"):
        _record_diagnostic(diagnostics, "大纲选段返回的 JSON 无法修复，系统已自动回退到关键词选段。")
    if diagnostics is not None:
        diagnostics["json_repair_applied"] = bool(repair_meta.get("repair_applied"))
        diagnostics["json_repair_succeeded"] = bool(repair_meta.get("repair_succeeded"))
    node_ids = payload.get("node_ids", []) if isinstance(payload, dict) else []
    selected = [flat_nodes[node_id] for node_id in node_ids if node_id in flat_nodes][:top_k]

    if not selected:
        if diagnostics is not None:
            diagnostics["outline_selection_strategy"] = "lexical_fallback_after_invalid_json"
        selected = choose_relevant_nodes_lexical(structure, question, top_k)
    else:
        if diagnostics is not None:
            diagnostics["outline_selection_strategy"] = "outline_llm"

    if not selected:
        selected = list(flat_nodes.values())[:top_k]

    if diagnostics is not None:
        diagnostics["selected_count"] = len(selected)
        diagnostics["selected_node_ids"] = [node.get("node_id") for node in selected if node.get("node_id")]
    return selected


def retrieve_candidate_nodes_for_manual(
    structure: list[dict],
    question: str,
    model: str,
    *,
    request_options: dict | None = None,
    trace_hook=None,
    stats_hook=None,
    candidate_top_k: int = 12,
    selection_mode: str = "outline_llm",
    diagnostics: dict | None = None,
) -> list[dict]:
    selected = choose_relevant_nodes(
        structure,
        question,
        model,
        request_options=request_options,
        trace_hook=trace_hook,
        stats_hook=stats_hook,
        top_k=candidate_top_k,
        selection_mode=selection_mode,
        diagnostics=diagnostics,
    )
    return [
        {
            "node_id": node.get("node_id"),
            "title": node.get("title"),
            "start_index": node.get("start_index"),
            "end_index": node.get("end_index"),
            "node": node,
        }
        for node in selected
    ]


def snapshot_outline_diagnostics(
    manual: dict[str, Any],
    diagnostics: dict[str, Any] | None,
    *,
    candidate_count: int,
) -> dict[str, Any]:
    warnings: list[str] = []
    if diagnostics is not None:
        for warning in diagnostics.get("warnings") or []:
            warning_text = str(warning).strip()
            if warning_text and warning_text not in warnings:
                warnings.append(warning_text)
    return {
        "document_id": manual.get("document_id"),
        "version_id": manual.get("version_id"),
        "document_label": manual.get("document_label"),
        "version_label": manual.get("version_label"),
        "candidate_count": candidate_count,
        "requested_top_k": diagnostics.get("requested_top_k") if diagnostics else None,
        "available_node_count": diagnostics.get("available_node_count") if diagnostics else None,
        "selected_count": diagnostics.get("selected_count") if diagnostics else None,
        "selected_node_ids": list(diagnostics.get("selected_node_ids") or []) if diagnostics else [],
        "selection_strategy": diagnostics.get("outline_selection_strategy") if diagnostics else None,
        "json_repair_applied": bool(diagnostics.get("json_repair_applied")) if diagnostics else False,
        "json_repair_succeeded": bool(diagnostics.get("json_repair_succeeded")) if diagnostics else False,
        "warnings": warnings,
    }


def merge_candidates_round_robin(per_manual_candidates: list[list[dict]], top_k: int) -> list[dict]:
    if top_k <= 0:
        return []
    merged: list[dict] = []
    max_candidate_count = max((len(candidates) for candidates in per_manual_candidates), default=0)
    for offset in range(max_candidate_count):
        for candidates in per_manual_candidates:
            if offset >= len(candidates):
                continue
            merged.append(candidates[offset])
            if len(merged) >= top_k:
                return merged
    return merged


async def retrieve_candidates_for_manual_async(
    structure: list[dict],
    question: str,
    model: str,
    *,
    request_options: dict | None = None,
    trace_hook=None,
    stats_hook=None,
    candidate_top_k: int = 12,
    selection_mode: str = "outline_llm",
    diagnostics: dict | None = None,
) -> list[dict]:
    return await asyncio.to_thread(
        retrieve_candidate_nodes_for_manual,
        structure,
        question,
        model,
        request_options=request_options,
        trace_hook=trace_hook,
        stats_hook=stats_hook,
        candidate_top_k=candidate_top_k,
        selection_mode=selection_mode,
        diagnostics=diagnostics,
    )


def build_rerank_prompt(question: str, candidates: list[dict], *, top_k: int) -> str:
    candidate_lines = []
    for candidate in candidates:
        candidate_lines.append(
            "\n".join(
                [
                    f"candidate_id: {candidate['candidate_id']}",
                    f"document: {candidate.get('document_label') or candidate.get('document_id') or 'unknown'}",
                    f"title: {candidate.get('title') or 'untitled'}",
                    f"pages: {candidate.get('page_start')}-{candidate.get('page_end')}",
                ]
            )
        )
    return f"""
You are reranking retrieved manual sections for a question-answering system.

Question:
{question}

Candidates:
{chr(10).join(candidate_lines)}

Return JSON only:
{{
  "items": [
    {{
      "candidate_id": "cand_1",
      "score": 0.95,
      "why": "short reason"
    }}
  ]
}}

Rules:
- Return at most {top_k} items.
- Scores must be between 0 and 1.
- Prefer specific sections that directly answer the question.
- Do not invent candidate_ids.
""".strip()


def _is_native_rerank_provider(provider_type: str | None, base_url: str | None) -> bool:
    normalized_provider_type = str(provider_type or "").strip().lower()
    normalized_base_url = str(base_url or "").strip().lower()
    return normalized_provider_type == "dashscope_rerank" or "/services/rerank/" in normalized_base_url


def _build_native_rerank_document(candidate: dict) -> str:
    return "\n".join(
        [
            f"document: {candidate.get('document_label') or candidate.get('document_id') or 'unknown'}",
            f"title: {candidate.get('title') or 'untitled'}",
            f"pages: {candidate.get('page_start')}-{candidate.get('page_end')}",
        ]
    )


def _rerank_candidates_via_native_api(
    question: str,
    candidates: list[dict],
    model: str,
    *,
    request_options: dict | None = None,
    stats_hook=None,
    top_k: int = 8,
) -> tuple[list[dict], dict]:
    options = dict(request_options or {})
    api_base = str(options.get("api_base") or "").strip()
    api_key = str(options.get("api_key") or "").strip()
    if not api_base or not api_key:
        raise RuntimeError("Native rerank requires api_base and api_key")

    payload = {
        "model": model,
        "input": {
            "query": question,
            "documents": [_build_native_rerank_document(candidate) for candidate in candidates],
        },
        "parameters": {"top_n": min(top_k, len(candidates))},
    }
    request_obj = urllib.request.Request(
        api_base,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request_obj, timeout=60) as response:
            raw_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Native rerank request failed: {exc.code} {body}") from exc

    parsed = json.loads(raw_body)
    results = ((parsed.get("output") or {}).get("results") or []) if isinstance(parsed, dict) else []
    ranked: list[dict] = []
    seen_indexes: set[int] = set()
    for item in results:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        if index < 0 or index >= len(candidates) or index in seen_indexes:
            continue
        seen_indexes.add(index)
        ranked_candidate = dict(candidates[index])
        try:
            score = float(item.get("relevance_score"))
        except (TypeError, ValueError):
            score = 0.0
        ranked_candidate["rerank_score"] = max(0.0, min(score, 1.0))
        ranked_candidate["rerank_reason"] = None
        ranked.append(ranked_candidate)
        if len(ranked) >= top_k:
            break

    if stats_hook:
        stats_hook(
            {
                "ok": True,
                "usage": (parsed.get("usage") or {}) if isinstance(parsed, dict) else {},
            }
        )

    if not ranked:
        selected = candidates[:top_k]
        return selected, {
            "applied": False,
            "mode": "fallback_original_order",
            "candidate_count": len(candidates),
            "selected_count": len(selected),
        }

    return ranked, {
        "applied": True,
        "mode": "native_rerank",
        "candidate_count": len(candidates),
        "selected_count": len(ranked),
    }


def rerank_candidates(
    question: str,
    candidates: list[dict],
    model: str | None,
    *,
    request_options: dict | None = None,
    trace_hook=None,
    stats_hook=None,
    top_k: int = 8,
    diagnostics: dict | None = None,
) -> tuple[list[dict], dict]:
    if not candidates:
        return [], {
            "applied": False,
            "mode": "empty",
            "candidate_count": 0,
            "selected_count": 0,
        }
    if not model:
        selected = candidates[:top_k]
        return selected, {
            "applied": False,
            "mode": "disabled",
            "candidate_count": len(candidates),
            "selected_count": len(selected),
        }

    options = dict(request_options or {})
    if _is_native_rerank_provider(options.get("provider_type"), options.get("api_base")):
        return _rerank_candidates_via_native_api(
            question,
            candidates,
            model,
            request_options=options,
            stats_hook=stats_hook,
            top_k=top_k,
        )

    response = llm_completion(
        model=model,
        prompt=build_rerank_prompt(question, candidates, top_k=top_k),
        raise_on_error=True,
        request_options=options,
        trace_hook=trace_hook,
        trace_label="candidate_rerank",
        stats_hook=stats_hook,
    )
    payload, repair_meta = extract_json_with_repair(
        raw_response=response,
        model=model,
        request_options=options,
        trace_hook=trace_hook,
        stats_hook=stats_hook,
        trace_label="candidate_rerank",
        schema_hint='{"items": [{"candidate_id": "cand_1", "score": 0.95, "why": "short reason"}]}',
        expected_keys=("items",),
    )
    if diagnostics is not None:
        diagnostics["json_repair_applied"] = bool(repair_meta.get("repair_applied"))
        diagnostics["json_repair_succeeded"] = bool(repair_meta.get("repair_succeeded"))

    ranking_items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(ranking_items, list):
        selected = candidates[:top_k]
        return selected, {
            "applied": False,
            "mode": "fallback_original_order",
            "candidate_count": len(candidates),
            "selected_count": len(selected),
        }

    candidate_map = {candidate["candidate_id"]: candidate for candidate in candidates}
    ranked: list[dict] = []
    seen_ids: set[str] = set()
    for item in ranking_items:
        if not isinstance(item, dict):
            continue
        candidate_id = str(item.get("candidate_id") or "").strip()
        if not candidate_id or candidate_id in seen_ids or candidate_id not in candidate_map:
            continue
        score_raw = item.get("score")
        try:
            score = float(score_raw)
        except (TypeError, ValueError):
            score = 0.0
        ranked_candidate = dict(candidate_map[candidate_id])
        ranked_candidate["rerank_score"] = max(0.0, min(score, 1.0))
        ranked_candidate["rerank_reason"] = str(item.get("why") or "").strip() or None
        ranked.append(ranked_candidate)
        seen_ids.add(candidate_id)
        if len(ranked) >= top_k:
            break

    if not ranked:
        selected = candidates[:top_k]
        return selected, {
            "applied": False,
            "mode": "fallback_original_order",
            "candidate_count": len(candidates),
            "selected_count": len(selected),
        }

    return ranked, {
        "applied": True,
        "mode": "model_rerank",
        "candidate_count": len(candidates),
        "selected_count": len(ranked),
    }


async def rerank_candidates_async(
    question: str,
    candidates: list[dict],
    model: str | None,
    *,
    request_options: dict | None = None,
    trace_hook=None,
    stats_hook=None,
    top_k: int = 8,
    diagnostics: dict | None = None,
) -> tuple[list[dict], dict]:
    return await asyncio.to_thread(
        rerank_candidates,
        question,
        candidates,
        model,
        request_options=request_options,
        trace_hook=trace_hook,
        stats_hook=stats_hook,
        top_k=top_k,
        diagnostics=diagnostics,
    )


def build_answer_context(
    selected_nodes: list[dict],
    pdf_path: str,
    model: str,
    *,
    max_context_pages: int | None = None,
    max_context_tokens: int | None = None,
) -> str:
    pdf_pages = get_page_tokens(pdf_path, model=model)
    chunks = []
    seen = set()
    total_pages = 0
    total_tokens = 0
    for node in selected_nodes:
        start_index = node.get("start_index")
        end_index = node.get("end_index")
        if start_index is None or end_index is None:
            continue
        key = (start_index, end_index)
        if key in seen:
            continue
        seen.add(key)
        page_count = int(end_index) - int(start_index) + 1
        if max_context_pages is not None and total_pages + page_count > max_context_pages:
            break
        section_tokens = sum(pdf_pages[page_num][1] for page_num in range(start_index - 1, end_index))
        if max_context_tokens is not None and total_tokens + section_tokens > max_context_tokens:
            continue
        section_text = get_text_of_pdf_pages_with_labels(pdf_pages, start_index, end_index)
        chunks.append(f"## Section: {node.get('title')} (pages {start_index}-{end_index})\n{section_text}")
        total_pages += page_count
        total_tokens += section_tokens
    return "\n\n".join(chunks)


def build_answer_prompt(question: str, selected_nodes: list[dict], context: str, system_prompt: str | None = None) -> str:
    section_list = "\n".join(
        f"- {node.get('title')} ({node.get('start_index')}-{node.get('end_index')})" for node in selected_nodes
    )
    extra = f"System prompt:\n{system_prompt}\n\n" if system_prompt else ""
    return f"""
{extra}Answer the question using only the provided PDF excerpts.

Question:
{question}

Selected sections:
{section_list}

PDF excerpts:
{context}

Requirements:
- Be concise and factual.
- If the answer is a list, present the list directly.
- Cite page numbers in parentheses, like (pages 353-360).
- If the excerpts are insufficient, say so explicitly.
"""


def build_query_rewrite_prompt(question: str, history_context: str) -> str:
    return f"""
Rewrite the user's latest question into a standalone retrieval query using the recent conversation context.

Conversation context:
{history_context}

Latest user question:
{question}

Return JSON only:
{{
  "rewritten_query": "..."
}}

Rules:
- Preserve concrete entities, constraints, and referents from the conversation.
- Keep the rewritten query concise and retrieval-friendly.
- If no rewrite is needed, return the original question.
"""


def build_generation_prompt(
    question: str,
    selected_nodes: list[dict],
    context: str,
    *,
    system_prompt: str | None = None,
    history_context: str | None = None,
) -> str:
    section_list = "\n".join(
        f"- {node.get('title')} ({node.get('start_index')}-{node.get('end_index')})" for node in selected_nodes
    )
    extra = f"System prompt:\n{system_prompt}\n\n" if system_prompt else ""
    history_block = f"Recent conversation context:\n{history_context}\n\n" if history_context else ""
    return f"""
{extra}{history_block}Answer the question using only the provided PDF excerpts.

Question:
{question}

Selected sections:
{section_list}

PDF excerpts:
{context}

Requirements:
- Be concise and factual.
- If the answer is a list, present the list directly.
- Cite page numbers in parentheses, like (pages 353-360).
- If the excerpts are insufficient, say so explicitly.
"""


def build_citations(selected_nodes: list[dict]) -> list[dict]:
    return [
        {
            "node_id": node.get("node_id"),
            "title": node.get("title"),
            "page_start": node.get("start_index"),
            "page_end": node.get("end_index"),
            "snippet_id": node.get("node_id"),
        }
        for node in selected_nodes
    ]


def _build_context_block_for_citation(
    citation: dict[str, Any],
    *,
    model: str,
    max_context_pages: int | None,
    max_context_tokens: int | None,
) -> str:
    node = citation.get("_node") or {
        "title": citation.get("title"),
        "start_index": citation.get("page_start"),
        "end_index": citation.get("page_end"),
    }
    storage_path = citation.get("_storage_path")
    if not storage_path:
        return ""
    with local_artifact_path(storage_path) as pdf_path:
        excerpt = build_answer_context(
            [node],
            str(pdf_path),
            model,
            max_context_pages=max_context_pages,
            max_context_tokens=max_context_tokens,
        )
    if not excerpt.strip():
        return ""
    return "\n".join(
        [
            f"[{citation.get('citation_id') or citation.get('candidate_id')}]",
            f"source: {citation.get('document_label') or citation.get('document_id') or 'unknown'}",
            f"pages: {citation.get('page_start')}-{citation.get('page_end')}",
            f"title: {citation.get('title') or 'untitled'}",
            excerpt,
        ]
    )


async def build_context_from_citations_async(
    citations: list[dict[str, Any]],
    *,
    model: str,
    max_context_pages: int | None,
    max_context_tokens: int | None,
) -> list[str]:
    ensure_run_reuse_cache()

    async def build_one(citation: dict[str, Any]) -> str:
        return await asyncio.to_thread(
            _build_context_block_for_citation,
            citation,
            model=model,
            max_context_pages=max_context_pages,
            max_context_tokens=max_context_tokens,
        )

    blocks = await asyncio.gather(*(build_one(citation) for citation in citations))
    return [block for block in blocks if block.strip()]


def build_answer_with_marker(answer_text: str, citations: list[dict]) -> str:
    citations_payload = {"citations": citations}
    return (
        f"{answer_text}\n\n---\n[CITATIONS_JSON_BEGIN]\n"
        f"{json.dumps(citations_payload, ensure_ascii=False)}\n"
        "[CITATIONS_JSON_END]"
    )


def format_history_context(messages: list[dict]) -> str:
    lines: list[str] = []
    for message in messages:
        role = str(message.get("role") or "user").upper()
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def estimate_history_tokens(messages: list[dict], model: str) -> int:
    history_context = format_history_context(messages)
    return count_tokens(history_context, model=model)


def answer_question_against_structure(
    *,
    pdf_path: str,
    structure: list[dict],
    question: str,
    model: str,
    system_prompt: str | None = None,
    request_options: dict | None = None,
    retrieval_options: dict | None = None,
    generation_options: dict | None = None,
    conversation_options: dict | None = None,
    history_messages: list[dict] | None = None,
    trace_hook=None,
) -> tuple[str, list[dict], dict, dict]:
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

    started = time.perf_counter()
    retrieve_started = time.perf_counter()
    shared_options = dict(request_options or {})
    retrieval_request_options = {**shared_options, **dict(retrieval_options or {})}
    generation_request_options = {**shared_options, **dict(generation_options or {})}
    conversation_request_options = dict(conversation_options or {})

    top_k = int(retrieval_request_options.pop("top_k", 5) or 5)
    selection_mode = retrieval_request_options.pop("selection_mode", "outline_llm")
    max_context_pages = retrieval_request_options.pop("max_context_pages", None)
    max_context_tokens = retrieval_request_options.pop("max_context_tokens", None)
    query_rewrite_with_history = bool(conversation_request_options.pop("query_rewrite_with_history", True))
    include_history = bool(conversation_request_options.pop("include_history", True))

    prepared_history_messages = list(history_messages or [])
    history_context = format_history_context(prepared_history_messages) if include_history and prepared_history_messages else ""
    history_token_estimate = estimate_history_tokens(prepared_history_messages, model=model) if history_context else 0
    retrieval_query = question
    rewritten_query = None
    rewrite_applied = False

    if query_rewrite_with_history and history_context:
        try:
            rewrite_response = llm_completion(
                model=model,
                prompt=build_query_rewrite_prompt(question, history_context),
                raise_on_error=True,
                request_options=retrieval_request_options,
                trace_hook=trace_hook,
                trace_label="query_rewrite",
                stats_hook=stats_hook,
            )
            rewrite_payload = extract_json(rewrite_response)
            candidate = rewrite_payload.get("rewritten_query") if isinstance(rewrite_payload, dict) else None
            if isinstance(candidate, str) and candidate.strip():
                rewritten_query = candidate.strip()
                retrieval_query = rewritten_query
                rewrite_applied = retrieval_query != question
        except Exception as exc:
            if is_fatal_llm_model_error(exc):
                raise
            retrieval_query = question

    selected_nodes = choose_relevant_nodes(
        structure,
        retrieval_query,
        model,
        request_options=retrieval_request_options,
        trace_hook=trace_hook,
        stats_hook=stats_hook,
        top_k=top_k,
        selection_mode=selection_mode,
    )
    context = build_answer_context(
        selected_nodes,
        pdf_path,
        model,
        max_context_pages=int(max_context_pages) if max_context_pages is not None else None,
        max_context_tokens=int(max_context_tokens) if max_context_tokens is not None else None,
    )
    retrieve_ms = int((time.perf_counter() - retrieve_started) * 1000)

    answer_started = time.perf_counter()
    answer = llm_completion(
        model=model,
        prompt=build_generation_prompt(
            question,
            selected_nodes,
            context,
            system_prompt=system_prompt,
            history_context=history_context,
        ),
        raise_on_error=True,
        request_options=generation_request_options,
        trace_hook=trace_hook,
        trace_label="final_answer",
        stats_hook=stats_hook,
    ).strip()
    answer_ms = int((time.perf_counter() - answer_started) * 1000)
    total_ms = int((time.perf_counter() - started) * 1000)
    citations = build_citations(selected_nodes)
    execution_context = {
        "history": {
            "used": bool(history_context),
            "messages_used": len(prepared_history_messages),
            "history_turns_used": len([m for m in prepared_history_messages if m.get("role") == "user"]),
            "history_token_estimate": history_token_estimate,
            "query_rewrite_with_history": query_rewrite_with_history,
            "include_history": include_history,
        },
        "retrieval": {
            "query": retrieval_query,
            "rewritten_query": rewritten_query,
            "rewrite_applied": rewrite_applied,
            "top_k": top_k,
            "selection_mode": selection_mode,
            "max_context_pages": int(max_context_pages) if max_context_pages is not None else None,
            "max_context_tokens": int(max_context_tokens) if max_context_tokens is not None else None,
        },
        "generation": {
            "temperature": generation_request_options.get("temperature"),
        },
    }
    return answer, selected_nodes, {
        "retrieve_ms": retrieve_ms,
        "answer_ms": answer_ms,
        "total_ms": total_ms,
        "input_tokens": usage_totals["input_tokens"],
        "output_tokens": usage_totals["output_tokens"],
        "total_tokens": usage_totals["total_tokens"],
        "manual_count": 1,
        "selected_section_count": len(selected_nodes),
        "successful_llm_calls": usage_totals["successful_llm_calls"],
        "citations_count": len(citations),
    }, execution_context


async def parse_pdf_to_structure_async(pdf_path: str, model: str) -> dict:
    return await asyncio.to_thread(parse_pdf_to_structure, pdf_path, model)


async def answer_question_against_structure_async(
    *,
    pdf_path: str,
    structure: list[dict],
    question: str,
    model: str,
    system_prompt: str | None = None,
    request_options: dict | None = None,
    retrieval_options: dict | None = None,
    generation_options: dict | None = None,
    conversation_options: dict | None = None,
    history_messages: list[dict] | None = None,
    trace_hook=None,
) -> tuple[str, list[dict], dict, dict]:
    ensure_run_reuse_cache()

    return await asyncio.to_thread(
        answer_question_against_structure,
        pdf_path=pdf_path,
        structure=structure,
        question=question,
        model=model,
        system_prompt=system_prompt,
        request_options=request_options,
        retrieval_options=retrieval_options,
        generation_options=generation_options,
        conversation_options=conversation_options,
        history_messages=history_messages,
        trace_hook=trace_hook,
    )


def load_structure_file(path: str) -> list[dict]:
    ensure_run_reuse_cache()
    data = read_json_artifact(path)
    return data["structure"] if isinstance(data, dict) and "structure" in data else data
