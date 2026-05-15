#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import get_settings
from app.services.node_embedding_service import (
    EsNodeDenseSearchBackend,
    ExactScanNodeDenseSearchBackend,
    NodeEmbeddingArtifactStore,
    embedding_runtime_options,
)
from app.services.provider_service import resolve_embedding_config
from app.services.node_shadow_service import run_node_shadow_replay
from app.services.routing_consumer_service import build_manual_gate_ref, tokenize_routing_text


DEFAULT_DOCUMENT_ID = "1bdd7603-5f14-4471-a7c3-d0e2e8f1f360"
DEFAULT_VERSION_ID = "48ce8816-cf25-47ec-8e30-f8c29d74d713"
DEFAULT_DOCUMENT_LABEL = "operations_manual_v1.pdf"
P0_SAMPLES = [
    {
        "cohort_id": "p0:1",
        "question": "有哪些特殊机场？",
        "kind": "p0_special_airport_list",
        "exact_node_ids": ["0080"],
        "expected_answer_summary": "目前共有5个特殊机场：迪庆/香格里拉、丽江/三义、腾冲/驼峰、大连/周水子、昭通。",
    },
    {
        "cohort_id": "p0:2",
        "question": "厦门高崎机场有什么特殊规定？",
        "kind": "p0_negative_special_airport",
        "exact_node_ids": ["0080"],
        "expected_answer_summary": "负相关问题；手册摘录未包含厦门高崎机场特殊规定，需引用特殊机场清单说明未列入。",
    },
    {
        "cohort_id": "p0:3",
        "question": "航班能否在雨夜降落高崎机场？",
        "kind": "p0_expansion_rain_night_landing",
        "exact_node_ids": ["0080", "0184", "0075", "0135", "0078"],
        "expected_answer_summary": "扩选问题；高崎未列入特殊机场，需同时覆盖低能见、着陆最低标准、湿/污染跑道和侧风限制。",
    },
]
SPECIAL_AIRPORT_PATTERN = re.compile(r"特殊机场|特殊航路|特别管控机场|高崎|厦门")
ASCII_TOKEN_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._/-]*$", re.IGNORECASE)
CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def _json_load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 6)


def _avg(values: Sequence[float | int | None]) -> float | None:
    normalized = [float(value) for value in values if value is not None]
    if not normalized:
        return None
    return round(mean(normalized), 6)


def _percentile(values: Sequence[float | int | None], percentile: float) -> float | None:
    normalized = sorted(float(value) for value in values if value is not None)
    if not normalized:
        return None
    if len(normalized) == 1:
        return round(normalized[0], 3)
    rank = (len(normalized) - 1) * max(0.0, min(percentile, 100.0)) / 100.0
    lower = int(rank)
    upper = min(lower + 1, len(normalized) - 1)
    fraction = rank - lower
    value = normalized[lower] + (normalized[upper] - normalized[lower]) * fraction
    return round(value, 3)


def _latency_summary(values: Sequence[float | int | None]) -> dict[str, Any]:
    normalized = [float(value) for value in values if value is not None]
    return {
        "count": len(normalized),
        "p50_ms": _percentile(normalized, 50),
        "p95_ms": _percentile(normalized, 95),
        "max_ms": round(max(normalized), 3) if normalized else None,
        "avg_ms": _avg(normalized),
    }


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _title_key(value: Any) -> str:
    return re.sub(r"\s+", "", _normalize_text(value)).lower()


def _normalize_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _page_overlap(a_start: Any, a_end: Any, b_start: Any, b_end: Any) -> int:
    left = _normalize_int(a_start)
    right = _normalize_int(a_end)
    other_left = _normalize_int(b_start)
    other_right = _normalize_int(b_end)
    if left is None or right is None or other_left is None or other_right is None:
        return 0
    start = max(left, other_left)
    end = min(right, other_right)
    return max(0, end - start + 1)


def _page_span(node: Mapping[str, Any]) -> int:
    start = _normalize_int(node.get("page_start"))
    end = _normalize_int(node.get("page_end"))
    if start is None or end is None or end < start:
        return 1_000_000
    return end - start + 1


def _build_breadcrumb(manual_label: str, ancestors: Sequence[str]) -> str:
    parts = [manual_label] if manual_label else []
    parts.extend(part for part in ancestors if part)
    return " / ".join(parts)


