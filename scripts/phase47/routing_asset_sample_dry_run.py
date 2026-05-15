#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from scripts.phase47.routing_asset_maintenance import (
    ROOT,
    _create_engine,
    _database_url_from_args,
    _display_database_url,
    _normalize_text,
    _rate,
    inspect_runtime_schema,
)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")


def _emit(args: argparse.Namespace, payload: dict[str, Any]) -> None:
    output = getattr(args, "output", None)
    if output:
        _write_json_file(Path(output), payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))


def _row_to_dict(row: Any) -> dict[str, Any]:
    return dict(row._mapping)


def _load_candidate_records(engine: Engine, *, sample_limit: int) -> list[dict[str, Any]]:
    query = sa.text(
        """
        SELECT
            d.id AS document_id,
            d.tenant_id AS tenant_id,
            d.workspace_id AS workspace_id,
            d.display_name AS display_name,
            d.source_filename AS source_filename,
            dv.id AS version_id,
            dv.version_no AS version_no,
            dv.parse_status AS parse_status,
            dv.parsed_structure_path AS parsed_structure_path,
            dv.routing_index_status AS routing_index_status,
            dv.routing_index_path AS routing_index_path,
            dv.routing_index_error AS routing_index_error,
            dv.routing_index_version AS routing_index_version,
            COUNT(rn.id) AS existing_routing_node_count,
            SUM(
                CASE
                    WHEN rn.id IS NOT NULL AND TRIM(COALESCE(rn.route_summary, '')) <> '' THEN 1
                    ELSE 0
                END
            ) AS existing_summary_count
        FROM document_versions dv
        JOIN documents d ON d.id = dv.document_id
        LEFT JOIN document_routing_nodes rn ON rn.version_id = dv.id
        WHERE dv.parse_status = 'index_ready'
          AND dv.parsed_structure_path IS NOT NULL
          AND TRIM(dv.parsed_structure_path) <> ''
        GROUP BY
            d.id,
            d.tenant_id,
            d.workspace_id,
            d.display_name,
            d.source_filename,
            dv.id,
            dv.version_no,
            dv.parse_status,
            dv.parsed_structure_path,
            dv.routing_index_status,
            dv.routing_index_path,
            dv.routing_index_error,
            dv.routing_index_version,
            dv.created_at
        ORDER BY
            CASE
                WHEN d.source_filename LIKE '%operations_manual%' THEN 0
                WHEN d.source_filename LIKE '%Guide%' THEN 1
                WHEN d.source_filename LIKE '%manual%' THEN 2
                WHEN d.source_filename LIKE '%mineru%' THEN 3
                ELSE 4
            END ASC,
            d.created_at DESC,
            dv.created_at DESC,
            dv.id ASC
        """
    )
    with engine.connect() as conn:
        rows = [_row_to_dict(row) for row in conn.execute(query).all()]

    selected: list[dict[str, Any]] = []
    seen_filenames: set[str] = set()
    for record in rows:
        filename = str(record.get("source_filename") or record.get("display_name") or "")
        if filename in seen_filenames:
            continue
        selected.append(record)
        seen_filenames.add(filename)
        if len(selected) >= sample_limit:
            return selected

    for record in rows:
        if record in selected:
            continue
        selected.append(record)
        if len(selected) >= sample_limit:
            break
    return selected


def _load_structure(path: str) -> tuple[list[dict] | dict, str | None]:
    from app.services.storage_service import read_json_artifact

    parsed = read_json_artifact(path)
    if isinstance(parsed, dict):
        return parsed.get("structure") or [], _normalize_text(parsed.get("doc_name"))
    return parsed, None


def _build_payload(record: dict[str, Any]) -> dict[str, Any]:
    from app.services.pageindex_service import RoutingBuildOptions, build_routing_index_payload

    parsed_structure_path = _normalize_text(record.get("parsed_structure_path"))
    if parsed_structure_path is None:
        raise RuntimeError("parsed_structure_path is missing")
    structure, source_doc_name = _load_structure(parsed_structure_path)
    document_label = (
        _normalize_text(record.get("display_name"))
        or _normalize_text(record.get("source_filename"))
        or "Document"
    )
    return build_routing_index_payload(
        structure,
        document_label=document_label,
        document_id=str(record["document_id"]),
        version_id=str(record["version_id"]),
        source_doc_name=source_doc_name or _normalize_text(record.get("source_filename")),
        routing_index_version=_normalize_text(record.get("routing_index_version")) or "v1",
        build_options=RoutingBuildOptions.disabled(),
    )


