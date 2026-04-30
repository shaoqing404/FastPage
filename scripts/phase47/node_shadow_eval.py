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
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import get_settings
from app.services.node_embedding_service import (
    EsNodeDenseSearchBackend,
    ExactScanNodeDenseSearchBackend,
    embedding_runtime_options,
)
from app.services.node_shadow_service import run_node_shadow_replay
from app.services.routing_consumer_service import build_manual_gate_ref


def _json_loads(text_value: Any, fallback: Any) -> Any:
    if text_value is None:
        return fallback
    if not isinstance(text_value, str):
        return text_value
    text_payload = text_value.strip()
    if not text_payload:
        return fallback
    try:
        return json.loads(text_payload)
    except json.JSONDecodeError:
        return fallback


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)


def _counter_dict(counter: Counter[str]) -> dict[str, int]:
    return {key: int(value) for key, value in counter.items() if value}


def _masked_database_url(url: str) -> str:
    if "://" not in url or "@" not in url:
        return url
    scheme, rest = url.split("://", 1)
    credentials, host = rest.split("@", 1)
    user = credentials.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}"


def _masked_url(url: str | None) -> str | None:
    if not url:
        return url
    if "://" not in url or "@" not in url:
        return url
    scheme, rest = url.split("://", 1)
    credentials, host = rest.split("@", 1)
    user = credentials.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}"


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


def _run_records(args: argparse.Namespace, engine: Engine) -> tuple[list[tuple[str, dict[str, Any]]], dict[str, str]]:
    records: list[tuple[str, dict[str, Any]]] = []
    scan_errors: dict[str, str] = {}
    with engine.connect() as conn:
        if args.run_kind in {"all", "chat"}:
            supported, error = _table_has_columns(
                engine,
                "chat_runs",
                {"id", "status", "created_at", "question", "citations_json", "execution_context_json", "metrics_json"},
            )
            if not supported:
                scan_errors["chat_runs"] = error or "unsupported_schema"
            else:
                query = """
                    SELECT id, status, created_at, question, document_id, version_id,
                           citations_json, execution_context_json, metrics_json
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
                {"id", "status", "created_at", "question", "citations_json", "execution_context_json", "metrics_json"},
            )
            if not supported:
                scan_errors["compliance_runs"] = error or "unsupported_schema"
            else:
                query = """
                    SELECT id, status, created_at, question, citations_json,
                           execution_context_json, metrics_json
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
    return records, scan_errors


