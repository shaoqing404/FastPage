from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


TELEMETRY_SCHEMA_VERSION = "ie4.telemetry.v1"
EMBEDDING_MODE_VALUES = frozenset({"auto", "off", "provider", "system"})


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_embedding_mode(value: Any) -> tuple[str | None, str, bool]:
    raw = _normalize_text(value)
    if raw is None:
        return None, "off", False
    normalized = raw.lower()
    if normalized in EMBEDDING_MODE_VALUES:
        return raw, normalized, False
    return raw, "off", True


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)


def telemetry_payload(**sections: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"schema_version": TELEMETRY_SCHEMA_VERSION}
    for key, value in sections.items():
        if value is not None:
            payload[key] = value
    return payload


def embedding_provider_telemetry(
    *,
    requested_mode: Any,
    embedding_config: Mapping[str, Any],
) -> dict[str, Any]:
    raw_requested_mode, normalized_mode, invalid_mode = _normalize_embedding_mode(requested_mode)
    resolved_mode = _normalize_text(embedding_config.get("resolved_mode"))
    enabled = bool(embedding_config.get("enabled"))
    fallback_reason = _normalize_text(embedding_config.get("fallback_reason"))

    if fallback_reason is None:
        if invalid_mode:
            fallback_reason = "invalid_mode_disabled"
        elif normalized_mode == "off":
            fallback_reason = "disabled_by_flag"
        elif enabled:
            fallback_reason = None
        elif normalized_mode == "provider":
            fallback_reason = "provider_embedding_unavailable"
        elif normalized_mode == "system":
            fallback_reason = "system_embedding_unavailable"
        else:
            fallback_reason = "no_embedding_provider_available"

    return {
        "requested_mode": normalized_mode,
        "raw_requested_mode": raw_requested_mode,
        "resolved_mode": resolved_mode,
        "enabled": enabled,
        "provider_source": _normalize_text(embedding_config.get("provider_source")),
        "provider_type": _normalize_text(embedding_config.get("provider_type")),
        "model": _normalize_text(embedding_config.get("model")),
        "fallback_reason": fallback_reason,
    }


def routing_asset_item(
    *,
    document_id: str | None,
    version_id: str | None,
    routing_index_status: Any,
    routing_index_path: Any,
    routing_index_version: Any = None,
) -> dict[str, Any]:
    status = _normalize_text(routing_index_status) or "unknown"
    path_present = _normalize_text(routing_index_path) is not None
    ready = status == "index_ready" and path_present
    failed = status == "failed"
    state = "ready" if ready else "failed" if failed else "missing"
    return {
        "document_id": document_id,
        "version_id": version_id,
        "routing_index_status": status,
        "routing_index_path_present": path_present,
        "routing_index_version": _normalize_text(routing_index_version),
        "state": state,
    }


