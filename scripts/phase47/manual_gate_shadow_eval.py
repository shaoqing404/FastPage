#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import get_settings


def _json_loads(text: str | None, fallback: Any) -> Any:
    if not text:
        return fallback
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return fallback


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * percentile))))
    return int(ordered[index])


def _counter_dict(counter: Counter[str]) -> dict[str, int]:
    return {key: int(value) for key, value in counter.items() if value}


def _engine() -> Engine:
    settings = get_settings()
    connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    return create_engine(settings.database_url, future=True, connect_args=connect_args)


def _table_has_columns(engine: Engine, table_name: str, required_columns: set[str]) -> tuple[bool, str | None]:
    try:
        columns = {column["name"] for column in inspect(engine).get_columns(table_name)}
    except Exception as exc:
        return False, f"table_unavailable:{type(exc).__name__}"
    missing = sorted(required_columns - columns)
    if missing:
        return False, f"missing_columns:{','.join(missing)}"
    return True, None


def _run_records(args: argparse.Namespace) -> tuple[list[tuple[str, dict[str, Any]]], dict[str, str]]:
    engine = _engine()
    records: list[tuple[str, dict[str, Any]]] = []
    scan_errors: dict[str, str] = {}
    try:
        with engine.connect() as conn:
            if args.run_kind in {"all", "chat"}:
                supported, error = _table_has_columns(
                    engine,
                    "chat_runs",
                    {"id", "status", "created_at", "execution_context_json"},
                )
                if not supported:
                    scan_errors["chat_runs"] = error or "unsupported_schema"
                else:
                    query = """
                        SELECT id, status, created_at, execution_context_json
                        FROM chat_runs
                    """
                    conditions: list[str] = []
                    params: dict[str, Any] = {"limit": args.limit}
                    if args.status:
                        conditions.append("status = :status")
                        params["status"] = args.status
                    if conditions:
                        query += " WHERE " + " AND ".join(conditions)
                    query += " ORDER BY created_at DESC LIMIT :limit"
                    for row in conn.execute(text(query), params).mappings():
                        records.append(("chat", dict(row)))
            if args.run_kind in {"all", "compliance"}:
                supported, error = _table_has_columns(
                    engine,
                    "compliance_runs",
                    {"id", "status", "created_at", "execution_context_json"},
                )
                if not supported:
                    scan_errors["compliance_runs"] = error or "unsupported_schema"
                else:
                    query = """
                        SELECT id, status, created_at, execution_context_json
                        FROM compliance_runs
                    """
                    conditions = []
                    params = {"limit": args.limit}
                    if args.status:
                        conditions.append("status = :status")
                        params["status"] = args.status
                    if conditions:
                        query += " WHERE " + " AND ".join(conditions)
                    query += " ORDER BY created_at DESC LIMIT :limit"
                    for row in conn.execute(text(query), params).mappings():
                        records.append(("compliance", dict(row)))
    finally:
        engine.dispose()
    return records, scan_errors


def _extract_manual_gate_record(run_kind: str, run: dict[str, Any]) -> dict[str, Any] | None:
    execution_context = _json_loads(run.get("execution_context_json"), {})
    retrieval = execution_context.get("retrieval") if isinstance(execution_context, dict) else None
    diagnostics = retrieval.get("diagnostics") if isinstance(retrieval, dict) else None
    manual_gate = diagnostics.get("manual_gate") if isinstance(diagnostics, dict) else None
    if not isinstance(manual_gate, dict):
        return None
    shadow_eval = manual_gate.get("shadow_eval") if isinstance(manual_gate.get("shadow_eval"), dict) else None
    return {
        "run_kind": run_kind,
        "run_id": run.get("id"),
        "status": run.get("status"),
        "created_at": run.get("created_at"),
        "requested_mode": manual_gate.get("requested_mode"),
        "effective_mode": manual_gate.get("effective_mode"),
        "decision": manual_gate.get("decision"),
        "fallback_reason": manual_gate.get("fallback_reason"),
        "manual_count_resolved": int(manual_gate.get("manual_count_resolved") or 0),
        "predicted_selected_count": int(manual_gate.get("predicted_selected_count") or 0),
        "applied_selected_count": int(manual_gate.get("applied_selected_count") or 0),
        "inventory_source_mix": dict(manual_gate.get("inventory_source_mix") or {}),
        "latency_ms": int(manual_gate.get("latency_ms") or 0),
        "timings_ms": dict(manual_gate.get("timings_ms") or {}),
        "shadow_eval": shadow_eval,
    }