def _manual_pairs_from_execution_context(run: dict[str, Any], execution_context: dict[str, Any]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []

    def add_pair(document_id: Any, version_id: Any) -> None:
        doc = str(document_id or "").strip()
        ver = str(version_id or "").strip()
        if doc and ver and (doc, ver) not in pairs:
            pairs.append((doc, ver))

    retrieval = execution_context.get("retrieval") if isinstance(execution_context, dict) else None
    diagnostics = retrieval.get("diagnostics") if isinstance(retrieval, dict) else None
    manual_gate = diagnostics.get("manual_gate") if isinstance(diagnostics, dict) else None
    if isinstance(manual_gate, dict):
        applied_ids = manual_gate.get("applied_selected_manual_ids") or manual_gate.get("predicted_selected_manual_ids") or []
        for manual_id in applied_ids:
            parts = str(manual_id or "").split(":", 1)
            if len(parts) == 2:
                add_pair(parts[0], parts[1])
        for manual in manual_gate.get("manuals") or []:
            if isinstance(manual, dict):
                add_pair(manual.get("document_id"), manual.get("version_id"))

    for manual in execution_context.get("resolved_manuals") or []:
        if isinstance(manual, dict):
            add_pair(manual.get("document_id"), manual.get("version_id"))

    add_pair(run.get("document_id"), run.get("version_id"))
    return pairs


def _manual_refs_for_pairs(engine: Engine, pairs: list[tuple[str, str]]) -> list[dict[str, Any]]:
    if not pairs:
        return []
    version_ids = [version_id for _document_id, version_id in pairs]
    placeholders = ", ".join(f":version_id_{index}" for index, _value in enumerate(version_ids))
    params = {f"version_id_{index}": value for index, value in enumerate(version_ids)}
    rows_by_version_id: dict[str, dict[str, Any]] = {}
    with engine.connect() as conn:
        query = text(
            f"""
            SELECT d.id AS document_id,
                   d.tenant_id AS tenant_id,
                   v.id AS version_id,
                   d.display_name AS document_label,
                   d.display_name AS display_name,
                   d.source_filename AS source_filename,
                   v.version_no AS version_no,
                   v.storage_path AS storage_path,
                   v.parsed_structure_path AS parsed_structure_path,
                   v.routing_index_status AS routing_index_status,
                   v.routing_index_path AS routing_index_path,
                   v.routing_index_version AS routing_index_version
            FROM document_versions v
            JOIN documents d ON d.id = v.document_id
            WHERE v.id IN ({placeholders})
            """
        )
        for row in conn.execute(query, params).mappings():
            rows_by_version_id[str(row["version_id"])] = dict(row)

    refs: list[dict[str, Any]] = []
    for document_id, version_id in pairs:
        row = rows_by_version_id.get(version_id) or {}
        ref = build_manual_gate_ref(
            document_id=str(row.get("document_id") or document_id),
            version_id=str(row.get("version_id") or version_id),
            document_label=row.get("document_label"),
            version_label=f"v{row.get('version_no')}" if row.get("version_no") is not None else None,
            display_name=row.get("display_name"),
            source_filename=row.get("source_filename"),
            storage_path=row.get("storage_path"),
            parsed_structure_path=row.get("parsed_structure_path"),
            routing_index_status=row.get("routing_index_status"),
            routing_index_path=row.get("routing_index_path"),
            routing_index_version=row.get("routing_index_version"),
        )
        if row.get("tenant_id"):
            ref["tenant_id"] = str(row.get("tenant_id"))
        refs.append(ref)
    return refs


def _input_payload_from_run(
    *,
    run_kind: str,
    run: dict[str, Any],
    engine: Engine,
    args: argparse.Namespace,
) -> dict[str, Any] | None:
    execution_context = _json_loads(run.get("execution_context_json"), {})
    if not isinstance(execution_context, dict):
        return None
    retrieval = execution_context.get("retrieval") if isinstance(execution_context, dict) else {}
    diagnostics = retrieval.get("diagnostics") if isinstance(retrieval, dict) else {}
    manual_gate = diagnostics.get("manual_gate") if isinstance(diagnostics, dict) else None
    if not isinstance(manual_gate, dict):
        return None

    manual_pairs = _manual_pairs_from_execution_context(run, execution_context)
    manual_refs = _manual_refs_for_pairs(engine, manual_pairs)
    if not manual_refs:
        return None

    metrics = _json_loads(run.get("metrics_json"), {})
    citations = _json_loads(run.get("citations_json"), [])
    retrieval_query = retrieval.get("query") if isinstance(retrieval, dict) else None
    if not retrieval_query:
        retrieval_query = run.get("question")

    top_k = args.top_k
    if top_k is None and isinstance(retrieval, dict):
        top_k = retrieval.get("top_k") or retrieval.get("global_top_k")
    candidate_top_k = args.candidate_top_k
    if candidate_top_k is None and isinstance(retrieval, dict):
        candidate_top_k = retrieval.get("candidate_top_k") or retrieval.get("per_document_top_k")

    return {
        "run_kind": run_kind,
        "run_id": run.get("id"),
        "status": run.get("status"),
        "created_at": run.get("created_at").isoformat() if hasattr(run.get("created_at"), "isoformat") else run.get("created_at"),
        "question": run.get("question"),
        "retrieval_query": retrieval_query,
        "top_k": top_k or max(len(citations), 1),
        "candidate_top_k": candidate_top_k or max(len(citations), 8),
        "manual_gate_result": {
            "applied_manuals": manual_refs,
            "diagnostics": manual_gate,
        },
        "outline_diagnostics": diagnostics.get("outline") if isinstance(diagnostics, dict) else None,
        "final_citations": citations if isinstance(citations, list) else [],
        "retrieve_candidates_latency_ms": metrics.get("retrieve_ms") if isinstance(metrics, dict) else None,
        "embedding_mode": args.embedding_mode,
        "dense_source": args.dense_source,
    }


def _load_json_file(path: str | None, fallback: Any) -> Any:
    if not path:
        return fallback
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _dense_search_backend(args: argparse.Namespace):
    if args.dense_source in {"sparse", "off"}:
        return None
    if args.dense_source == "artifact-exact":
        return ExactScanNodeDenseSearchBackend()
    if args.dense_source == "es-shadow":
        return EsNodeDenseSearchBackend()
    return None


def _run_input_payload(args: argparse.Namespace, engine: Engine, SessionLocal: sessionmaker) -> list[dict[str, Any]]:
    payload = _load_json_file(args.input, {})
    if args.top_k is not None and "top_k" not in payload:
        payload["top_k"] = args.top_k
    if args.candidate_top_k is not None and "candidate_top_k" not in payload:
        payload["candidate_top_k"] = args.candidate_top_k
    if args.embedding_mode is not None and "embedding_mode" not in payload:
        payload["embedding_mode"] = args.embedding_mode
    if args.dense_source is not None and "dense_source" not in payload:
        payload["dense_source"] = args.dense_source
    dense_scores = _load_json_file(args.dense_scores, None)
    node_corpora = payload.get("node_corpora") if isinstance(payload.get("node_corpora"), list) else None
    dense_backend = None if dense_scores is not None else _dense_search_backend(args)
    with SessionLocal() as db:
        return [
            run_node_shadow_replay(
                db,
                payload,
                dense_scores=dense_scores,
                dense_search_backend=dense_backend,
                node_corpora=node_corpora,
            )
        ]


def _run_database_replay(args: argparse.Namespace, engine: Engine, SessionLocal: sessionmaker) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    run_rows, scan_errors = _run_records(args, engine)
    dense_scores = _load_json_file(args.dense_scores, None)
    dense_backend = None if dense_scores is not None else _dense_search_backend(args)
    scanned_run_count = 0
    skipped_run_count = 0
    with SessionLocal() as db:
        for run_kind, run in run_rows:
            scanned_run_count += 1
            payload = _input_payload_from_run(run_kind=run_kind, run=run, engine=engine, args=args)
            if payload is None:
                skipped_run_count += 1
                continue
            reports.append(
                run_node_shadow_replay(
                    db,
                    payload,
                    dense_scores=dense_scores,
                    dense_search_backend=dense_backend,
                )
            )
            if len(reports) >= args.sample_limit:
                break
    scan = {
        "run_count_scanned": scanned_run_count,
        "run_count_reported": len(reports),
        "run_count_skipped": skipped_run_count,
        "scan_errors": scan_errors,
    }
    return reports, scan


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return round(mean(values), 6)


def _metric_value(report: dict[str, Any], metric_name: str) -> float | None:
    metric = ((report.get("metrics") or {}).get(metric_name) or {})
    value = metric.get("value")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _aggregate_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
    dense_fallback_counts: Counter[str] = Counter()
    corpus_source_counts: Counter[str] = Counter()
    fallback_source_counts: Counter[str] = Counter()
    artifact_status_counts: Counter[str] = Counter()
    zero_hit_rates: list[float] = []
    fallback_needed_rates: list[float] = []
    outline_overlap_values: list[float] = []
    citation_recall_values: list[float] = []
    shadow_latencies: list[int] = []
    latency_deltas: list[int] = []
    dense_enabled_count = 0
    artifact_occurrence_count = 0
    artifact_available_count = 0
    artifact_built_count = 0
    artifact_written_count = 0

    for report in reports:
        dense = report.get("dense") or {}
        if dense.get("enabled"):
            dense_enabled_count += 1
        fallback_reason = dense.get("fallback_reason")
        if fallback_reason:
            dense_fallback_counts[str(fallback_reason)] += 1
        for artifact in dense.get("artifacts") or []:
            if not isinstance(artifact, dict):
                continue
            artifact_occurrence_count += 1
            if artifact.get("available"):
                artifact_available_count += 1
            if artifact.get("built"):
                artifact_built_count += 1
            if artifact.get("written"):
                artifact_written_count += 1
            status = artifact.get("artifact_status") or "legacy_or_unknown"
            artifact_status_counts[str(status)] += 1
        for source, count in ((report.get("corpus_summary") or {}).get("source_counts") or {}).items():
            corpus_source_counts[str(source)] += int(count or 0)
        metrics = report.get("metrics") or {}
        zero_hit = _metric_value(report, "zero_hit_rate")
        if zero_hit is not None:
            zero_hit_rates.append(zero_hit)
        fallback_needed = _metric_value(report, "fallback_needed_rate")
        if fallback_needed is not None:
            fallback_needed_rates.append(fallback_needed)
        outline_overlap = _metric_value(report, "node_topk_overlap_with_outline")
        if outline_overlap is not None:
            outline_overlap_values.append(outline_overlap)
        citation_recall = _metric_value(report, "node_topk_recall_of_final_citation_nodes")
        if citation_recall is not None:
            citation_recall_values.append(citation_recall)
        fallback_by_source = ((metrics.get("fallback_needed_rate") or {}).get("by_source") or {})
        for source, count in fallback_by_source.items():
            fallback_source_counts[str(source)] += int(count or 0)
        latency = metrics.get("latency_delta") or {}
        if latency.get("node_shadow_latency_ms") is not None:
            shadow_latencies.append(int(latency.get("node_shadow_latency_ms") or 0))
        if latency.get("delta_ms") is not None:
            latency_deltas.append(int(latency.get("delta_ms") or 0))

    return {
        "run_count": len(reports),
        "dense_enabled_count": dense_enabled_count,
        "artifact_occurrence_count": artifact_occurrence_count,
        "artifact_available_count": artifact_available_count,
        "artifact_built_count": artifact_built_count,
        "artifact_written_count": artifact_written_count,
        "artifact_status_counts": _counter_dict(artifact_status_counts),
        "metrics": {
            "node_topk_overlap_with_outline": {"avg_value": _avg(outline_overlap_values)},
            "node_topk_recall_of_final_citation_nodes": {"avg_value": _avg(citation_recall_values)},
            "hybrid_vs_lexical_gain": {
                "avg_value": _avg(
                    [
                        float((report.get("metrics") or {}).get("hybrid_vs_lexical_gain", {}).get("value"))
                        for report in reports
                        if (report.get("metrics") or {}).get("hybrid_vs_lexical_gain", {}).get("value") is not None
                    ]
                ),
                "skipped_reason_counts": _counter_dict(dense_fallback_counts),
            },
            "latency_delta": {
                "node_shadow_latency_ms_avg": _avg([float(value) for value in shadow_latencies]),
                "delta_ms_avg": _avg([float(value) for value in latency_deltas]),
            },
            "zero_hit_rate": {"avg_value": _avg(zero_hit_rates)},
            "fallback_needed_rate": {
                "avg_value": _avg(fallback_needed_rates),
                "by_source": _counter_dict(fallback_source_counts),
            },
        },
        "corpus_source_counts": _counter_dict(corpus_source_counts),
        "dense_fallback_counts": _counter_dict(dense_fallback_counts),
    }


def _es_check_snapshot(settings: Any) -> dict[str, Any]:
    """Report ES availability, index list, and doc counts for the report.

    Returns a diagnostic dict suitable for embedding in the runtime snapshot.
    Never raises; all errors are captured in the return value.
    """
    es_enabled = bool(getattr(settings, "routing_node_es_enabled", False))
    index_prefix = getattr(settings, "routing_node_es_index_prefix", None) or "pageindex-node-embeddings"
    result: dict[str, Any] = {
        "es_enabled": es_enabled,
        "es_available": False,
        "unavailable_reason": None,
        "index_prefix": index_prefix,
        "indices": [],
        "real_es_verified": False,
    }
    if not es_enabled:
        result["unavailable_reason"] = "es_disabled"
        return result
    try:
        from elasticsearch import Elasticsearch  # type: ignore
    except ImportError:
        result["unavailable_reason"] = "es_dependency_unavailable"
        return result
    url = (getattr(settings, "routing_node_es_url", "") or "").strip()
    if not url:
        result["unavailable_reason"] = "es_url_missing"
        return result
    try:
        client = Elasticsearch(url)
        ping_ok = bool(client.ping())
    except Exception as exc:
        result["unavailable_reason"] = f"es_client_error:{type(exc).__name__}"
        return result
    if not ping_ok:
        result["unavailable_reason"] = "es_ping_failed"
        return result
    result["es_available"] = True
    result["real_es_verified"] = True
    try:
        cat_response = client.cat.indices(index=f"{index_prefix}*", format="json")
        result["indices"] = [
            {
                "index": row.get("index"),
                "docs_count": row.get("docs.count"),
                "store_size": row.get("store.size"),
            }
            for row in (cat_response or [])
            if isinstance(row, dict)
        ]
    except Exception as exc:
        result["indices_error"] = str(exc)
    return result


def _runtime_snapshot() -> dict[str, Any]:
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
        "system_embedding_retry_base_seconds": embedding_options["retry_base_seconds"],
        "routing_embeddings_build_mode": settings.routing_embeddings_build_mode,
        "routing_node_es_enabled": bool(getattr(settings, "routing_node_es_enabled", False)),
        "routing_node_es_url": _masked_url(getattr(settings, "routing_node_es_url", "")),
        "routing_node_es_index_prefix": getattr(settings, "routing_node_es_index_prefix", None),
    }