def _summarize_record(record: dict[str, Any], payload: dict[str, Any] | None, *, error: str | None = None) -> dict[str, Any]:
    node_count = int((payload or {}).get("node_count") or 0)
    coverage = (((payload or {}).get("build_metadata") or {}).get("summary_coverage") or {})
    summary_count = int(coverage.get("summary_count") or 0)
    missing_summary_count = int(coverage.get("missing_summary_count") or max(node_count - summary_count, 0))
    existing_node_count = int(record.get("existing_routing_node_count") or 0)
    existing_summary_count = int(record.get("existing_summary_count") or 0)
    existing_missing_summary_count = max(existing_node_count - existing_summary_count, 0)
    routing_index_path_present = _normalize_text(record.get("routing_index_path")) is not None
    preexisting_missing = (
        record.get("parse_status") == "index_ready"
        and (_normalize_text(record.get("routing_index_status")) != "index_ready" or not routing_index_path_present)
    )
    return {
        "file_name": record.get("source_filename") or record.get("display_name"),
        "document_id": record.get("document_id"),
        "version_id": record.get("version_id"),
        "parse_status": record.get("parse_status"),
        "build_success": error is None and payload is not None,
        "node_count": node_count,
        "summary_count": summary_count,
        "missing_summary_count": missing_summary_count,
        "coverage_ratio": coverage.get("coverage_ratio") if coverage else _rate(summary_count, node_count),
        "readiness": (payload or {}).get("readiness"),
        "routing_index_status": record.get("routing_index_status"),
        "routing_index_path_present": routing_index_path_present,
        "preexisting_routing_node_count": existing_node_count,
        "preexisting_summary_count": existing_summary_count,
        "preexisting_missing_summary_count": existing_missing_summary_count,
        "preexisting_missing": preexisting_missing,
        "error": error,
        "skipped_reason": None if error is None else "build_failed",
    }