def _aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    requested_mode_counts: Counter[str] = Counter()
    effective_mode_counts: Counter[str] = Counter()
    decision_counts: Counter[str] = Counter()
    fallback_reason_counts: Counter[str] = Counter()
    inventory_source_mix: Counter[str] = Counter()
    manual_gate_latencies: list[int] = []
    inventory_latencies: list[int] = []
    score_latencies: list[int] = []
    decision_latencies: list[int] = []
    evaluable_records: list[dict[str, Any]] = []

    for record in records:
        requested_mode_counts[str(record.get("requested_mode") or "unknown")] += 1
        effective_mode_counts[str(record.get("effective_mode") or "unknown")] += 1
        decision_counts[str(record.get("decision") or "unknown")] += 1
        fallback_reason = str(record.get("fallback_reason") or "none")
        fallback_reason_counts[fallback_reason] += 1
        for source, count in dict(record.get("inventory_source_mix") or {}).items():
            inventory_source_mix[str(source)] += int(count or 0)
        latency_ms = int(record.get("latency_ms") or 0)
        if latency_ms:
            manual_gate_latencies.append(latency_ms)
        timings_ms = dict(record.get("timings_ms") or {})
        if timings_ms.get("inventory") is not None:
            inventory_latencies.append(int(timings_ms.get("inventory") or 0))
        if timings_ms.get("score") is not None:
            score_latencies.append(int(timings_ms.get("score") or 0))
        if timings_ms.get("decision") is not None:
            decision_latencies.append(int(timings_ms.get("decision") or 0))
        if isinstance(record.get("shadow_eval"), dict):
            evaluable_records.append(record)

    top1_hits = sum(1 for record in evaluable_records if record["shadow_eval"].get("top1_hit_final_citation_manuals"))
    top2_hits = sum(
        1 for record in evaluable_records if record["shadow_eval"].get("top2_full_coverage_of_final_citation_manuals")
    )
    fallback_full_count = sum(1 for record in evaluable_records if record["shadow_eval"].get("would_fallback_full"))
    citation_recall_at_top1 = [
        float(record["shadow_eval"].get("citation_recall_at_top1") or 0.0) for record in evaluable_records
    ]
    citation_recall_at_top2 = [
        float(record["shadow_eval"].get("citation_recall_at_top2") or 0.0) for record in evaluable_records
    ]
    reduction_pairs = [
        (
            int(record["shadow_eval"].get("would_reduce_manuals_from") or 0),
            int(record["shadow_eval"].get("would_reduce_manuals_to") or 0),
        )
        for record in evaluable_records
    ]
    avg_reduce_from = round(mean(pair[0] for pair in reduction_pairs), 4) if reduction_pairs else 0.0
    avg_reduce_to = round(mean(pair[1] for pair in reduction_pairs), 4) if reduction_pairs else 0.0

    return {
        "run_count_with_manual_gate": len(records),
        "run_count_with_shadow_eval": len(evaluable_records),
        "requested_mode_counts": _counter_dict(requested_mode_counts),
        "effective_mode_counts": _counter_dict(effective_mode_counts),
        "decision_counts": _counter_dict(decision_counts),
        "fallback_reason_counts": _counter_dict(fallback_reason_counts),
        "shadow_metrics": {
            "top1_hit_final_citation_manuals": {
                "count": top1_hits,
                "rate": _rate(top1_hits, len(evaluable_records)),
            },
            "top2_full_coverage_of_final_citation_manuals": {
                "count": top2_hits,
                "rate": _rate(top2_hits, len(evaluable_records)),
            },
            "citation_recall_at_top1_avg": round(mean(citation_recall_at_top1), 6) if citation_recall_at_top1 else 0.0,
            "citation_recall_at_top2_avg": round(mean(citation_recall_at_top2), 6) if citation_recall_at_top2 else 0.0,
            "would_reduce_manuals_from_avg": avg_reduce_from,
            "would_reduce_manuals_to_avg": avg_reduce_to,
            "would_fallback_full": {
                "count": fallback_full_count,
                "rate": _rate(fallback_full_count, len(evaluable_records)),
            },
            "inventory_source_mix": _counter_dict(inventory_source_mix),
        },
        "latency_ms": {
            "manual_gate_avg": round(mean(manual_gate_latencies), 4) if manual_gate_latencies else 0.0,
            "manual_gate_p95": _percentile(manual_gate_latencies, 0.95),
            "inventory_avg": round(mean(inventory_latencies), 4) if inventory_latencies else 0.0,
            "score_avg": round(mean(score_latencies), 4) if score_latencies else 0.0,
            "decision_avg": round(mean(decision_latencies), 4) if decision_latencies else 0.0,
        },
    }


def _serialize_record(record: dict[str, Any]) -> dict[str, Any]:
    created_at = record.get("created_at")
    serialized = dict(record)
    if isinstance(created_at, datetime):
        serialized["created_at"] = created_at.isoformat()
    return serialized


def _write_output(path: str | None, payload: dict[str, Any]) -> None:
    if not path:
        return
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate Manual Gate shadow diagnostics from chat/compliance runs.")
    parser.add_argument("--run-kind", choices=("all", "chat", "compliance"), default="all")
    parser.add_argument("--status", default="completed")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--sample-limit", type=int, default=20)
    parser.add_argument("--output")
    args = parser.parse_args()

    scanned_records: list[dict[str, Any]] = []
    run_rows, scan_errors = _run_records(args)
    scanned_run_count = 0
    for run_kind, run in run_rows:
        scanned_run_count += 1
        record = _extract_manual_gate_record(run_kind, run)
        if record is not None:
            scanned_records.append(record)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "query": {
            "run_kind": args.run_kind,
            "status": args.status,
            "limit": args.limit,
        },
        "scan": {
            "run_count_scanned": scanned_run_count,
            "run_count_with_manual_gate": len(scanned_records),
            "scan_errors": scan_errors,
        },
        "summary": _aggregate(scanned_records),
        "samples": [_serialize_record(record) for record in scanned_records[: max(0, args.sample_limit)]],
    }
    _write_output(args.output, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