def _runtime_snapshot_with_es_check(settings: Any | None = None) -> dict[str, Any]:
    """Return runtime snapshot augmented with ES check data."""
    snapshot = _runtime_snapshot()
    s = settings or get_settings()
    snapshot["es_check"] = _es_check_snapshot(s)
    return snapshot


def _build_report_payload(args: argparse.Namespace) -> dict[str, Any]:
    engine = _engine()
    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )
    try:
        if args.input:
            reports = _run_input_payload(args, engine, SessionLocal)
            scan = {"mode": "input", "run_count_reported": len(reports), "scan_errors": {}}
        else:
            reports, scan = _run_database_replay(args, engine, SessionLocal)
            scan["mode"] = "database"
    finally:
        engine.dispose()

    settings = get_settings()
    runtime = _runtime_snapshot_with_es_check(settings) if getattr(args, "es_check", False) else _runtime_snapshot()
    return {
        "schema_version": "node_shadow_eval_report_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "query": {
            "input": args.input,
            "run_kind": args.run_kind,
            "status": args.status,
            "limit": args.limit,
            "sample_limit": args.sample_limit,
            "top_k": args.top_k,
            "candidate_top_k": args.candidate_top_k,
            "embedding_mode": args.embedding_mode,
            "dense_source": args.dense_source,
        },
        "runtime": runtime,
        "scan": scan,
        "summary": _aggregate_reports(reports),
        "samples": reports,
    }


