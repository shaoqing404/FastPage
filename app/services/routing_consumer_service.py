from __future__ import annotations

import re
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DocumentRoutingNode
from app.services.pageindex_service import load_structure_file
from app.services.storage_service import read_document_routing_index


MANUAL_GATE_MODE_VALUES = frozenset({"off", "shadow", "live"})
MANUAL_GATE_SCORE_VERSION = "manual_gate_r1.v1"
MANUAL_GATE_DEFAULT_THRESHOLDS = {
    "top1_min_score": 10.0,
    "top1_min_delta": 3.0,
    "top1_min_signal_count": 2,
    "top2_min_second_score": 7.0,
    "top2_min_third_delta": 1.5,
    "top2_min_signal_count": 2,
}
MANUAL_GATE_INVENTORY_SOURCE_PRIORITY = (
    "document_routing_nodes",
    "routing_index_json",
    "structure_json",
    "metadata_only",
)

_ASCII_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[._/-][A-Za-z0-9]+)*")
_CJK_TOKEN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _manual_key(document_id: str | None, version_id: str | None) -> str:
    return f"{document_id or 'unknown'}:{version_id or 'unknown'}"


def tokenize_routing_text(text: str | None) -> list[str]:
    normalized = _normalize_text(text)
    if normalized is None:
        return []

    lowered = normalized.lower()
    tokens: list[str] = []
    seen: set[str] = set()

    for token in _ASCII_TOKEN_RE.findall(lowered):
        if len(token) >= 2 or any(char.isdigit() for char in token):
            if token not in seen:
                tokens.append(token)
                seen.add(token)
        if any(sep in token for sep in ("-", "_", ".", "/")):
            for part in re.split(r"[-_./]+", token):
                if (len(part) >= 2 or any(char.isdigit() for char in part)) and part not in seen:
                    tokens.append(part)
                    seen.add(part)

    for span in _CJK_TOKEN_RE.findall(lowered):
        if span not in seen:
            tokens.append(span)
            seen.add(span)
        if len(span) > 1:
            for index in range(len(span) - 1):
                bigram = span[index : index + 2]
                if bigram not in seen:
                    tokens.append(bigram)
                    seen.add(bigram)
    return tokens


def build_manual_gate_ref(
    *,
    document_id: str,
    version_id: str,
    document_label: str | None,
    version_label: str | None,
    display_name: str | None,
    source_filename: str | None,
    storage_path: str | None,
    parsed_structure_path: str | None,
    routing_index_status: str | None,
    routing_index_path: str | None,
    routing_index_version: str | None,
) -> dict[str, Any]:
    return {
        "manual_key": _manual_key(document_id, version_id),
        "document_id": document_id,
        "version_id": version_id,
        "document_label": _normalize_text(document_label) or _normalize_text(display_name) or _normalize_text(source_filename),
        "version_label": _normalize_text(version_label),
        "display_name": _normalize_text(display_name),
        "source_filename": _normalize_text(source_filename),
        "storage_path": _normalize_text(storage_path),
        "parsed_structure_path": _normalize_text(parsed_structure_path),
        "routing_index_status": _normalize_text(routing_index_status),
        "routing_index_path": _normalize_text(routing_index_path),
        "routing_index_version": _normalize_text(routing_index_version),
    }


def _normalize_manual_gate_mode(value: Any) -> tuple[str | None, str, bool]:
    raw = _normalize_text(value)
    if raw is None:
        return None, "off", False
    normalized = raw.lower()
    if normalized in MANUAL_GATE_MODE_VALUES:
        return raw, normalized, False
    return raw, "off", True