def routing_asset_coverage(items: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    materialized = list(items)
    total_count = len(materialized)
    ready_count = sum(1 for item in materialized if item.get("state") == "ready")
    failed_count = sum(1 for item in materialized if item.get("state") == "failed")
    missing_count = max(total_count - ready_count - failed_count, 0)
    return {
        "total_count": total_count,
        "ready_count": ready_count,
        "missing_count": missing_count,
        "failed_count": failed_count,
        "coverage_rate": _rate(ready_count, total_count),
        "missing_rate": _rate(missing_count, total_count),
        "failure_rate": _rate(failed_count, total_count),
    }


def routing_asset_build_telemetry(
    *,
    items: Iterable[Mapping[str, Any]],
    mode: str,
    dry_run: bool,
    backfill: bool,
    attempted: bool,
    status: str | None = None,
    node_count: int | None = None,
    hook_results: Mapping[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    materialized = list(items)
    coverage = routing_asset_coverage(materialized)
    resolved_status = status
    if resolved_status is None:
        if coverage["failed_count"]:
            resolved_status = "failed"
        elif coverage["missing_count"]:
            resolved_status = "missing"
        else:
            resolved_status = "completed"

    payload: dict[str, Any] = {
        "mode": {
            "requested_mode": mode,
            "dry_run": bool(dry_run),
            "backfill": bool(backfill),
        },
        "status": resolved_status,
        "attempted": bool(attempted),
        "coverage": coverage,
    }
    if len(materialized) == 1:
        payload["asset"] = dict(materialized[0])
    if node_count is not None:
        payload["node_count"] = int(node_count)
    if hook_results is not None:
        payload["hook_results"] = dict(hook_results)
    if error:
        payload["error"] = error
    return payload


def manual_gate_telemetry(
    *,
    gate_result: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(gate_result, Mapping):
        return None
    diagnostics = gate_result.get("diagnostics")
    if not isinstance(diagnostics, Mapping):
        return None
    shadow_eval = diagnostics.get("shadow_eval")
    payload: dict[str, Any] = {
        "requested_mode": _normalize_text(diagnostics.get("requested_mode")),
        "effective_mode": _normalize_text(diagnostics.get("effective_mode")),
        "decision": _normalize_text(diagnostics.get("decision")),
        "fallback_reason": _normalize_text(diagnostics.get("fallback_reason")),
        "mode_fallback_reason": _normalize_text(diagnostics.get("mode_fallback_reason")),
        "decision_fallback_reason": _normalize_text(diagnostics.get("decision_fallback_reason")),
        "manual_count_resolved": int(diagnostics.get("manual_count_resolved") or 0),
        "predicted_selected_count": int(diagnostics.get("predicted_selected_count") or 0),
        "applied_selected_count": int(diagnostics.get("applied_selected_count") or 0),
        "selected_manuals": list(diagnostics.get("selected_manuals") or []),
        "applied_manuals": list(diagnostics.get("applied_manuals") or []),
        "selected_manual_ids": list(diagnostics.get("predicted_selected_manual_ids") or []),
        "applied_manual_ids": list(diagnostics.get("applied_selected_manual_ids") or []),
        "applied_selection": _normalize_text(diagnostics.get("applied_selection")),
        "runtime_fallback_reason": _normalize_text(diagnostics.get("runtime_fallback_reason")),
        "full_retry": dict(diagnostics.get("full_retry") or {}),
        "zero_hit_retry": dict(diagnostics.get("zero_hit_retry") or {}),
        "score_version": _normalize_text(diagnostics.get("score_version")),
        "inventory_source_mix": dict(diagnostics.get("inventory_source_mix") or {}),
        "latency_ms": int(diagnostics.get("latency_ms") or 0),
        "timings_ms": dict(diagnostics.get("timings_ms") or {}),
    }
    if isinstance(shadow_eval, Mapping):
        payload["shadow_eval"] = {
            "top1_hit_final_citation_manuals": bool(shadow_eval.get("top1_hit_final_citation_manuals")),
            "top2_full_coverage_of_final_citation_manuals": bool(
                shadow_eval.get("top2_full_coverage_of_final_citation_manuals")
            ),
            "citation_recall_at_top1": float(shadow_eval.get("citation_recall_at_top1") or 0.0),
            "citation_recall_at_top2": float(shadow_eval.get("citation_recall_at_top2") or 0.0),
            "would_reduce_manuals_from": int(shadow_eval.get("would_reduce_manuals_from") or 0),
            "would_reduce_manuals_to": int(shadow_eval.get("would_reduce_manuals_to") or 0),
            "would_fallback_full": bool(shadow_eval.get("would_fallback_full")),
            "final_citation_manual_count": int(shadow_eval.get("final_citation_manual_count") or 0),
            "final_citation_count": int(shadow_eval.get("final_citation_count") or 0),
            "manual_gate_latency_ms": int(shadow_eval.get("manual_gate_latency_ms") or 0),
        }
    return payload