def _flatten_structure_nodes(
    nodes: Sequence[Mapping[str, Any]],
    *,
    manual_ref: Mapping[str, Any],
    parent_node_id: str | None = None,
    depth: int = 0,
    ancestors: Sequence[str] | None = None,
    output: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if output is None:
        output = []
    manual_key = manual_ref["manual_key"]
    manual_label = _normalize_text(manual_ref.get("document_label"))
    prior_titles = list(ancestors or [])
    for index, node in enumerate(nodes):
        if not isinstance(node, Mapping):
            continue
        node_id = _normalize_text(node.get("node_id"))
        title = _normalize_text(node.get("title"))
        if not node_id:
            continue
        current_titles = prior_titles + ([title] if title else [])
        page_start = _normalize_int(node.get("start_index"))
        page_end = _normalize_int(node.get("end_index"))
        route_doc = {
            "manual_key": manual_key,
            "document_id": manual_ref.get("document_id"),
            "version_id": manual_ref.get("version_id"),
            "document_label": manual_ref.get("document_label"),
            "version_label": manual_ref.get("version_label"),
            "display_name": manual_ref.get("display_name"),
            "source_filename": manual_ref.get("source_filename"),
            "routing_index_status": manual_ref.get("routing_index_status"),
            "routing_index_path_present": bool(manual_ref.get("routing_index_path")),
            "routing_index_version": manual_ref.get("routing_index_version"),
            "node_id": node_id,
            "node_key": f"{manual_key}:{node_id}",
            "parent_node_id": parent_node_id,
            "title": title,
            "breadcrumb": _build_breadcrumb(manual_label, current_titles),
            "page_start": page_start,
            "page_end": page_end,
            "page_span": None if page_start is None or page_end is None else max(0, page_end - page_start + 1),
            "depth": depth,
            "route_summary": node.get("summary"),
            "contrastive_summary": None,
            "aliases": None,
            "keywords": None,
            "manual_profile_text": None,
            "corpus_source": "structure_json",
            "inventory_source": "structure_json",
            "original_index": len(output) + index,
        }
        output.append(route_doc)
        children = node.get("nodes")
        if isinstance(children, list) and children:
            _flatten_structure_nodes(
                children,
                manual_ref=manual_ref,
                parent_node_id=node_id,
                depth=depth + 1,
                ancestors=current_titles,
                output=output,
            )
    for original_index, route_doc in enumerate(output):
        route_doc["original_index"] = original_index
    return output


def build_node_corpus_from_structure(
    structure_payload: Mapping[str, Any],
    manual_ref: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    structure_nodes = structure_payload.get("structure") if isinstance(structure_payload, Mapping) else None
    if not isinstance(structure_nodes, list):
        raise ValueError("structure_json_missing_structure_array")
    nodes = _flatten_structure_nodes(structure_nodes, manual_ref=manual_ref)
    source_doc_name = _normalize_text(structure_payload.get("doc_name")) if isinstance(structure_payload, Mapping) else ""
    corpus = {
        "manual_key": manual_ref["manual_key"],
        "manual": dict(manual_ref),
        "corpus_source": "structure_json",
        "nodes": nodes,
        "node_count": len(nodes),
        "fallback_reason": "document_routing_nodes_and_routing_index_json_not_used_for_real_manual_cohort",
        "warning": None,
    }
    return corpus, {
        "doc_name": source_doc_name,
        "node_count": len(nodes),
        "summary_count": sum(1 for node in nodes if _normalize_text(node.get("route_summary"))),
        "top_level_count": sum(1 for node in nodes if int(node.get("depth") or 0) == 0),
        "leaf_count": sum(1 for node in nodes if not any(other.get("parent_node_id") == node.get("node_id") for other in nodes)),
    }


def _children_by_parent(nodes: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    children: dict[str, list[str]] = {}
    for node in nodes:
        parent = _normalize_text(node.get("parent_node_id"))
        node_id = _normalize_text(node.get("node_id"))
        if parent and node_id:
            children.setdefault(parent, []).append(node_id)
    return children


def _ancestors(node_id: str, node_by_id: Mapping[str, Mapping[str, Any]]) -> list[str]:
    result: list[str] = []
    current = node_by_id.get(node_id)
    seen: set[str] = set()
    while current:
        parent = _normalize_text(current.get("parent_node_id"))
        if not parent or parent in seen:
            break
        result.append(parent)
        seen.add(parent)
        current = node_by_id.get(parent)
    return result


def _descendants(node_id: str, children: Mapping[str, Sequence[str]]) -> list[str]:
    result: list[str] = []
    stack = list(children.get(node_id) or [])
    seen: set[str] = set()
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        result.append(current)
        stack.extend(children.get(current) or [])
    return result


def _node_index(nodes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    node_by_id = {
        _normalize_text(node.get("node_id")): node
        for node in nodes
        if _normalize_text(node.get("node_id"))
    }
    children = _children_by_parent(nodes)
    title_index: dict[str, list[Mapping[str, Any]]] = {}
    for node in nodes:
        title_index.setdefault(_title_key(node.get("title")), []).append(node)
    relaxed_by_node_id = {
        node_id: {node_id, *_ancestors(node_id, node_by_id), *_descendants(node_id, children)}
        for node_id in node_by_id
    }
    return {
        "node_by_id": node_by_id,
        "children_by_parent": children,
        "title_index": title_index,
        "relaxed_by_node_id": relaxed_by_node_id,
    }


def _page_candidate_ids(question: Mapping[str, Any], nodes: Sequence[Mapping[str, Any]], *, limit: int = 8) -> list[str]:
    candidates = []
    for node in nodes:
        overlap = _page_overlap(question.get("page_start"), question.get("page_end"), node.get("page_start"), node.get("page_end"))
        if overlap <= 0:
            continue
        candidates.append((overlap, int(node.get("depth") or 0), -_page_span(node), _normalize_text(node.get("node_id"))))
    candidates.sort(reverse=True)
    return [node_id for _overlap, _depth, _span, node_id in candidates[:limit] if node_id]


def _resolve_question_gold(
    question: Mapping[str, Any],
    *,
    nodes: Sequence[Mapping[str, Any]],
    title_index: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    leaf_title = _normalize_text(question.get("leaf_title"))
    title_matches = list(title_index.get(_title_key(leaf_title), []))
    page_start = question.get("page_start")
    page_end = question.get("page_end")
    source = "unresolved"
    exact_nodes: list[Mapping[str, Any]] = []
    if title_matches:
        exact_page = [
            node
            for node in title_matches
            if _normalize_int(node.get("page_start")) == _normalize_int(page_start)
            and _normalize_int(node.get("page_end")) == _normalize_int(page_end)
        ]
        if exact_page:
            exact_nodes = exact_page
            source = "leaf_title_page_exact"
        else:
            overlapping = [
                node
                for node in title_matches
                if _page_overlap(page_start, page_end, node.get("page_start"), node.get("page_end")) > 0
            ]
            if overlapping:
                exact_nodes = overlapping
                source = "leaf_title_page_overlap"
            else:
                exact_nodes = title_matches
                source = "leaf_title_only"
    if not exact_nodes:
        containing = [
            node
            for node in nodes
            if _normalize_int(node.get("page_start")) is not None
            and _normalize_int(node.get("page_end")) is not None
            and _normalize_int(page_start) is not None
            and _normalize_int(page_end) is not None
            and int(node["page_start"]) <= int(page_start)
            and int(node["page_end"]) >= int(page_end)
        ]
        if containing:
            max_depth = max(int(node.get("depth") or 0) for node in containing)
            exact_nodes = [node for node in containing if int(node.get("depth") or 0) == max_depth]
            source = "page_span_deepest_fallback"
    if not exact_nodes:
        page_candidates = _page_candidate_ids(question, nodes, limit=1)
        exact_nodes = [node for node in nodes if node.get("node_id") in page_candidates]
        source = "page_overlap_best_fallback" if exact_nodes else "unresolved"
    exact_node_ids = sorted({_normalize_text(node.get("node_id")) for node in exact_nodes if _normalize_text(node.get("node_id"))})
    return {
        "exact_node_ids": exact_node_ids,
        "gold_source": source,
        "leaf_candidate_node_ids": _page_candidate_ids(question, nodes),
        "leaf_title": leaf_title,
        "page_start": _normalize_int(page_start),
        "page_end": _normalize_int(page_end),
    }


def _is_special_airport_sample(sample: Mapping[str, Any]) -> bool:
    text_value = " ".join(
        _normalize_text(sample.get(key))
        for key in ("question", "leaf_title", "leaf_path", "reference_answer", "kind")
    )
    return bool(SPECIAL_AIRPORT_PATTERN.search(text_value)) or str(sample.get("cohort_id", "")).startswith("p0:")


def build_real_manual_cohort(
    questions: Sequence[Mapping[str, Any]],
    *,
    nodes: Sequence[Mapping[str, Any]],
    node_index: Mapping[str, Any],
    document_id: str,
    version_id: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    title_index = node_index["title_index"]
    samples: list[dict[str, Any]] = []
    gold_source_counts: Counter[str] = Counter()
    for index, item in enumerate(questions):
        if not isinstance(item, Mapping):
            continue
        gold = _resolve_question_gold(item, nodes=nodes, title_index=title_index)
        gold_source_counts[str(gold.get("gold_source"))] += 1
        sample = {
            "cohort_id": f"questions:{item.get('id', index + 1)}",
            "source": "questions_json",
            "question_id": item.get("id"),
            "batch": item.get("batch"),
            "question": item.get("question"),
            "reference_answer": item.get("reference_answer"),
            "chapter_title": item.get("chapter_title"),
            "leaf_title": item.get("leaf_title"),
            "leaf_path": item.get("leaf_path"),
            "page_start": item.get("page_start"),
            "page_end": item.get("page_end"),
            "kind": item.get("kind"),
            "candidate_score": item.get("candidate_score"),
            "target_document_id": document_id,
            "target_version_id": version_id,
            "gold": gold,
            "answer_correctness_review": "not_evaluated_retrieval_shadow_only",
        }
        sample["tags"] = ["special_airport"] if _is_special_airport_sample(sample) else []
        samples.append(sample)
    for p0 in P0_SAMPLES:
        exact_node_ids = [node_id for node_id in p0["exact_node_ids"] if node_id in node_index["node_by_id"]]
        gold_source_counts["manual_p0_citation_gold"] += 1
        sample = {
            "cohort_id": p0["cohort_id"],
            "source": "p0_manual_gold",
            "question_id": p0["cohort_id"],
            "question": p0["question"],
            "reference_answer": p0["expected_answer_summary"],
            "chapter_title": None,
            "leaf_title": None,
            "leaf_path": None,
            "page_start": None,
            "page_end": None,
            "kind": p0["kind"],
            "candidate_score": None,
            "target_document_id": document_id,
            "target_version_id": version_id,
            "gold": {
                "exact_node_ids": exact_node_ids,
                "gold_source": "manual_p0_citation_gold",
                "leaf_candidate_node_ids": exact_node_ids,
                "leaf_title": None,
                "page_start": None,
                "page_end": None,
            },
            "answer_correctness_review": "manual_review_placeholder_p0_answer_known",
            "tags": ["special_airport", "p0"],
        }
        samples.append(sample)
    summary = {
        "questions_json_count": len([item for item in questions if isinstance(item, Mapping)]),
        "p0_count": len(P0_SAMPLES),
        "sample_count": len(samples),
        "gold_source_counts": dict(gold_source_counts),
        "unresolved_gold_count": sum(1 for sample in samples if not sample["gold"].get("exact_node_ids")),
        "special_airport_count": sum(1 for sample in samples if "special_airport" in sample.get("tags", [])),
        "final_citation_gold_present": False,
        "gold_policy": {
            "exact": "questions.json uses resolved leaf section/node gold from leaf_title and page span; P0 uses user-provided citation node ids.",
            "relaxed": "a gold node is matched if top-k contains that node, one of its ancestors, or one of its descendants.",
            "leaf_candidate": "page-overlap candidates are retained for diagnostics but are not final citation gold.",
            "answer_correctness": "not scored automatically; manual-review placeholder only.",
        },
    }
    return samples, summary


def _masked_database_url(url: str) -> str:
    if "://" not in url or "@" not in url:
        return url
    scheme, rest = url.split("://", 1)
    credentials, host = rest.split("@", 1)
    user = credentials.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}"


def _masked_embedding_config(config: Mapping[str, Any]) -> dict[str, Any]:
    return {key: ("***" if key == "api_key" and value else value) for key, value in config.items()}


def _load_original_retrieval_latencies(path: str | None) -> dict[str, Any]:
    if not path:
        return {"available": False, "reason": "raw_results_path_not_configured", "by_question_id": {}, "summary": {}}
    raw_path = Path(path)
    if not raw_path.exists():
        return {"available": False, "reason": "raw_results_missing", "path": str(raw_path), "by_question_id": {}, "summary": {}}
    payload = _json_load(raw_path)
    if not isinstance(payload, list):
        return {"available": False, "reason": "raw_results_not_array", "path": str(raw_path), "by_question_id": {}, "summary": {}}
    by_question_id: dict[str, dict[str, Any]] = {}
    retrieve_values: list[int] = []
    total_values: list[int] = []
    answer_values: list[int] = []
    status_counts: Counter[str] = Counter()
    rerank_latency_values: list[int] = []
    for item in payload:
        if not isinstance(item, Mapping):
            continue
        question_id = _normalize_text(item.get("question_id"))
        raw_response = item.get("raw_response") if isinstance(item.get("raw_response"), Mapping) else {}
        metrics = raw_response.get("metrics") if isinstance(raw_response.get("metrics"), Mapping) else {}
        retrieve_ms = _normalize_int(metrics.get("retrieve_ms"))
        total_ms = _normalize_int(metrics.get("total_ms") or item.get("latency_ms"))
        answer_ms = _normalize_int(metrics.get("answer_ms"))
        rerank_ms = _normalize_int(metrics.get("rerank_ms") or metrics.get("rerank_latency_ms"))
        status = _normalize_text(item.get("error") or raw_response.get("status") or item.get("status_code") or "unknown")
        status_counts[status] += 1
        if retrieve_ms is not None:
            retrieve_values.append(retrieve_ms)
        if total_ms is not None:
            total_values.append(total_ms)
        if answer_ms is not None:
            answer_values.append(answer_ms)
        if rerank_ms is not None:
            rerank_latency_values.append(rerank_ms)
        if question_id:
            by_question_id[question_id] = {
                "question_id": question_id,
                "retrieve_ms": retrieve_ms,
                "total_ms": total_ms,
                "answer_ms": answer_ms,
                "rerank_ms": rerank_ms,
                "status": status,
                "manual_count": metrics.get("manual_count"),
                "selected_section_count": metrics.get("selected_section_count"),
                "documents_considered": metrics.get("documents_considered"),
                "documents_with_hits": metrics.get("documents_with_hits"),
            }
    return {
        "available": bool(by_question_id),
        "path": str(raw_path),
        "sample_count": len(by_question_id),
        "status_counts": dict(status_counts),
        "by_question_id": by_question_id,
        "summary": {
            "retrieve_ms": _latency_summary(retrieve_values),
            "answer_ms": _latency_summary(answer_values),
            "total_ms": _latency_summary(total_values),
            "rerank_ms": (
                _latency_summary(rerank_latency_values)
                if rerank_latency_values
                else {"available": False, "reason": "raw_results_has_no_rerank_latency_fields"}
            ),
        },
    }


def _probe_artifact_embedding_latency(
    args: argparse.Namespace,
    corpus: Mapping[str, Any],
) -> dict[str, Any]:
    if args.dense_source in {"sparse", "off"}:
        return {"available": False, "reason": "dense_source_disabled"}
    started = time.perf_counter()
    embedding_config = dict(resolve_embedding_config(provider_config={}, embedding_mode=args.embedding_mode))
    try:
        result = NodeEmbeddingArtifactStore().get_or_build(
            manual=dict(corpus.get("manual") or {}),
            nodes=[dict(node) for node in corpus.get("nodes") or [] if isinstance(node, Mapping)],
            embedding_config=embedding_config,
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        return {
            "available": result.available,
            "elapsed_ms": elapsed_ms,
            "embedding_config": _masked_embedding_config(embedding_config),
            "result": result.summary(),
        }
    except Exception as exc:
        return {
            "available": False,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "embedding_config": _masked_embedding_config(embedding_config),
            "reason": f"artifact_probe_error:{type(exc).__name__}",
        }


def _engine() -> Engine:
    settings = get_settings()
    connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    return create_engine(settings.database_url, future=True, connect_args=connect_args)


def _manual_ref_from_database(
    engine: Engine,
    *,
    document_id: str,
    version_id: str,
    document_label: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    query = text(
        """
        SELECT d.id AS document_id,
               v.id AS version_id,
               d.tenant_id AS tenant_id,
               d.display_name AS document_label,
               d.display_name AS display_name,
               d.source_filename AS source_filename,
               v.version_no AS version_no,
               v.parse_status AS parse_status,
               v.storage_path AS storage_path,
               v.parsed_structure_path AS parsed_structure_path,
               v.routing_index_status AS routing_index_status,
               v.routing_index_path AS routing_index_path,
               v.routing_index_version AS routing_index_version,
               COUNT(rn.id) AS routing_node_count
        FROM document_versions v
        JOIN documents d ON d.id = v.document_id
        LEFT JOIN document_routing_nodes rn ON rn.version_id = v.id
        WHERE d.id = :document_id AND v.id = :version_id
        GROUP BY d.id, v.id, d.tenant_id, d.display_name, d.source_filename,
                 v.version_no, v.parse_status, v.storage_path, v.parsed_structure_path,
                 v.routing_index_status, v.routing_index_path, v.routing_index_version
        """
    )
    row: Mapping[str, Any] | None = None
    try:
        with engine.connect() as conn:
            row = conn.execute(query, {"document_id": document_id, "version_id": version_id}).mappings().first()
    except Exception:
        row = None
    if row is None:
        manual_ref = build_manual_gate_ref(
            document_id=document_id,
            version_id=version_id,
            document_label=document_label,
            version_label="v1",
            display_name=document_label,
            source_filename=document_label,
            storage_path=None,
            parsed_structure_path=None,
            routing_index_status=None,
            routing_index_path=None,
            routing_index_version="v1",
        )
        manual_ref["tenant_id"] = "tenant_default"
        return manual_ref, {"found_in_database": False, "routing_node_count": None}
    manual_ref = build_manual_gate_ref(
        document_id=str(row.get("document_id") or document_id),
        version_id=str(row.get("version_id") or version_id),
        document_label=row.get("document_label") or document_label,
        version_label=f"v{row.get('version_no')}" if row.get("version_no") is not None else "v1",
        display_name=row.get("display_name") or document_label,
        source_filename=row.get("source_filename") or document_label,
        storage_path=row.get("storage_path"),
        parsed_structure_path=row.get("parsed_structure_path"),
        routing_index_status=row.get("routing_index_status"),
        routing_index_path=row.get("routing_index_path"),
        routing_index_version=row.get("routing_index_version") or "v1",
    )
    manual_ref["tenant_id"] = str(row.get("tenant_id") or "tenant_default")
    return manual_ref, {
        "found_in_database": True,
        "parse_status": row.get("parse_status"),
        "routing_index_status": row.get("routing_index_status"),
        "routing_index_path_present": bool(row.get("routing_index_path")),
        "parsed_structure_path_present": bool(row.get("parsed_structure_path")),
        "routing_node_count": int(row.get("routing_node_count") or 0),
    }


def _dense_backend(args: argparse.Namespace):
    if args.dense_source in {"sparse", "off"}:
        return None
    if args.dense_source == "artifact-exact":
        return ExactScanNodeDenseSearchBackend()
    if args.dense_source == "es-shadow":
        return EsNodeDenseSearchBackend()
    return None


def _top_node_summary(nodes: Sequence[Mapping[str, Any]], limit: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for rank, node in enumerate(list(nodes)[:limit], start=1):
        result.append(
            {
                "rank": rank,
                "node_id": node.get("node_id"),
                "title": node.get("title"),
                "page_start": node.get("page_start"),
                "page_end": node.get("page_end"),
                "lexical_rank": node.get("lexical_rank"),
                "hybrid_rank": node.get("hybrid_rank"),
                "lexical_score": node.get("lexical_score"),
                "dense_score": node.get("dense_score"),
                "hybrid_score": node.get("hybrid_score"),
                "zero_hit": node.get("zero_hit"),
            }
        )
    return result


def _selected_node_ids(nodes: Sequence[Mapping[str, Any]], top_k: int) -> set[str]:
    return {
        _normalize_text(node.get("node_id"))
        for node in list(nodes)[:top_k]
        if _normalize_text(node.get("node_id"))
    }


def _exact_recall(selected: set[str], gold_ids: Sequence[str]) -> float | None:
    gold = {node_id for node_id in gold_ids if node_id}
    if not gold:
        return None
    return _rate(len(selected & gold), len(gold))


def _relaxed_recall(
    selected: set[str],
    gold_ids: Sequence[str],
    relaxed_by_node_id: Mapping[str, set[str]],
) -> float | None:
    gold = [node_id for node_id in gold_ids if node_id]
    if not gold:
        return None
    matched = 0
    for node_id in gold:
        relaxed = relaxed_by_node_id.get(node_id) or {node_id}
        if selected & relaxed:
            matched += 1
    return _rate(matched, len(gold))


def _document_hit(nodes: Sequence[Mapping[str, Any]], top_k: int, document_id: str, version_id: str) -> float:
    for node in list(nodes)[:top_k]:
        if node.get("document_id") == document_id and node.get("version_id") == version_id:
            return 1.0
    return 0.0


def _query_language_stats(question: str, gold_ids: Sequence[str], node_by_id: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    tokens = tokenize_routing_text(question)
    ascii_tokens = [token for token in tokens if ASCII_TOKEN_PATTERN.match(token)]
    cjk_tokens = [token for token in tokens if CJK_PATTERN.search(token)]
    gold_text = " ".join(
        " ".join(
            _normalize_text(node_by_id[node_id].get(key))
            for key in ("title", "breadcrumb", "route_summary")
        )
        for node_id in gold_ids
        if node_id in node_by_id
    )
    gold_tokens = set(tokenize_routing_text(gold_text))
    overlap = _rate(len(set(tokens) & gold_tokens), len(set(tokens))) if tokens else None
    return {
        "query_token_count": len(tokens),
        "query_cjk_token_count": len(cjk_tokens),
        "query_ascii_token_count": len(ascii_tokens),
        "query_ascii_tokens": ascii_tokens,
        "query_gold_token_overlap": overlap,
    }


def _jaccard(left: set[str], right: set[str]) -> float | None:
    if not left and not right:
        return None
    return round(len(left & right) / len(left | right), 6)


def _evaluate_sample(
    sample: Mapping[str, Any],
    report: Mapping[str, Any],
    *,
    top_ks: Sequence[int],
    node_index: Mapping[str, Any],
    document_id: str,
    version_id: str,
    fast_search_wall_ms: float | None = None,
    original_retrieval_latency: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    gold_ids = list((sample.get("gold") or {}).get("exact_node_ids") or [])
    relaxed_by_node_id = node_index["relaxed_by_node_id"]
    lexical_nodes = list(report.get("lexical_top_nodes") or [])
    hybrid_nodes = list(report.get("hybrid_top_nodes") or [])
    metrics: dict[str, Any] = {"lexical": {}, "hybrid": {}}
    for mode, nodes in (("lexical", lexical_nodes), ("hybrid", hybrid_nodes)):
        for top_k in top_ks:
            selected = _selected_node_ids(nodes, top_k)
            metrics[mode][str(top_k)] = {
                "exact_recall": _exact_recall(selected, gold_ids),
                "relaxed_recall": _relaxed_recall(selected, gold_ids, relaxed_by_node_id),
                "document_hit": _document_hit(nodes, top_k, document_id, version_id),
            }
    language = _query_language_stats(str(sample.get("question") or ""), gold_ids, node_index["node_by_id"])
    top8_lexical = _selected_node_ids(lexical_nodes, min(8, max(top_ks)))
    top8_hybrid = _selected_node_ids(hybrid_nodes, min(8, max(top_ks)))
    zero_hit = ((report.get("metrics") or {}).get("zero_hit_rate") or {}).get("value")
    node_score_ms = (((report.get("metrics") or {}).get("latency_delta") or {}).get("node_shadow_latency_ms"))
    original_latency = dict(original_retrieval_latency or {})
    original_retrieve_ms = original_latency.get("retrieve_ms")
    speedup_ratio = None
    if original_retrieve_ms is not None and fast_search_wall_ms is not None and fast_search_wall_ms > 0:
        speedup_ratio = round(float(original_retrieve_ms) / float(fast_search_wall_ms), 6)
    return {
        "cohort_id": sample.get("cohort_id"),
        "source": sample.get("source"),
        "question_id": sample.get("question_id"),
        "kind": sample.get("kind"),
        "question": sample.get("question"),
        "leaf_title": sample.get("leaf_title"),
        "leaf_path": sample.get("leaf_path"),
        "page_start": sample.get("page_start"),
        "page_end": sample.get("page_end"),
        "tags": list(sample.get("tags") or []),
        "gold": sample.get("gold"),
        "answer_correctness_review": sample.get("answer_correctness_review"),
        "metrics": metrics,
        "zero_hit_rate": zero_hit,
        "latency": {
            "fast_search_wall_ms": fast_search_wall_ms,
            "node_score_ms": node_score_ms,
            "original_retrieval_ms": original_retrieve_ms,
            "original_total_ms": original_latency.get("total_ms"),
            "original_answer_ms": original_latency.get("answer_ms"),
            "original_rerank_ms": original_latency.get("rerank_ms"),
            "speedup_vs_original_retrieve": speedup_ratio,
            "original_retrieval_status": original_latency.get("status"),
        },
        "language": language,
        "top8_lex_hyb_jaccard": _jaccard(top8_lexical, top8_hybrid),
        "dense": {
            "enabled": (report.get("dense") or {}).get("enabled"),
            "fallback_reason": (report.get("dense") or {}).get("fallback_reason"),
            "dense_source": (report.get("dense") or {}).get("dense_source"),
            "requested_dense_source": (report.get("dense") or {}).get("requested_dense_source"),
            "query_embedding_dimensions": (report.get("dense") or {}).get("query_embedding_dimensions"),
        },
        "hybrid_top_nodes": _top_node_summary(hybrid_nodes, max(top_ks)),
        "lexical_top_nodes": _top_node_summary(lexical_nodes, max(top_ks)),
    }


def _metric_values(rows: Sequence[Mapping[str, Any]], mode: str, top_k: int, metric: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = (((row.get("metrics") or {}).get(mode) or {}).get(str(top_k)) or {}).get(metric)
        if value is not None:
            values.append(float(value))
    return values


def _latency_values(rows: Sequence[Mapping[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = (row.get("latency") or {}).get(key)
        if value is not None:
            values.append(float(value))
    return values


def _hit_rate(values: Sequence[float], *, full: bool = False) -> float | None:
    if not values:
        return None
    if full:
        return _rate(sum(1 for value in values if value >= 1.0), len(values))
    return _rate(sum(1 for value in values if value > 0), len(values))


def _accuracy_latency_summary(rows: Sequence[Mapping[str, Any]], *, top_k: int = 10) -> dict[str, Any]:
    exact_values = _metric_values(rows, "hybrid", top_k, "exact_recall")
    relaxed_values = _metric_values(rows, "hybrid", top_k, "relaxed_recall")
    document_values = _metric_values(rows, "hybrid", top_k, "document_hit")
    fast_values = _latency_values(rows, "fast_search_wall_ms")
    node_score_values = _latency_values(rows, "node_score_ms")
    original_values = _latency_values(rows, "original_retrieval_ms")
    speedup_values = _latency_values(rows, "speedup_vs_original_retrieve")
    return {
        "sample_count": len(rows),
        f"hybrid_hit_rate@{top_k}": _hit_rate(exact_values),
        f"hybrid_full_hit_rate@{top_k}": _hit_rate(exact_values, full=True),
        f"hybrid_exact_recall@{top_k}": _avg(exact_values),
        f"hybrid_relaxed_recall@{top_k}": _avg(relaxed_values),
        f"document_hit_rate@{top_k}": _avg(document_values),
        "fast_search_wall_ms": _latency_summary(fast_values),
        "node_score_ms": _latency_summary(node_score_values),
        "original_retrieval_ms": _latency_summary(original_values),
        "speedup_vs_original_retrieve": {
            **_latency_summary(speedup_values),
            "paired_sample_count": len(speedup_values),
            "estimate_basis": "per-sample raw_results retrieve_ms divided by measured fast_search wall time",
        },
    }


def _query_type(row: Mapping[str, Any]) -> str:
    source = _normalize_text(row.get("source"))
    if source == "p0_manual_gold":
        return _normalize_text(row.get("kind")) or "p0"
    return _normalize_text(row.get("kind")) or "unknown"


def _summarize_by_query_type(rows: Sequence[Mapping[str, Any]], *, top_k: int = 10) -> dict[str, Any]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(_query_type(row), []).append(row)
    return {
        query_type: _accuracy_latency_summary(group_rows, top_k=top_k)
        for query_type, group_rows in sorted(grouped.items())
    }


def _summarize_rows(rows: Sequence[Mapping[str, Any]], top_ks: Sequence[int]) -> dict[str, Any]:
    overall: dict[str, Any] = {
        "sample_count": len(rows),
        "zero_hit_rate": _avg(row.get("zero_hit_rate") for row in rows),
    }
    for top_k in top_ks:
        for mode in ("lexical", "hybrid"):
            overall[f"{mode}_exact@{top_k}"] = _avg(_metric_values(rows, mode, top_k, "exact_recall"))
            overall[f"{mode}_relaxed@{top_k}"] = _avg(_metric_values(rows, mode, top_k, "relaxed_recall"))
            overall[f"{mode}_document@{top_k}"] = _avg(_metric_values(rows, mode, top_k, "document_hit"))
        overall[f"dense_vs_lexical_exact_gain@{top_k}"] = (
            None
            if overall[f"hybrid_exact@{top_k}"] is None or overall[f"lexical_exact@{top_k}"] is None
            else round(overall[f"hybrid_exact@{top_k}"] - overall[f"lexical_exact@{top_k}"], 6)
        )
        overall[f"dense_vs_lexical_relaxed_gain@{top_k}"] = (
            None
            if overall[f"hybrid_relaxed@{top_k}"] is None or overall[f"lexical_relaxed@{top_k}"] is None
            else round(overall[f"hybrid_relaxed@{top_k}"] - overall[f"lexical_relaxed@{top_k}"], 6)
        )
    language = {
        "avg_query_token_count": _avg((row.get("language") or {}).get("query_token_count") for row in rows),
        "avg_query_cjk_token_count": _avg((row.get("language") or {}).get("query_cjk_token_count") for row in rows),
        "avg_query_ascii_token_count": _avg((row.get("language") or {}).get("query_ascii_token_count") for row in rows),
        "avg_query_gold_token_overlap": _avg((row.get("language") or {}).get("query_gold_token_overlap") for row in rows),
        "avg_top8_lex_hyb_jaccard": _avg(row.get("top8_lex_hyb_jaccard") for row in rows),
        "cjk_only_or_mostly_cjk_count": sum(
            1
            for row in rows
            if int((row.get("language") or {}).get("query_cjk_token_count") or 0)
            >= int((row.get("language") or {}).get("query_ascii_token_count") or 0)
        ),
    }
    default_top_k = 10 if 10 in top_ks else max(top_ks)
    return {
        "overall": overall,
        "language_token_overlap": language,
        "latency": {
            "fast_search_wall_ms": _latency_summary(_latency_values(rows, "fast_search_wall_ms")),
            "node_score_ms": _latency_summary(_latency_values(rows, "node_score_ms")),
            "original_retrieval_ms": _latency_summary(_latency_values(rows, "original_retrieval_ms")),
            "speedup_vs_original_retrieve": {
                **_latency_summary(_latency_values(rows, "speedup_vs_original_retrieve")),
                "paired_sample_count": len(_latency_values(rows, "speedup_vs_original_retrieve")),
            },
        },
        f"accuracy_latency@{default_top_k}": _accuracy_latency_summary(rows, top_k=default_top_k),
        f"by_query_type@{default_top_k}": _summarize_by_query_type(rows, top_k=default_top_k),
    }


def _negative_gain_samples(rows: Sequence[Mapping[str, Any]], *, top_k: int = 8, limit: int = 20) -> list[dict[str, Any]]:
    negative: list[dict[str, Any]] = []
    for row in rows:
        lexical = (((row.get("metrics") or {}).get("lexical") or {}).get(str(top_k)) or {}).get("exact_recall")
        hybrid = (((row.get("metrics") or {}).get("hybrid") or {}).get(str(top_k)) or {}).get("exact_recall")
        if lexical is None or hybrid is None or float(hybrid) >= float(lexical):
            continue
        negative.append(
            {
                "cohort_id": row.get("cohort_id"),
                "kind": row.get("kind"),
                "question": row.get("question"),
                f"lexical_exact@{top_k}": lexical,
                f"hybrid_exact@{top_k}": hybrid,
                "delta": round(float(hybrid) - float(lexical), 6),
                "gold_node_ids": (row.get("gold") or {}).get("exact_node_ids"),
                "hybrid_top_node_ids": [node.get("node_id") for node in row.get("hybrid_top_nodes") or []][:top_k],
                "lexical_top_node_ids": [node.get("node_id") for node in row.get("lexical_top_nodes") or []][:top_k],
            }
        )
    negative.sort(key=lambda item: (item["delta"], str(item.get("cohort_id"))))
    return negative[:limit]


def _failure_samples(rows: Sequence[Mapping[str, Any]], *, top_k: int = 8, limit: int = 20) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for row in rows:
        exact = (((row.get("metrics") or {}).get("hybrid") or {}).get(str(top_k)) or {}).get("exact_recall")
        if exact is None or float(exact) > 0:
            continue
        failures.append(
            {
                "cohort_id": row.get("cohort_id"),
                "kind": row.get("kind"),
                "question": row.get("question"),
                "gold_source": (row.get("gold") or {}).get("gold_source"),
                "gold_node_ids": (row.get("gold") or {}).get("exact_node_ids"),
                "zero_hit_rate": row.get("zero_hit_rate"),
                "query_gold_token_overlap": (row.get("language") or {}).get("query_gold_token_overlap"),
                "hybrid_top_node_ids": [node.get("node_id") for node in row.get("hybrid_top_nodes") or []][:top_k],
            }
        )
    failures.sort(key=lambda item: (-(item.get("zero_hit_rate") or 0), str(item.get("cohort_id"))))
    return failures[:limit]


def _artifact_summary(rows: Sequence[Mapping[str, Any]], raw_reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    dense_enabled_count = sum(1 for row in rows if (row.get("dense") or {}).get("enabled"))
    fallback_counts = Counter(str((row.get("dense") or {}).get("fallback_reason")) for row in rows if (row.get("dense") or {}).get("fallback_reason"))
    artifact_by_key: dict[str, dict[str, Any]] = {}
    status_counts: Counter[str] = Counter()
    for report in raw_reports:
        for artifact in (report.get("dense") or {}).get("artifacts") or []:
            if not isinstance(artifact, Mapping):
                continue
            key = _normalize_text(artifact.get("uri") or artifact.get("object_path") or artifact.get("embedding_spec_id"))
            if not key:
                continue
            artifact_by_key[key] = dict(artifact)
            status_counts[str(artifact.get("artifact_status") or "unknown")] += 1
    return {
        "dense_enabled_count": dense_enabled_count,
        "dense_fallback_counts": dict(fallback_counts),
        "distinct_artifact_count": len(artifact_by_key),
        "artifact_status_occurrences": dict(status_counts),
        "artifacts": list(artifact_by_key.values()),
    }


def _runtime_snapshot(args: argparse.Namespace, manual_truth: Mapping[str, Any], manual_ref: Mapping[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    embedding_options = embedding_runtime_options(settings_obj=settings)
    return {
        "database_mode": settings.database_mode,
        "database_url": _masked_database_url(settings.database_url),
        "storage_backend": settings.storage_backend,
        "minio_endpoint": settings.minio_endpoint,
        "minio_bucket": settings.minio_bucket,
        "system_embedding_enabled": settings.system_embedding_enabled,
        "system_embedding_provider_type": settings.system_embedding_provider_type,
        "system_embedding_model": settings.system_embedding_model,
        "system_embedding_batch_size": embedding_options["batch_size"],
        "system_embedding_timeout_seconds": embedding_options["timeout_seconds"],
        "system_embedding_max_retries": embedding_options["max_retries"],
        "routing_embeddings_build_mode": settings.routing_embeddings_build_mode,
        "routing_node_es_enabled": bool(getattr(settings, "routing_node_es_enabled", False)),
        "manual_ref": dict(manual_ref),
        "manual_truth": dict(manual_truth),
        "cohort_paths": {
            "questions": str(args.questions),
            "structure": str(args.structure),
            "raw_results": str(args.raw_results) if args.raw_results else None,
        },
        "shadow": {
            "dense_source": args.dense_source,
            "embedding_mode": args.embedding_mode,
            "top_ks": args.top_ks,
            "candidate_top_k": args.candidate_top_k,
            "default_node_top_k": 10,
            "benchmark_boundary": {
                "fast_search": "explicit section localization, single fact, definition, numeric, and requirement queries",
                "deepresearch": "cross-section, multi-condition, compliance judgment, and official complete-text evidence expansion",
                "auto_confidence": "design placeholder only; not implemented",
            },
        },
    }


def run_real_manual_eval(args: argparse.Namespace) -> dict[str, Any]:
    questions = _json_load(Path(args.questions))
    if not isinstance(questions, list):
        raise ValueError("questions_json_must_be_array")
    structure_payload = _json_load(Path(args.structure))
    if not isinstance(structure_payload, Mapping):
        raise ValueError("structure_json_must_be_object")

    top_ks = sorted({int(value) for value in args.top_ks})
    max_top_k = max(top_ks)
    engine = _engine()
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)
    try:
        manual_ref, manual_truth = _manual_ref_from_database(
            engine,
            document_id=args.document_id,
            version_id=args.version_id,
            document_label=args.document_label,
        )
        corpus, structure_summary = build_node_corpus_from_structure(structure_payload, manual_ref)
        node_index = _node_index(corpus["nodes"])
        samples, cohort_summary = build_real_manual_cohort(
            questions,
            nodes=corpus["nodes"],
            node_index=node_index,
            document_id=args.document_id,
            version_id=args.version_id,
        )
        if args.limit:
            samples = samples[: args.limit]
            cohort_summary["sample_count_after_limit"] = len(samples)

        original_retrieval = _load_original_retrieval_latencies(args.raw_results)
        original_by_question_id = original_retrieval.get("by_question_id") if isinstance(original_retrieval.get("by_question_id"), dict) else {}
        artifact_embedding_probe = _probe_artifact_embedding_latency(args, corpus)
        dense_backend = _dense_backend(args)
        rows: list[dict[str, Any]] = []
        raw_reports: list[dict[str, Any]] = []
        with SessionLocal() as db:
            for index, sample in enumerate(samples, start=1):
                payload = {
                    "run_kind": "real_manual_cohort",
                    "run_id": sample["cohort_id"],
                    "question": sample["question"],
                    "top_k": max_top_k,
                    "candidate_top_k": max(args.candidate_top_k or max_top_k, max_top_k),
                    "manual_gate_result": {"applied_manuals": [manual_ref]},
                    "embedding_mode": args.embedding_mode,
                }
                started = time.perf_counter()
                report = run_node_shadow_replay(
                    db,
                    payload,
                    dense_search_backend=dense_backend,
                    node_corpora=[corpus],
                )
                fast_search_wall_ms = round((time.perf_counter() - started) * 1000, 3)
                raw_reports.append(report)
                question_id_key = _normalize_text(sample.get("question_id"))
                original_latency = original_by_question_id.get(question_id_key) if question_id_key else None
                rows.append(
                    _evaluate_sample(
                        sample,
                        report,
                        top_ks=top_ks,
                        node_index=node_index,
                        document_id=args.document_id,
                        version_id=args.version_id,
                        fast_search_wall_ms=fast_search_wall_ms,
                        original_retrieval_latency=original_latency,
                    )
                )
                if args.progress_every and (index == 1 or index % args.progress_every == 0 or index == len(samples)):
                    print(f"real_manual_shadow_eval progress {index}/{len(samples)}", file=sys.stderr, flush=True)
    finally:
        engine.dispose()

    summary = _summarize_rows(rows, top_ks)
    special_rows = [row for row in rows if "special_airport" in row.get("tags", [])]
    p0_rows = [row for row in rows if "p0" in row.get("tags", [])]
    special_summary = _summarize_rows(special_rows, top_ks) if special_rows else {"overall": {}, "language_token_overlap": {}}
    p0_summary = _summarize_rows(p0_rows, top_ks) if p0_rows else {"overall": {}, "language_token_overlap": {}}
    artifact_summary = _artifact_summary(rows, raw_reports)

    return {
        "schema_version": "node_shadow_fast_search_latency_eval_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runtime": _runtime_snapshot(args, manual_truth, manual_ref),
        "questions_json_structure": {
            "type": "array",
            "count": len(questions),
            "keys": sorted({key for item in questions if isinstance(item, Mapping) for key in item.keys()}),
            "kind_counts": dict(Counter(str(item.get("kind")) for item in questions if isinstance(item, Mapping))),
            "has_expected_section_node_citation": False,
            "has_reference_answer": all(bool(_normalize_text(item.get("reference_answer"))) for item in questions if isinstance(item, Mapping)),
            "source_observation": "results/test_log.txt indicates questions.json was reused with 500 questions after loading 1340 PDF pages; questions.json itself contains no provenance block.",
        },
        "cohort": {
            **cohort_summary,
            "structure_summary": structure_summary,
            "manual_document_id": args.document_id,
            "manual_version_id": args.version_id,
            "manual_label": manual_ref.get("document_label"),
        },
        "summary": {
            **summary,
            "artifact_exact_dense": artifact_summary,
            "artifact_embedding_probe": artifact_embedding_probe,
            "original_retrieval_benchmark": {
                key: value
                for key, value in original_retrieval.items()
                if key != "by_question_id"
            },
            "rerank_latency": (original_retrieval.get("summary") or {}).get("rerank_ms"),
            "special_airport_cohort": special_summary,
            "p0_three_questions": p0_summary,
            "negative_gain_samples@8": _negative_gain_samples(rows, top_k=8),
            "failure_samples@8": _failure_samples(rows, top_k=8),
        },
        "p0_results": p0_rows,
        "rows": rows,
    }


def _write_output(path: str | None, payload: Mapping[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    if not path:
        print(serialized)
        return
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(serialized, encoding="utf-8")


def _parse_top_ks(value: str) -> list[int]:
    top_ks = [int(part.strip()) for part in value.split(",") if part.strip()]
    if not top_ks:
        raise argparse.ArgumentTypeError("top-ks must contain at least one integer")
    return top_ks


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Real manual cohort node-shadow diagnostics.")
    parser.add_argument("--questions", default=str(ROOT / "results/questions.json"))
    parser.add_argument("--structure", default=str(ROOT / "results/operations_manual_v1_structure.json"))
    parser.add_argument("--raw-results", default=str(ROOT / "results/raw_results.json"))
    parser.add_argument("--document-id", default=DEFAULT_DOCUMENT_ID)
    parser.add_argument("--version-id", default=DEFAULT_VERSION_ID)
    parser.add_argument("--document-label", default=DEFAULT_DOCUMENT_LABEL)
    parser.add_argument("--dense-source", choices=("sparse", "off", "artifact-exact", "es-shadow"), default="artifact-exact")
    parser.add_argument("--embedding-mode", choices=("auto", "off", "provider", "system"), default="system")
    parser.add_argument("--top-ks", type=_parse_top_ks, default=[10])
    parser.add_argument("--candidate-top-k", type=int, default=20)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--progress-every", type=int, default=25)
    parser.add_argument("--output", default=str(ROOT / "results/node_shadow_fast_search_latency_latest.json"))
    args = parser.parse_args(argv)

    payload = run_real_manual_eval(args)
    _write_output(args.output, payload)


if __name__ == "__main__":
    main()