def resolve_manual_gate_mode(
    *,
    requested_mode: Any,
    default_mode: Any,
    allow_live: bool,
    live_deferred_reason: str = "live_deferred_until_a3",
) -> dict[str, Any]:
    requested_raw, requested_normalized, invalid_requested = _normalize_manual_gate_mode(requested_mode)
    default_raw, default_normalized, invalid_default = _normalize_manual_gate_mode(default_mode)

    source = "request" if requested_raw is not None else "settings"
    configured_mode = requested_normalized if requested_raw is not None else default_normalized
    fallback_reason = None
    effective_mode = configured_mode
    invalid_config = invalid_requested or (requested_raw is None and invalid_default)

    if invalid_config:
        fallback_reason = "invalid_mode_disabled"
        effective_mode = "off"
    elif configured_mode == "live" and not allow_live:
        fallback_reason = live_deferred_reason
        effective_mode = "shadow"

    return {
        "requested_mode": configured_mode,
        "effective_mode": effective_mode,
        "fallback_reason": fallback_reason,
        "source": source,
        "raw_requested_mode": requested_raw,
        "default_mode": default_normalized,
    }


def _node_record(
    *,
    node_id: Any,
    title: Any,
    breadcrumb: Any,
    depth: Any,
    page_start: Any,
    page_end: Any,
) -> dict[str, Any]:
    return {
        "node_id": _normalize_text(node_id),
        "title": _normalize_text(title),
        "breadcrumb": _normalize_text(breadcrumb),
        "depth": _normalize_optional_int(depth) or 0,
        "page_start": _normalize_optional_int(page_start),
        "page_end": _normalize_optional_int(page_end),
    }


def _nodes_from_routing_rows(rows: Sequence[DocumentRoutingNode]) -> list[dict[str, Any]]:
    return [
        _node_record(
            node_id=row.node_id,
            title=row.title,
            breadcrumb=row.breadcrumb,
            depth=row.depth,
            page_start=row.page_start,
            page_end=row.page_end,
        )
        for row in rows
    ]