def _routing_rows(document_id: str, version_id: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    now = datetime.utcnow()
    rows: list[dict[str, Any]] = []
    for node in payload.get("nodes") or []:
        rows.append(
            {
                "id": str(uuid.uuid4()),
                "document_id": document_id,
                "version_id": version_id,
                "node_id": node.get("node_id"),
                "parent_node_id": node.get("parent_node_id"),
                "depth": int(node.get("depth") or 0),
                "title": node.get("title"),
                "breadcrumb": node.get("breadcrumb"),
                "page_start": node.get("page_start"),
                "page_end": node.get("page_end"),
                "route_summary": node.get("route_summary"),
                "contrastive_summary": node.get("contrastive_summary"),
                "aliases_json": node.get("aliases_json"),
                "keywords_json": node.get("keywords_json"),
                "manual_profile_text": node.get("manual_profile_text"),
                "created_at": now,
                "updated_at": now,
            }
        )
    return rows


def _count_rows(conn: sa.Connection, version_id: str) -> int:
    value = conn.execute(
        sa.text("SELECT COUNT(*) FROM document_routing_nodes WHERE version_id = :version_id"),
        {"version_id": version_id},
    ).scalar()
    return int(value or 0)


def _row_ids(conn: sa.Connection, version_id: str) -> set[str]:
    rows = conn.execute(
        sa.text("SELECT id FROM document_routing_nodes WHERE version_id = :version_id"),
        {"version_id": version_id},
    ).all()
    return {str(row[0]) for row in rows}


def _replace_rows_once(conn: sa.Connection, *, document_id: str, version_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    rows = _routing_rows(document_id, version_id, payload)
    delete_result = conn.execute(
        sa.text("DELETE FROM document_routing_nodes WHERE version_id = :version_id"),
        {"version_id": version_id},
    )
    if rows:
        conn.execute(
            sa.text(
                """
                INSERT INTO document_routing_nodes (
                    id, document_id, version_id, node_id, parent_node_id, depth, title, breadcrumb,
                    page_start, page_end, route_summary, contrastive_summary, aliases_json,
                    keywords_json, manual_profile_text, created_at, updated_at
                )
                VALUES (
                    :id, :document_id, :version_id, :node_id, :parent_node_id, :depth, :title, :breadcrumb,
                    :page_start, :page_end, :route_summary, :contrastive_summary, :aliases_json,
                    :keywords_json, :manual_profile_text, :created_at, :updated_at
                )
                """
            ),
            rows,
        )
    return {
        "deleted_count": int(delete_result.rowcount or 0),
        "inserted_count": len(rows),
        "post_replace_count": _count_rows(conn, version_id),
        "row_ids": sorted(_row_ids(conn, version_id)),
    }


def _idempotency_check(engine: Engine, record: dict[str, Any], first_payload: dict[str, Any]) -> dict[str, Any]:
    second_payload = _build_payload(record)
    version_id = str(record["version_id"])
    document_id = str(record["document_id"])
    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            pre_count = _count_rows(conn, version_id)
            first_replace = _replace_rows_once(
                conn,
                document_id=document_id,
                version_id=version_id,
                payload=first_payload,
            )
            second_replace = _replace_rows_once(
                conn,
                document_id=document_id,
                version_id=version_id,
                payload=second_payload,
            )
            post_second_count = _count_rows(conn, version_id)
            first_ids = set(first_replace["row_ids"])
            second_ids = set(second_replace["row_ids"])
            stable_node_count = int(first_payload.get("node_count") or 0) == int(second_payload.get("node_count") or 0)
            stable_readiness = first_payload.get("readiness") == second_payload.get("readiness")
            replaced_not_appended = (
                first_replace["post_replace_count"] == int(first_payload.get("node_count") or 0)
                and post_second_count == int(second_payload.get("node_count") or 0)
                and post_second_count != first_replace["post_replace_count"] * 2
                and not (first_ids & second_ids)
            )
            return {
                "status": "passed" if stable_node_count and stable_readiness and replaced_not_appended else "failed",
                "mode": "transactional_rollback_no_storage_write",
                "document_id": document_id,
                "version_id": version_id,
                "file_name": record.get("source_filename") or record.get("display_name"),
                "preexisting_row_count": pre_count,
                "first_build_node_count": int(first_payload.get("node_count") or 0),
                "second_build_node_count": int(second_payload.get("node_count") or 0),
                "first_readiness": first_payload.get("readiness"),
                "second_readiness": second_payload.get("readiness"),
                "first_replace": {
                    "deleted_count": first_replace["deleted_count"],
                    "inserted_count": first_replace["inserted_count"],
                    "post_replace_count": first_replace["post_replace_count"],
                },
                "second_replace": {
                    "deleted_count": second_replace["deleted_count"],
                    "inserted_count": second_replace["inserted_count"],
                    "post_replace_count": second_replace["post_replace_count"],
                },
                "stable_node_count": stable_node_count,
                "stable_readiness": stable_readiness,
                "replaced_not_appended": replaced_not_appended,
                "rolled_back": True,
            }
        finally:
            transaction.rollback()


def _download_pdf_candidates(limit: int = 10) -> list[dict[str, Any]]:
    downloads = Path("/Users/shaoqing/Downloads")
    if not downloads.exists():
        return []
    candidates = []
    for path in downloads.glob("**/*"):
        if path.is_file() and path.suffix.lower() == ".pdf":
            try:
                stat = path.stat()
            except OSError:
                continue
            candidates.append(
                {
                    "file_name": path.name,
                    "path": str(path),
                    "size_bytes": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                }
            )
    candidates.sort(key=lambda item: int(item["size_bytes"]), reverse=True)
    return candidates[:limit]


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    database_url = _database_url_from_args(args)
    display_database_url = _display_database_url(database_url)
    engine = _create_engine(database_url)
    try:
        schema = inspect_runtime_schema(engine)
        payload: dict[str, Any] = {
            "status": "blocked" if schema["status"] != "ready" else "dry_run_completed",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "repository_root": str(ROOT),
            "database_url": display_database_url,
            "schema": schema,
            "dry_run": True,
            "mutates_storage": False,
            "commits_database": False,
            "sample_source": "existing_db_index_ready_versions_with_parsed_structure",
            "download_pdf_candidates": _download_pdf_candidates(),
            "samples": [],
            "totals": {
                "sample_count": 0,
                "success_count": 0,
                "failure_count": 0,
                "missing_count": 0,
                "skipped_count": 0,
            },
            "idempotency": None,
        }
        if schema["status"] != "ready":
            return payload

        records = _load_candidate_records(engine, sample_limit=int(args.sample_limit))
        successful_payloads: list[tuple[dict[str, Any], dict[str, Any]]] = []
        samples: list[dict[str, Any]] = []
        for record in records:
            try:
                routing_payload = _build_payload(record)
                samples.append(_summarize_record(record, routing_payload))
                successful_payloads.append((record, routing_payload))
            except Exception as exc:
                samples.append(_summarize_record(record, None, error=f"{type(exc).__name__}: {exc}"))

        success_count = sum(1 for sample in samples if sample["build_success"])
        failure_count = sum(1 for sample in samples if not sample["build_success"] and sample.get("error"))
        missing_count = sum(1 for sample in samples if sample.get("preexisting_missing"))
        skipped_count = max(0, int(args.sample_limit) - len(samples))
        payload["samples"] = samples
        payload["totals"] = {
            "sample_count": len(samples),
            "success_count": success_count,
            "failure_count": failure_count,
            "missing_count": missing_count,
            "skipped_count": skipped_count,
        }
        if successful_payloads:
            record, routing_payload = successful_payloads[0]
            payload["idempotency"] = _idempotency_check(engine, record, routing_payload)
        else:
            payload["idempotency"] = {"status": "skipped", "reason": "no_successful_sample_build"}
        return payload
    finally:
        engine.dispose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dry-run routing asset sample build validation")
    parser.add_argument("--database-url", help="Override DATABASE_URL for this tool run")
    parser.add_argument("--sample-limit", type=int, default=5)
    parser.add_argument("--output", help="Optional JSON output path")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    payload = build_report(args)
    _emit(args, payload)
    return 2 if payload["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