def _markdown_report(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    metrics = summary.get("metrics") or {}
    runtime = payload.get("runtime") or {}
    lines = [
        "# Node Shadow Eval Report",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- database_mode: {runtime.get('database_mode')}",
        f"- database_url: {runtime.get('database_url')}",
        f"- system_embedding_enabled: {runtime.get('system_embedding_enabled')}",
        f"- system_embedding_provider_type: {runtime.get('system_embedding_provider_type')}",
        f"- system_embedding_model: {runtime.get('system_embedding_model')}",
        f"- system_embedding_batch_size: {runtime.get('system_embedding_batch_size')}",
        f"- system_embedding_max_retries: {runtime.get('system_embedding_max_retries')}",
        f"- routing_embeddings_build_mode: {runtime.get('routing_embeddings_build_mode')}",
        f"- routing_node_es_enabled: {runtime.get('routing_node_es_enabled')}",
        f"- routing_node_es_url: {runtime.get('routing_node_es_url')}",
        f"- routing_node_es_index_prefix: {runtime.get('routing_node_es_index_prefix')}",
        f"- es_check_available: {(runtime.get('es_check') or {}).get('es_available')}",
        f"- es_check_real_verified: {(runtime.get('es_check') or {}).get('real_es_verified')}",
        f"- es_check_unavailable_reason: {(runtime.get('es_check') or {}).get('unavailable_reason')}",
        f"- es_index_count: {len((runtime.get('es_check') or {}).get('indices') or [])}",
        f"- run_count: {summary.get('run_count')}",
        f"- dense_enabled_count: {summary.get('dense_enabled_count')}",
        f"- artifact_status_counts: {json.dumps(summary.get('artifact_status_counts') or {}, ensure_ascii=False, sort_keys=True)}",
        "",
        "## Metrics",
        "",
        f"- node_topk_overlap_with_outline avg: {(metrics.get('node_topk_overlap_with_outline') or {}).get('avg_value')}",
        f"- node_topk_recall_of_final_citation_nodes avg: {(metrics.get('node_topk_recall_of_final_citation_nodes') or {}).get('avg_value')}",
        f"- hybrid_vs_lexical_gain avg: {(metrics.get('hybrid_vs_lexical_gain') or {}).get('avg_value')}",
        f"- latency node_shadow avg ms: {(metrics.get('latency_delta') or {}).get('node_shadow_latency_ms_avg')}",
        f"- zero_hit_rate avg: {(metrics.get('zero_hit_rate') or {}).get('avg_value')}",
        f"- fallback_needed_rate avg: {(metrics.get('fallback_needed_rate') or {}).get('avg_value')}",
        "",
        "## Fallbacks",
        "",
        f"- corpus_source_counts: {json.dumps(summary.get('corpus_source_counts') or {}, ensure_ascii=False, sort_keys=True)}",
        f"- dense_fallback_counts: {json.dumps(summary.get('dense_fallback_counts') or {}, ensure_ascii=False, sort_keys=True)}",
        f"- fallback_by_source: {json.dumps((metrics.get('fallback_needed_rate') or {}).get('by_source') or {}, ensure_ascii=False, sort_keys=True)}",
    ]
    return "\n".join(lines) + "\n"


def _write_output(path: str | None, payload: dict[str, Any], report_format: str) -> None:
    if report_format == "markdown":
        serialized = _markdown_report(payload)
    else:
        serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    if not path:
        print(serialized)
        return
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(serialized, encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Offline node shadow scorer replay for manual-gate runs.")
    parser.add_argument("--input", help="JSON payload with question plus manuals/manual_gate_result.")
    parser.add_argument("--dense-scores", help="Optional JSON map of node_key to dense score for hybrid scaffold testing.")
    parser.add_argument(
        "--dense-source",
        choices=("sparse", "off", "artifact-exact", "es-shadow"),
        default="sparse",
        help="Dense source for shadow scoring: sparse/off, artifact exact scan, or ES shadow backend.",
    )
    parser.add_argument("--run-kind", choices=("all", "chat", "compliance"), default="all")
    parser.add_argument("--status", default="completed")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--sample-limit", type=int, default=20)
    parser.add_argument("--top-k", type=int)
    parser.add_argument("--candidate-top-k", type=int)
    parser.add_argument("--embedding-mode", choices=("auto", "off", "provider", "system"), default="off")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--output")
    parser.add_argument(
        "--es-check",
        action="store_true",
        default=False,
        help="Include ES availability/index/synced count in the report runtime snapshot.",
    )
    args = parser.parse_args(argv)

    payload = _build_report_payload(args)
    _write_output(args.output, payload, args.format)


if __name__ == "__main__":
    main()