def _nodes_from_routing_payload(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    nodes = payload.get("nodes")
    if not isinstance(nodes, list):
        return []
    return [
        _node_record(
            node_id=node.get("node_id"),
            title=node.get("title"),
            breadcrumb=node.get("breadcrumb"),
            depth=node.get("depth"),
            page_start=node.get("page_start"),
            page_end=node.get("page_end"),
        )
        for node in nodes
        if isinstance(node, Mapping)
    ]


def _build_breadcrumb(manual_label: str | None, ancestors: list[str]) -> str | None:
    parts: list[str] = []
    if manual_label:
        parts.append(manual_label)
    parts.extend(title for title in ancestors if title)
    if not parts:
        return None
    return " / ".join(parts)


def _collect_structure_nodes(
    nodes: list[dict[str, Any]] | dict[str, Any] | None,
    *,
    manual_label: str | None,
    depth: int = 0,
    ancestors: list[str] | None = None,
    collected: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if collected is None:
        collected = []
    if not nodes:
        return collected

    node_items = nodes if isinstance(nodes, list) else [nodes]
    current_ancestors = list(ancestors or [])
    for node in node_items:
        if not isinstance(node, Mapping):
            continue
        title = _normalize_text(node.get("title"))
        next_ancestors = current_ancestors + ([title] if title else [])
        collected.append(
            _node_record(
                node_id=node.get("node_id"),
                title=title,
                breadcrumb=_build_breadcrumb(manual_label, next_ancestors),
                depth=depth,
                page_start=node.get("start_index"),
                page_end=node.get("end_index"),
            )
        )
        child_nodes = node.get("nodes")
        if child_nodes:
            _collect_structure_nodes(
                child_nodes,
                manual_label=manual_label,
                depth=depth + 1,
                ancestors=next_ancestors,
                collected=collected,
            )
    return collected


def _rows_by_version_id(db: Session, version_ids: list[str]) -> dict[str, list[DocumentRoutingNode]]:
    if not version_ids:
        return {}
    rows = db.scalars(
        select(DocumentRoutingNode)
        .where(DocumentRoutingNode.version_id.in_(version_ids))
        .order_by(DocumentRoutingNode.version_id.asc(), DocumentRoutingNode.depth.asc(), DocumentRoutingNode.node_id.asc())
    ).all()
    grouped: dict[str, list[DocumentRoutingNode]] = {}
    for row in rows:
        grouped.setdefault(row.version_id, []).append(row)
    return grouped


def build_manual_inventory(
    manual_ref: Mapping[str, Any],
    *,
    routing_rows: Sequence[DocumentRoutingNode] | None = None,
) -> dict[str, Any]:
    manual_inventory = dict(manual_ref)
    warning: str | None = None
    routing_nodes = _nodes_from_routing_rows(routing_rows or [])
    if routing_nodes:
        manual_inventory["inventory_source"] = "document_routing_nodes"
        manual_inventory["inventory_nodes"] = routing_nodes
        manual_inventory["inventory_warning"] = None
        manual_inventory["inventory_node_count"] = len(routing_nodes)
        return manual_inventory

    routing_index_path = _normalize_text(manual_ref.get("routing_index_path"))
    if routing_index_path:
        try:
            routing_payload = read_document_routing_index(routing_index_path)
            routing_nodes = _nodes_from_routing_payload(routing_payload)
            if routing_nodes:
                manual_inventory["inventory_source"] = "routing_index_json"
                manual_inventory["inventory_nodes"] = routing_nodes
                manual_inventory["inventory_warning"] = None
                manual_inventory["inventory_node_count"] = len(routing_nodes)
                return manual_inventory
        except Exception as exc:  # pragma: no cover - defensive fallback
            warning = f"routing_index_json_unavailable:{type(exc).__name__}"

    parsed_structure_path = _normalize_text(manual_ref.get("parsed_structure_path"))
    if parsed_structure_path:
        try:
            structure = load_structure_file(parsed_structure_path)
            structure_nodes = _collect_structure_nodes(
                structure,
                manual_label=_normalize_text(manual_ref.get("document_label")),
            )
            if structure_nodes:
                manual_inventory["inventory_source"] = "structure_json"
                manual_inventory["inventory_nodes"] = structure_nodes
                manual_inventory["inventory_warning"] = warning
                manual_inventory["inventory_node_count"] = len(structure_nodes)
                return manual_inventory
        except Exception as exc:  # pragma: no cover - defensive fallback
            warning = f"structure_json_unavailable:{type(exc).__name__}"

    manual_inventory["inventory_source"] = "metadata_only"
    manual_inventory["inventory_nodes"] = []
    manual_inventory["inventory_warning"] = warning
    manual_inventory["inventory_node_count"] = 0
    return manual_inventory


def build_manual_inventories(db: Session, manual_refs: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    version_ids = [
        str(version_id)
        for version_id in (manual_ref.get("version_id") for manual_ref in manual_refs)
        if _normalize_text(version_id) is not None
    ]
    routing_rows = _rows_by_version_id(db, version_ids)
    return [
        build_manual_inventory(
            manual_ref,
            routing_rows=routing_rows.get(str(manual_ref.get("version_id") or "")) or [],
        )
        for manual_ref in manual_refs
    ]


def _token_overlap(query_tokens: set[str], candidate_text: str | None, *, cap: int) -> int:
    if not query_tokens:
        return 0
    candidate_tokens = set(tokenize_routing_text(candidate_text))
    if not candidate_tokens:
        return 0
    return min(len(query_tokens & candidate_tokens), cap)


def _substring_hit(query_tokens: Sequence[str], candidate_text: str | None) -> bool:
    normalized = (_normalize_text(candidate_text) or "").lower()
    if not normalized:
        return False
    return any(token in normalized for token in query_tokens if len(token) >= 3)


def _page_span(page_start: int | None, page_end: int | None) -> int | None:
    if page_start is None or page_end is None:
        return None
    if page_end < page_start:
        return None
    return page_end - page_start + 1


def _best_node_signal(query_tokens: set[str], inventories: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    best = {
        "node_id": None,
        "title": None,
        "title_hits": 0,
        "breadcrumb_hits": 0,
        "depth": 0,
        "page_span": None,
        "score": 0.0,
    }
    for node in inventories:
        title_hits = _token_overlap(query_tokens, _normalize_text(node.get("title")), cap=6)
        breadcrumb_hits = _token_overlap(query_tokens, _normalize_text(node.get("breadcrumb")), cap=4)
        depth = _normalize_optional_int(node.get("depth")) or 0
        page_span = _page_span(
            _normalize_optional_int(node.get("page_start")),
            _normalize_optional_int(node.get("page_end")),
        )
        has_heading_signal = title_hits > 0 or breadcrumb_hits > 0
        depth_bonus = 0.25 * min(depth, 3) if has_heading_signal else 0.0
        if has_heading_signal and page_span is not None and page_span <= 4:
            span_bonus = 1.0
        elif has_heading_signal and page_span is not None and page_span <= 10:
            span_bonus = 0.5
        else:
            span_bonus = 0.0
        node_score = round((title_hits * 1.25) + (min(breadcrumb_hits, 2) * 0.75) + depth_bonus + span_bonus, 4)
        if node_score > best["score"]:
            best = {
                "node_id": _normalize_text(node.get("node_id")),
                "title": _normalize_text(node.get("title")),
                "title_hits": title_hits,
                "breadcrumb_hits": breadcrumb_hits,
                "depth": depth,
                "page_span": page_span,
                "score": node_score,
            }
    return best


def score_manual_inventories(question: str, manual_inventories: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    query_tokens_list = tokenize_routing_text(question)
    query_tokens = set(query_tokens_list)
    substring_tokens = [token for token in query_tokens_list if len(token) >= 3]
    inventory_bonus_map = {
        "document_routing_nodes": 1.0,
        "routing_index_json": 0.75,
        "structure_json": 0.25,
        "metadata_only": 0.0,
    }

    scored_manuals: list[dict[str, Any]] = []
    for index, manual in enumerate(manual_inventories):
        best_node = _best_node_signal(query_tokens, manual.get("inventory_nodes") or [])
        label_text = _normalize_text(manual.get("document_label")) or _normalize_text(manual.get("display_name"))
        source_filename = _normalize_text(manual.get("source_filename"))
        label_hits = _token_overlap(query_tokens, label_text, cap=4)
        source_hits = _token_overlap(query_tokens, source_filename, cap=4)
        label_phrase_hit = _substring_hit(substring_tokens, label_text)
        source_phrase_hit = _substring_hit(substring_tokens, source_filename)
        inventory_source = str(manual.get("inventory_source") or "metadata_only")
        inventory_bonus = inventory_bonus_map.get(inventory_source, 0.0)
        score = round(
            (3.0 if label_phrase_hit else 0.0)
            + (2.0 if source_phrase_hit else 0.0)
            + (label_hits * 1.5)
            + (source_hits * 1.0)
            + float(best_node["score"])
            + inventory_bonus,
            4,
        )
        signal_count = sum(
            1
            for value in (
                label_phrase_hit,
                source_phrase_hit,
                label_hits > 0,
                source_hits > 0,
                best_node["title_hits"] > 0,
                best_node["breadcrumb_hits"] > 0,
            )
            if value
        )
        scored_manuals.append(
            {
                "manual_key": manual.get("manual_key"),
                "document_id": manual.get("document_id"),
                "version_id": manual.get("version_id"),
                "document_label": manual.get("document_label"),
                "version_label": manual.get("version_label"),
                "display_name": manual.get("display_name"),
                "source_filename": manual.get("source_filename"),
                "routing_index_status": manual.get("routing_index_status"),
                "routing_index_path_present": _normalize_text(manual.get("routing_index_path")) is not None,
                "routing_index_version": manual.get("routing_index_version"),
                "inventory_source": inventory_source,
                "inventory_node_count": int(manual.get("inventory_node_count") or 0),
                "inventory_warning": manual.get("inventory_warning"),
                "score": score,
                "signal_count": signal_count,
                "label_phrase_hit": bool(label_phrase_hit),
                "source_phrase_hit": bool(source_phrase_hit),
                "label_hit_count": label_hits,
                "source_hit_count": source_hits,
                "best_node_id": best_node["node_id"],
                "best_node_title": best_node["title"],
                "best_title_hit_count": best_node["title_hits"],
                "best_breadcrumb_hit_count": best_node["breadcrumb_hits"],
                "best_depth": best_node["depth"],
                "best_page_span": best_node["page_span"],
                "original_index": index,
            }
        )
    scored_manuals.sort(key=lambda item: (-float(item["score"]), int(item["original_index"])))
    for rank, manual in enumerate(scored_manuals, start=1):
        manual["rank"] = rank
    return scored_manuals


def build_inventory_source_mix(manuals: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = Counter(str(manual.get("inventory_source") or "metadata_only") for manual in manuals)
    return {
        source: int(counts.get(source, 0))
        for source in MANUAL_GATE_INVENTORY_SOURCE_PRIORITY
        if counts.get(source, 0)
    }


def _selected_manual_keys(scored_manuals: Sequence[Mapping[str, Any]], selected_count: int) -> list[str]:
    return [
        str(manual.get("manual_key"))
        for manual in scored_manuals[: max(0, selected_count)]
        if _normalize_text(manual.get("manual_key")) is not None
    ]


def _full_fallback_decision(
    scored_manuals: Sequence[Mapping[str, Any]],
    *,
    fallback_reason: str,
    thresholds: Mapping[str, Any],
) -> dict[str, Any]:
    manual_count = len(scored_manuals)
    return {
        "decision": "fallback_full",
        "fallback_reason": fallback_reason,
        "predicted_selected_count": manual_count,
        "predicted_selected_manual_keys": _selected_manual_keys(scored_manuals, manual_count),
        "thresholds": thresholds,
    }


def decide_manual_gate(
    scored_manuals: Sequence[Mapping[str, Any]],
    *,
    thresholds: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_thresholds = {**MANUAL_GATE_DEFAULT_THRESHOLDS, **dict(thresholds or {})}
    manual_count = len(scored_manuals)
    if manual_count <= 1:
        return {
            "decision": "bypass_single_manual",
            "fallback_reason": None,
            "predicted_selected_count": manual_count,
            "predicted_selected_manual_keys": _selected_manual_keys(scored_manuals, manual_count),
            "thresholds": resolved_thresholds,
        }

    top1 = scored_manuals[0]
    top2 = scored_manuals[1]
    top3 = scored_manuals[2] if manual_count > 2 else None
    top1_delta = round(float(top1["score"]) - float(top2["score"]), 4)
    top2_delta = round(float(top2["score"]) - float(top3["score"]), 4) if top3 is not None else float(top2["score"])

    if not any(int(manual.get("inventory_node_count") or 0) > 0 for manual in scored_manuals):
        return _full_fallback_decision(
            scored_manuals,
            fallback_reason="missing_inventory",
            thresholds=resolved_thresholds,
        )

    if (
        float(top1["score"]) >= float(resolved_thresholds["top1_min_score"])
        and top1_delta >= float(resolved_thresholds["top1_min_delta"])
        and int(top1["signal_count"]) >= int(resolved_thresholds["top1_min_signal_count"])
    ):
        predicted_selected_count = 1
        decision = "select_top1"
        fallback_reason = None
    elif (
        manual_count > 2
        and float(top2["score"]) >= float(resolved_thresholds["top2_min_second_score"])
        and top2_delta >= float(resolved_thresholds["top2_min_third_delta"])
        and int(top2["signal_count"]) >= int(resolved_thresholds["top2_min_signal_count"])
    ):
        predicted_selected_count = 2
        decision = "select_top2"
        fallback_reason = None
    else:
        predicted_selected_count = manual_count
        decision = "fallback_full"
        if int(top1["signal_count"]) == 0:
            fallback_reason = "no_manual_signal"
        elif top1_delta < float(resolved_thresholds["top1_min_delta"]):
            fallback_reason = "ambiguous_manual_scores"
        else:
            fallback_reason = "decision_threshold_not_met"

    return {
        "decision": decision,
        "fallback_reason": fallback_reason,
        "predicted_selected_count": predicted_selected_count,
        "predicted_selected_manual_keys": _selected_manual_keys(scored_manuals, predicted_selected_count),
        "thresholds": resolved_thresholds,
    }


def _compact_manual_refs(manual_refs: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "manual_key": _normalize_text(manual_ref.get("manual_key")),
            "document_id": _normalize_text(manual_ref.get("document_id")),
            "version_id": _normalize_text(manual_ref.get("version_id")),
            "document_label": _normalize_text(manual_ref.get("document_label")),
            "version_label": _normalize_text(manual_ref.get("version_label")),
        }
        for manual_ref in manual_refs
    ]


def run_manual_gate(
    db: Session,
    *,
    question: str,
    manual_refs: Sequence[Mapping[str, Any]],
    requested_mode: Any,
    default_mode: Any,
    allow_live: bool,
    live_deferred_reason: str = "live_deferred_until_a3",
) -> dict[str, Any]:
    started = time.perf_counter()
    mode_info = resolve_manual_gate_mode(
        requested_mode=requested_mode,
        default_mode=default_mode,
        allow_live=allow_live,
        live_deferred_reason=live_deferred_reason,
    )

    inventory_started = time.perf_counter()
    manual_inventories = build_manual_inventories(db, manual_refs)
    inventory_ms = int((time.perf_counter() - inventory_started) * 1000)

    score_started = time.perf_counter()
    scored_manuals = score_manual_inventories(question, manual_inventories)
    score_ms = int((time.perf_counter() - score_started) * 1000)

    decision_started = time.perf_counter()
    decision = decide_manual_gate(scored_manuals)
    decision_ms = int((time.perf_counter() - decision_started) * 1000)

    predicted_manual_keys = set(decision["predicted_selected_manual_keys"])
    manuals_by_key = {str(manual_ref.get("manual_key")): dict(manual_ref) for manual_ref in manual_refs}
    predicted_selected_manuals = [
        manuals_by_key[manual_key]
        for manual_key in decision["predicted_selected_manual_keys"]
        if manual_key in manuals_by_key
    ]
    if mode_info["effective_mode"] == "live":
        applied_manuals = predicted_selected_manuals
        applied_selection = decision["decision"]
    else:
        applied_manuals = [dict(manual_ref) for manual_ref in manual_refs]
        applied_selection = "full_manuals"

    latency_ms = int((time.perf_counter() - started) * 1000)
    diagnostics = {
        "score_version": MANUAL_GATE_SCORE_VERSION,
        "requested_mode": mode_info["requested_mode"],
        "effective_mode": mode_info["effective_mode"],
        "mode_source": mode_info["source"],
        "fallback_reason": mode_info["fallback_reason"] or decision["fallback_reason"],
        "mode_fallback_reason": mode_info["fallback_reason"],
        "decision_fallback_reason": decision["fallback_reason"],
        "decision": decision["decision"],
        "manual_count_resolved": len(manual_refs),
        "predicted_selected_count": decision["predicted_selected_count"],
        "applied_selected_count": len(applied_manuals),
        "predicted_selected_manual_ids": list(decision["predicted_selected_manual_keys"]),
        "applied_selected_manual_ids": [
            str(manual_ref.get("manual_key"))
            for manual_ref in applied_manuals
            if _normalize_text(manual_ref.get("manual_key")) is not None
        ],
        "selected_manuals": _compact_manual_refs(predicted_selected_manuals),
        "applied_manuals": _compact_manual_refs(applied_manuals),
        "applied_selection": applied_selection,
        "runtime_fallback_reason": None,
        "full_retry": {
            "applied": False,
            "reason": None,
            "trigger": None,
            "previous_applied_selection": None,
            "previous_applied_manual_ids": [],
        },
        "zero_hit_retry": {
            "applied": False,
            "reason": None,
            "trigger": None,
        },
        "thresholds": decision["thresholds"],
        "inventory_source_mix": build_inventory_source_mix(manual_inventories),
        "latency_ms": latency_ms,
        "timings_ms": {
            "inventory": inventory_ms,
            "score": score_ms,
            "decision": decision_ms,
        },
        "manuals": [
            {
                key: value
                for key, value in manual.items()
                if key not in {"original_index"}
            }
            for manual in scored_manuals
        ],
        "shadow_eval": None,
    }
    return {
        "requested_mode": mode_info["requested_mode"],
        "effective_mode": mode_info["effective_mode"],
        "decision": decision["decision"],
        "fallback_reason": diagnostics["fallback_reason"],
        "selected_manuals": predicted_selected_manuals,
        "predicted_selected_manuals": predicted_selected_manuals,
        "applied_manuals": applied_manuals,
        "diagnostics": diagnostics,
    }


def manual_gate_error_result(
    *,
    manual_refs: Sequence[Mapping[str, Any]],
    requested_mode: Any,
    default_mode: Any,
    allow_live: bool,
    error: Exception,
    live_deferred_reason: str = "live_deferred_until_a3",
) -> dict[str, Any]:
    mode_info = resolve_manual_gate_mode(
        requested_mode=requested_mode,
        default_mode=default_mode,
        allow_live=allow_live,
        live_deferred_reason=live_deferred_reason,
    )
    fallback_reason = f"manual_gate_error:{type(error).__name__}"
    diagnostics = {
        "score_version": MANUAL_GATE_SCORE_VERSION,
        "requested_mode": mode_info["requested_mode"],
        "effective_mode": "off",
        "mode_source": mode_info["source"],
        "fallback_reason": fallback_reason,
        "mode_fallback_reason": mode_info["fallback_reason"],
        "decision_fallback_reason": fallback_reason,
        "decision": "fallback_full",
        "manual_count_resolved": len(manual_refs),
        "predicted_selected_count": len(manual_refs),
        "applied_selected_count": len(manual_refs),
        "predicted_selected_manual_ids": [
            str(manual_ref.get("manual_key"))
            for manual_ref in manual_refs
            if _normalize_text(manual_ref.get("manual_key")) is not None
        ],
        "applied_selected_manual_ids": [
            str(manual_ref.get("manual_key"))
            for manual_ref in manual_refs
            if _normalize_text(manual_ref.get("manual_key")) is not None
        ],
        "selected_manuals": _compact_manual_refs(manual_refs),
        "applied_manuals": _compact_manual_refs(manual_refs),
        "applied_selection": "full_manuals",
        "runtime_fallback_reason": fallback_reason,
        "full_retry": {
            "applied": False,
            "reason": None,
            "trigger": None,
            "previous_applied_selection": None,
            "previous_applied_manual_ids": [],
        },
        "zero_hit_retry": {
            "applied": False,
            "reason": None,
            "trigger": None,
        },
        "thresholds": dict(MANUAL_GATE_DEFAULT_THRESHOLDS),
        "inventory_source_mix": {},
        "latency_ms": 0,
        "timings_ms": {
            "inventory": 0,
            "score": 0,
            "decision": 0,
        },
        "manuals": [],
        "shadow_eval": None,
        "error": {
            "type": type(error).__name__,
            "message": str(error),
        },
    }
    return {
        "requested_mode": mode_info["requested_mode"],
        "effective_mode": "off",
        "decision": "fallback_full",
        "fallback_reason": fallback_reason,
        "selected_manuals": [dict(manual_ref) for manual_ref in manual_refs],
        "predicted_selected_manuals": [dict(manual_ref) for manual_ref in manual_refs],
        "applied_manuals": [dict(manual_ref) for manual_ref in manual_refs],
        "diagnostics": diagnostics,
    }


def apply_manual_gate_full_retry(
    gate_result: dict[str, Any],
    manual_refs: Sequence[Mapping[str, Any]],
    *,
    fallback_reason: str,
    trigger: str,
) -> dict[str, Any]:
    """Mutate a live gate result after downstream retrieval proves the pruned set unsafe."""
    full_manuals = [dict(manual_ref) for manual_ref in manual_refs]
    full_manual_ids = [
        str(manual_ref.get("manual_key"))
        for manual_ref in full_manuals
        if _normalize_text(manual_ref.get("manual_key")) is not None
    ]
    diagnostics = gate_result.get("diagnostics")
    if not isinstance(diagnostics, dict):
        diagnostics = {}
        gate_result["diagnostics"] = diagnostics

    previous_applied_selection = _normalize_text(diagnostics.get("applied_selection"))
    previous_applied_manual_ids = list(diagnostics.get("applied_selected_manual_ids") or [])
    diagnostics["fallback_reason"] = fallback_reason
    diagnostics["runtime_fallback_reason"] = fallback_reason
    diagnostics["applied_selected_count"] = len(full_manuals)
    diagnostics["applied_selected_manual_ids"] = full_manual_ids
    diagnostics["applied_manuals"] = _compact_manual_refs(full_manuals)
    diagnostics["applied_selection"] = "full_manuals_after_retry"
    diagnostics["full_retry"] = {
        "applied": True,
        "reason": fallback_reason,
        "trigger": trigger,
        "previous_applied_selection": previous_applied_selection,
        "previous_applied_manual_ids": previous_applied_manual_ids,
    }
    diagnostics["zero_hit_retry"] = {
        "applied": True,
        "reason": fallback_reason,
        "trigger": trigger,
    }

    gate_result["fallback_reason"] = fallback_reason
    gate_result["applied_manuals"] = full_manuals
    return gate_result


def finalize_manual_gate_shadow_eval(
    gate_result: Mapping[str, Any],
    citations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    diagnostics = gate_result.get("diagnostics")
    if not isinstance(diagnostics, dict):
        return {}

    predicted_ids = list(diagnostics.get("predicted_selected_manual_ids") or [])
    top1_ids = set(predicted_ids[:1])
    top2_ids = set(predicted_ids[:2])
    citation_keys = [
        _manual_key(_normalize_text(citation.get("document_id")), _normalize_text(citation.get("version_id")))
        for citation in citations
        if _normalize_text(citation.get("document_id")) is not None and _normalize_text(citation.get("version_id")) is not None
    ]
    final_manual_ids = sorted(set(citation_keys))
    citation_total = len(citation_keys)
    citation_recall_at_top1 = round(
        sum(1 for citation_key in citation_keys if citation_key in top1_ids) / citation_total,
        6,
    ) if citation_total else 0.0
    citation_recall_at_top2 = round(
        sum(1 for citation_key in citation_keys if citation_key in top2_ids) / citation_total,
        6,
    ) if citation_total else 0.0
    shadow_eval = {
        "top1_hit_final_citation_manuals": bool(final_manual_ids) and set(final_manual_ids).issubset(top1_ids),
        "top2_full_coverage_of_final_citation_manuals": bool(final_manual_ids) and set(final_manual_ids).issubset(top2_ids),
        "citation_recall_at_top1": citation_recall_at_top1,
        "citation_recall_at_top2": citation_recall_at_top2,
        "would_reduce_manuals_from": int(diagnostics.get("manual_count_resolved") or 0),
        "would_reduce_manuals_to": int(diagnostics.get("predicted_selected_count") or 0),
        "would_fallback_full": str(diagnostics.get("decision")) == "fallback_full",
        "inventory_source_mix": dict(diagnostics.get("inventory_source_mix") or {}),
        "manual_gate_latency_ms": int(diagnostics.get("latency_ms") or 0),
        "final_citation_manual_ids": final_manual_ids,
        "final_citation_manual_count": len(final_manual_ids),
        "final_citation_count": citation_total,
    }
    diagnostics["shadow_eval"] = shadow_eval
    return shadow_eval


__all__ = [
    "MANUAL_GATE_DEFAULT_THRESHOLDS",
    "MANUAL_GATE_MODE_VALUES",
    "MANUAL_GATE_SCORE_VERSION",
    "build_inventory_source_mix",
    "build_manual_gate_ref",
    "build_manual_inventories",
    "decide_manual_gate",
    "apply_manual_gate_full_retry",
    "finalize_manual_gate_shadow_eval",
    "manual_gate_error_result",
    "resolve_manual_gate_mode",
    "run_manual_gate",
    "score_manual_inventories",
    "tokenize_routing_text",
]
