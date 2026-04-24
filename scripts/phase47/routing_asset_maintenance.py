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
from sqlalchemy.orm import Session


ROOT = Path(__file__).resolve().parents[2]
REBUILD_HINT = "先执行 `uv run python scripts/phase47/runtime_reset.py rebuild`，确认 DB 已迁移到 Alembic head 后再重试。"

REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "alembic_version": ("version_num",),
    "documents": (
        "id",
        "tenant_id",
        "workspace_id",
        "owner_user_id",
        "display_name",
        "source_filename",
        "active_version_id",
        "status",
        "created_at",
    ),
    "document_versions": (
        "id",
        "document_id",
        "version_no",
        "storage_path",
        "file_hash",
        "parse_status",
        "parsed_structure_path",
        "routing_index_status",
        "routing_index_path",
        "routing_index_error",
        "routing_index_version",
        "created_at",
    ),
    "document_routing_nodes": (
        "id",
        "document_id",
        "version_id",
        "node_id",
        "parent_node_id",
        "depth",
        "title",
        "breadcrumb",
        "page_start",
        "page_end",
        "route_summary",
        "contrastive_summary",
        "aliases_json",
        "keywords_json",
        "manual_profile_text",
        "created_at",
        "updated_at",
    ),
}

ROUTING_NODE_COLUMNS = REQUIRED_COLUMNS["document_routing_nodes"]
MUTATED_TABLES = ("document_versions", "document_routing_nodes")


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))


def _write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")


def _emit(args: argparse.Namespace, payload: dict[str, Any]) -> None:
    output = getattr(args, "output", None)
    if output:
        _write_json_file(Path(output), payload)
    _print_json(payload)


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _migration_head() -> str | None:
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory
    except ModuleNotFoundError:
        return None

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    heads = sorted(ScriptDirectory.from_config(config).get_heads())
    if len(heads) == 1:
        return heads[0]
    return ",".join(heads) if heads else None


def _current_revisions(engine: Engine, inspector: sa.Inspector) -> list[str]:
    if not inspector.has_table("alembic_version"):
        return []
    try:
        with engine.connect() as conn:
            return sorted(
                str(row[0])
                for row in conn.execute(sa.text("SELECT version_num FROM alembic_version")).all()
                if row[0] is not None
            )
    except Exception:
        return []


def inspect_runtime_schema(engine: Engine) -> dict[str, Any]:
    inspector = sa.inspect(engine)
    existing_tables = set(inspector.get_table_names())
    missing_tables = sorted(set(REQUIRED_COLUMNS) - existing_tables)
    missing_columns: dict[str, list[str]] = {}

    for table_name, required_columns in REQUIRED_COLUMNS.items():
        if table_name not in existing_tables:
            continue
        existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
        missing = sorted(set(required_columns) - existing_columns)
        if missing:
            missing_columns[table_name] = missing

    head_revision = _migration_head()
    current_revisions = _current_revisions(engine, inspector)
    revision_ready = bool(head_revision and current_revisions == [head_revision])
    status = "ready"
    reasons: list[str] = []
    if missing_tables:
        status = "blocked"
        reasons.append("missing_required_tables")
    if missing_columns:
        status = "blocked"
        reasons.append("missing_required_columns")
    if not revision_ready:
        status = "blocked"
        reasons.append("database_not_at_alembic_head")

    return {
        "status": status,
        "head_revision": head_revision,
        "current_revisions": current_revisions,
        "missing_tables": missing_tables,
        "missing_columns": missing_columns,
        "reasons": reasons,
        "next_step": None if status == "ready" else REBUILD_HINT,
    }


def _database_url_from_args(args: argparse.Namespace) -> str:
    database_url = getattr(args, "database_url", None)
    if database_url:
        return database_url
    from app.core.config import get_settings

    return get_settings().database_url


def _display_database_url(database_url: str) -> str:
    try:
        return sa.engine.make_url(database_url).render_as_string(hide_password=True)
    except Exception:
        return database_url


def _create_engine(database_url: str) -> Engine:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return sa.create_engine(database_url, future=True, connect_args=connect_args)


def _row_to_dict(row: Any) -> dict[str, Any]:
    return dict(row._mapping)


def _load_version_records(engine: Engine, *, summary_threshold: float) -> list[dict[str, Any]]:
    query = sa.text(
        """
        SELECT
            d.id AS document_id,
            d.tenant_id AS tenant_id,
            d.workspace_id AS workspace_id,
            d.display_name AS display_name,
            d.source_filename AS source_filename,
            d.status AS document_status,
            dv.id AS version_id,
            dv.version_no AS version_no,
            dv.storage_path AS storage_path,
            dv.parse_status AS parse_status,
            dv.parsed_structure_path AS parsed_structure_path,
            dv.routing_index_status AS routing_index_status,
            dv.routing_index_path AS routing_index_path,
            dv.routing_index_error AS routing_index_error,
            dv.routing_index_version AS routing_index_version,
            dv.created_at AS version_created_at,
            COUNT(rn.id) AS routing_node_count,
            SUM(
                CASE
                    WHEN rn.id IS NOT NULL AND TRIM(COALESCE(rn.route_summary, '')) <> '' THEN 1
                    ELSE 0
                END
            ) AS summary_count
        FROM document_versions dv
        JOIN documents d ON d.id = dv.document_id
        LEFT JOIN document_routing_nodes rn ON rn.version_id = dv.id
        GROUP BY
            d.id,
            d.tenant_id,
            d.workspace_id,
            d.display_name,
            d.source_filename,
            d.status,
            dv.id,
            dv.version_no,
            dv.storage_path,
            dv.parse_status,
            dv.parsed_structure_path,
            dv.routing_index_status,
            dv.routing_index_path,
            dv.routing_index_error,
            dv.routing_index_version,
            dv.created_at
        ORDER BY d.created_at ASC, dv.created_at ASC, dv.id ASC
        """
    )
    records: list[dict[str, Any]] = []
    with engine.connect() as conn:
        rows = conn.execute(query).all()

    for row in rows:
        record = _row_to_dict(row)
        node_count = int(record.get("routing_node_count") or 0)
        summary_count = int(record.get("summary_count") or 0)
        missing_summary_count = max(node_count - summary_count, 0)
        summary_coverage_ratio = _rate(summary_count, node_count)
        eligible = record.get("parse_status") == "index_ready"
        path_present = _normalize_text(record.get("routing_index_path")) is not None
        routing_status = _normalize_text(record.get("routing_index_status")) or "unknown"
        ready = eligible and routing_status == "index_ready" and path_present and node_count > 0
        failed = eligible and routing_status == "failed"
        if not eligible:
            state = "not_index_ready"
        elif ready:
            state = "ready"
        elif failed:
            state = "failed"
        else:
            state = "missing"

        issue_flags: list[str] = []
        if eligible and routing_status == "failed":
            issue_flags.append("routing_index_failed")
        if eligible and not path_present:
            issue_flags.append("missing_routing_index_path")
        if eligible and node_count == 0:
            issue_flags.append("missing_routing_node_rows")
        if eligible and not _normalize_text(record.get("parsed_structure_path")):
            issue_flags.append("missing_parsed_structure_path")
        if eligible and node_count > 0 and summary_coverage_ratio < summary_threshold:
            issue_flags.append("low_summary_coverage")

        record.update(
            {
                "eligible_for_routing_asset": eligible,
                "routing_asset_state": state,
                "routing_index_path_present": path_present,
                "routing_node_count": node_count,
                "summary_count": summary_count,
                "missing_summary_count": missing_summary_count,
                "summary_coverage_ratio": summary_coverage_ratio,
                "summary_coverage_threshold": summary_threshold,
                "issue_flags": issue_flags,
            }
        )
        records.append(record)
    return records


def _sample_records(records: list[dict[str, Any]], *, sample_limit: int) -> dict[str, list[dict[str, Any]]]:
    sample_limit = max(0, min(int(sample_limit), 100))

    def summarize(record: dict[str, Any]) -> dict[str, Any]:
        return {
            "tenant_id": record.get("tenant_id"),
            "workspace_id": record.get("workspace_id"),
            "document_id": record.get("document_id"),
            "version_id": record.get("version_id"),
            "display_name": record.get("display_name"),
            "source_filename": record.get("source_filename"),
            "parse_status": record.get("parse_status"),
            "routing_index_status": record.get("routing_index_status"),
            "routing_index_path_present": record.get("routing_index_path_present"),
            "routing_node_count": record.get("routing_node_count"),
            "summary_count": record.get("summary_count"),
            "missing_summary_count": record.get("missing_summary_count"),
            "summary_coverage_ratio": record.get("summary_coverage_ratio"),
            "issue_flags": record.get("issue_flags"),
        }

    return {
        "missing": [
            summarize(record)
            for record in records
            if record.get("routing_asset_state") == "missing"
        ][:sample_limit],
        "failed": [
            summarize(record)
            for record in records
            if record.get("routing_asset_state") == "failed"
        ][:sample_limit],
        "low_summary_coverage": [
            summarize(record)
            for record in records
            if "low_summary_coverage" in (record.get("issue_flags") or [])
        ][:sample_limit],
    }


def _mutation_target(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "tenant_id": record.get("tenant_id"),
        "workspace_id": record.get("workspace_id"),
        "document_id": record.get("document_id"),
        "version_id": record.get("version_id"),
        "version_no": record.get("version_no"),
        "parsed_structure_path": record.get("parsed_structure_path"),
        "current_routing_index_status": record.get("routing_index_status"),
        "current_routing_index_path": record.get("routing_index_path"),
        "issue_flags": record.get("issue_flags"),
    }


def _candidate_records(
    records: list[dict[str, Any]],
    *,
    include_low_summary: bool,
    max_versions: int | None = None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for record in records:
        if not record.get("eligible_for_routing_asset"):
            continue
        has_structure = _normalize_text(record.get("parsed_structure_path")) is not None
        if not has_structure:
            continue
        state = record.get("routing_asset_state")
        low_summary = "low_summary_coverage" in (record.get("issue_flags") or [])
        if state in {"missing", "failed"} or (include_low_summary and low_summary):
            candidates.append(record)
    if max_versions is not None:
        candidates = candidates[: max(0, int(max_versions))]
    return candidates


def _quality_summary(records: list[dict[str, Any]], *, summary_threshold: float) -> dict[str, Any]:
    eligible_records = [record for record in records if record.get("eligible_for_routing_asset")]
    ready_count = sum(1 for record in eligible_records if record.get("routing_asset_state") == "ready")
    missing_count = sum(1 for record in eligible_records if record.get("routing_asset_state") == "missing")
    failed_count = sum(1 for record in eligible_records if record.get("routing_asset_state") == "failed")
    node_count = sum(int(record.get("routing_node_count") or 0) for record in eligible_records)
    summary_count = sum(int(record.get("summary_count") or 0) for record in eligible_records)
    missing_summary_count = max(node_count - summary_count, 0)
    low_summary_count = sum(
        1 for record in eligible_records if "low_summary_coverage" in (record.get("issue_flags") or [])
    )
    return {
        "total_versions": len(records),
        "eligible_versions": len(eligible_records),
        "ready_count": ready_count,
        "missing_count": missing_count,
        "failed_count": failed_count,
        "low_summary_coverage_count": low_summary_count,
        "missing_rate": _rate(missing_count, len(eligible_records)),
        "failure_rate": _rate(failed_count, len(eligible_records)),
        "ready_rate": _rate(ready_count, len(eligible_records)),
        "summary_coverage": {
            "node_count": node_count,
            "summary_count": summary_count,
            "missing_summary_count": missing_summary_count,
            "coverage_ratio": _rate(summary_count, node_count),
            "threshold": summary_threshold,
        },
    }


def build_scan_report(
    engine: Engine,
    *,
    command: str = "scan",
    summary_threshold: float = 1.0,
    sample_limit: int = 20,
    include_low_summary: bool = False,
    max_versions: int | None = None,
    database_url: str | None = None,
) -> dict[str, Any]:
    schema = inspect_runtime_schema(engine)
    report: dict[str, Any] = {
        "status": "blocked" if schema["status"] != "ready" else "dry_run",
        "command": command,
        "dry_run": True,
        "execute_required_for_mutation": True,
        "repository_root": str(ROOT),
        "database_url": database_url,
        "schema": schema,
        "targets": {
            "repo_owned_tables_checked": sorted(REQUIRED_COLUMNS),
            "mutated_tables_when_executed": list(MUTATED_TABLES),
            "storage_artifact_when_executed": "documents/{document_id}/versions/{version_id}/routing_index.json",
        },
    }
    if schema["status"] != "ready":
        report["quality_summary"] = None
        report["sample_validation"] = None
        report["planned_mutations"] = {
            "status": "blocked",
            "reason": "schema_not_ready",
            "document_versions": [],
        }
        return report

    records = _load_version_records(engine, summary_threshold=summary_threshold)
    candidates = _candidate_records(
        records,
        include_low_summary=include_low_summary,
        max_versions=max_versions,
    )
    samples = _sample_records(records, sample_limit=sample_limit)
    quality = _quality_summary(records, summary_threshold=summary_threshold)
    report["quality_summary"] = quality
    report["sample_validation"] = {
        "sample_limit": max(0, min(int(sample_limit), 100)),
        "node_count": quality["summary_coverage"]["node_count"],
        "summary_coverage_ratio": quality["summary_coverage"]["coverage_ratio"],
        "failure_rate": quality["failure_rate"],
        "missing_rate": quality["missing_rate"],
        "samples": samples,
    }
    report["planned_mutations"] = {
        "status": "dry_run",
        "requires_execute": True,
        "include_low_summary": include_low_summary,
        "document_version_count": len(candidates),
        "document_versions": [_mutation_target(record) for record in candidates],
        "tables": list(MUTATED_TABLES),
        "rollback_manifest": "created only in --execute mode",
    }
    return report


def scan_payload(args: argparse.Namespace) -> dict[str, Any]:
    database_url = _database_url_from_args(args)
    display_database_url = _display_database_url(database_url)
    engine = _create_engine(database_url)
    try:
        return build_scan_report(
            engine,
            command=getattr(args, "command", "scan") or "scan",
            summary_threshold=float(getattr(args, "summary_threshold", 1.0)),
            sample_limit=int(getattr(args, "sample_limit", 20)),
            include_low_summary=bool(getattr(args, "include_low_summary", False)),
            max_versions=getattr(args, "max_versions", None),
            database_url=display_database_url,
        )
    finally:
        engine.dispose()


def _load_parsed_structure(path: str) -> tuple[list[dict] | dict, str | None]:
    from app.services.storage_service import read_json_artifact

    parsed = read_json_artifact(path)
    if isinstance(parsed, dict):
        return parsed.get("structure") or [], _normalize_text(parsed.get("doc_name"))
    return parsed, None


def _write_routing_index(*, tenant_id: str, document_id: str, version_id: str, routing_index: dict[str, Any]) -> str:
    from app.services.storage_service import write_document_routing_index

    return write_document_routing_index(
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        data=routing_index,
    )


def _routing_rows_from_payload(document_id: str, version_id: str, routing_index: dict[str, Any]) -> list[dict[str, Any]]:
    now = datetime.utcnow()
    rows: list[dict[str, Any]] = []
    for node in routing_index.get("nodes") or []:
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


def _previous_nodes(conn: sa.Connection, version_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not version_ids:
        return {}
    query = sa.text(
        f"""
        SELECT {", ".join(ROUTING_NODE_COLUMNS)}
        FROM document_routing_nodes
        WHERE version_id IN :version_ids
        ORDER BY version_id ASC, depth ASC, node_id ASC
        """
    ).bindparams(sa.bindparam("version_ids", expanding=True))
    nodes: dict[str, list[dict[str, Any]]] = {version_id: [] for version_id in version_ids}
    for row in conn.execute(query, {"version_ids": version_ids}).all():
        node = _row_to_dict(row)
        nodes.setdefault(str(node["version_id"]), []).append(node)
    return nodes


def _rollback_manifest_payload(
    *,
    database_url: str,
    schema: dict[str, Any],
    candidates: list[dict[str, Any]],
    previous_nodes: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    return {
        "schema_version": "routing_asset_backfill_rollback_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "repository_root": str(ROOT),
        "database_url": database_url,
        "schema": schema,
        "mutated_tables": list(MUTATED_TABLES),
        "storage_artifacts_note": "rollback restores DB metadata/rows only; remove newly written storage artifacts manually if needed.",
        "document_versions": [
            {
                "tenant_id": record.get("tenant_id"),
                "workspace_id": record.get("workspace_id"),
                "document_id": record.get("document_id"),
                "version_id": record.get("version_id"),
                "previous_version": {
                    "routing_index_status": record.get("routing_index_status"),
                    "routing_index_path": record.get("routing_index_path"),
                    "routing_index_error": record.get("routing_index_error"),
                    "routing_index_version": record.get("routing_index_version"),
                },
                "previous_nodes": previous_nodes.get(str(record.get("version_id")), []),
                "backfill_result": None,
            }
            for record in candidates
        ],
    }


def _default_manifest_path() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ROOT / "results" / f"routing_asset_backfill_rollback_{timestamp}.json"


def _execute_backfill_record(db: Session, record: dict[str, Any]) -> dict[str, Any]:
    from app.models import DocumentRoutingNode, DocumentVersion
    from app.services.pageindex_service import RoutingBuildOptions, build_routing_index_payload

    parsed_path = _normalize_text(record.get("parsed_structure_path"))
    if parsed_path is None:
        raise RuntimeError("parsed_structure_path is missing")
    structure, source_doc_name = _load_parsed_structure(parsed_path)
    document_label = _normalize_text(record.get("display_name")) or _normalize_text(record.get("source_filename")) or "Document"
    routing_index = build_routing_index_payload(
        structure,
        document_label=document_label,
        document_id=str(record["document_id"]),
        version_id=str(record["version_id"]),
        source_doc_name=source_doc_name or _normalize_text(record.get("source_filename")),
        routing_index_version=_normalize_text(record.get("routing_index_version")) or "v1",
        build_options=RoutingBuildOptions.disabled(),
    )
    routing_index_path = _write_routing_index(
        tenant_id=str(record["tenant_id"]),
        document_id=str(record["document_id"]),
        version_id=str(record["version_id"]),
        routing_index=routing_index,
    )
    rows = _routing_rows_from_payload(str(record["document_id"]), str(record["version_id"]), routing_index)
    db.execute(sa.delete(DocumentRoutingNode).where(DocumentRoutingNode.version_id == record["version_id"]))
    if rows:
        db.execute(sa.insert(DocumentRoutingNode), rows)
    db.execute(
        sa.update(DocumentVersion)
        .where(DocumentVersion.id == record["version_id"])
        .values(
            routing_index_status="index_ready",
            routing_index_path=routing_index_path,
            routing_index_error=None,
            routing_index_version=routing_index.get("routing_index_version") or "v1",
        )
    )
    coverage = (routing_index.get("build_metadata") or {}).get("summary_coverage") or {}
    return {
        "status": "completed",
        "tenant_id": record.get("tenant_id"),
        "workspace_id": record.get("workspace_id"),
        "document_id": record.get("document_id"),
        "version_id": record.get("version_id"),
        "routing_index_path": routing_index_path,
        "node_count": len(rows),
        "summary_coverage": coverage,
    }


def backfill_payload(args: argparse.Namespace) -> dict[str, Any]:
    database_url = _database_url_from_args(args)
    display_database_url = _display_database_url(database_url)
    engine = _create_engine(database_url)
    try:
        dry_run_report = build_scan_report(
            engine,
            command="backfill",
            summary_threshold=float(getattr(args, "summary_threshold", 1.0)),
            sample_limit=int(getattr(args, "sample_limit", 20)),
            include_low_summary=bool(getattr(args, "include_low_summary", False)),
            max_versions=getattr(args, "max_versions", None),
            database_url=display_database_url,
        )
        if dry_run_report["status"] == "blocked":
            return dry_run_report
        if not getattr(args, "execute", False):
            return dry_run_report

        records = _load_version_records(
            engine,
            summary_threshold=float(getattr(args, "summary_threshold", 1.0)),
        )
        candidates = _candidate_records(
            records,
            include_low_summary=bool(getattr(args, "include_low_summary", False)),
            max_versions=getattr(args, "max_versions", None),
        )
        candidate_ids = [str(record["version_id"]) for record in candidates]
        with engine.connect() as conn:
            previous_nodes = _previous_nodes(conn, candidate_ids)
        manifest = _rollback_manifest_payload(
            database_url=display_database_url,
            schema=dry_run_report["schema"],
            candidates=candidates,
            previous_nodes=previous_nodes,
        )
        manifest_path = Path(getattr(args, "rollback_manifest", None) or _default_manifest_path())
        _write_json_file(manifest_path, manifest)

        results: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        with Session(engine) as db:
            for record in candidates:
                try:
                    result = _execute_backfill_record(db, record)
                    db.commit()
                    results.append(result)
                except Exception as exc:
                    db.rollback()
                    failures.append(
                        {
                            "status": "failed",
                            "tenant_id": record.get("tenant_id"),
                            "workspace_id": record.get("workspace_id"),
                            "document_id": record.get("document_id"),
                            "version_id": record.get("version_id"),
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )

        by_version = {str(result["version_id"]): result for result in results + failures}
        for item in manifest["document_versions"]:
            item["backfill_result"] = by_version.get(str(item["version_id"]))
        _write_json_file(manifest_path, manifest)

        verification = build_scan_report(
            engine,
            command="validate",
            summary_threshold=float(getattr(args, "summary_threshold", 1.0)),
            sample_limit=int(getattr(args, "sample_limit", 20)),
            include_low_summary=bool(getattr(args, "include_low_summary", False)),
            max_versions=getattr(args, "max_versions", None),
            database_url=display_database_url,
        )
        return {
            "status": "completed" if not failures else "partial",
            "command": "backfill",
            "dry_run": False,
            "execute": True,
            "repository_root": str(ROOT),
            "database_url": display_database_url,
            "rollback_manifest": str(manifest_path),
            "preflight": dry_run_report,
            "results": {
                "attempted_count": len(candidates),
                "completed_count": len(results),
                "failed_count": len(failures),
                "failure_rate": _rate(len(failures), len(candidates)),
                "completed": results,
                "failed": failures,
            },
            "post_validate": verification,
        }
    finally:
        engine.dispose()


def _load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _coerce_node_row_for_insert(row: dict[str, Any]) -> dict[str, Any]:
    coerced = dict(row)
    for key in ("created_at", "updated_at"):
        value = coerced.get(key)
        if isinstance(value, str):
            try:
                coerced[key] = datetime.fromisoformat(value)
            except ValueError:
                coerced[key] = datetime.utcnow()
        elif value is None:
            coerced[key] = datetime.utcnow()
    return coerced


def rollback_payload(args: argparse.Namespace) -> dict[str, Any]:
    database_url = _database_url_from_args(args)
    display_database_url = _display_database_url(database_url)
    manifest_path = Path(getattr(args, "manifest"))
    manifest = _load_manifest(manifest_path)
    engine = _create_engine(database_url)
    try:
        schema = inspect_runtime_schema(engine)
        planned = manifest.get("document_versions") or []
        payload: dict[str, Any] = {
            "status": "blocked" if schema["status"] != "ready" else "dry_run",
            "command": "rollback",
            "dry_run": not bool(getattr(args, "execute", False)),
            "execute_required_for_mutation": True,
            "database_url": display_database_url,
            "manifest": str(manifest_path),
            "schema": schema,
            "planned_mutations": {
                "tables": list(MUTATED_TABLES),
                "document_version_count": len(planned),
                "document_versions": [
                    {
                        "tenant_id": item.get("tenant_id"),
                        "workspace_id": item.get("workspace_id"),
                        "document_id": item.get("document_id"),
                        "version_id": item.get("version_id"),
                        "restore_routing_index_status": (item.get("previous_version") or {}).get(
                            "routing_index_status"
                        ),
                        "restore_routing_index_path": (item.get("previous_version") or {}).get("routing_index_path"),
                        "restore_node_count": len(item.get("previous_nodes") or []),
                    }
                    for item in planned
                ],
            },
            "storage_artifacts_note": manifest.get("storage_artifacts_note"),
        }
        if schema["status"] != "ready" or not getattr(args, "execute", False):
            return payload

        from app.models import DocumentRoutingNode, DocumentVersion

        restored: list[dict[str, Any]] = []
        with Session(engine) as db:
            for item in planned:
                version_id = item.get("version_id")
                previous = item.get("previous_version") or {}
                previous_nodes = [_coerce_node_row_for_insert(row) for row in (item.get("previous_nodes") or [])]
                db.execute(sa.delete(DocumentRoutingNode).where(DocumentRoutingNode.version_id == version_id))
                if previous_nodes:
                    db.execute(sa.insert(DocumentRoutingNode), previous_nodes)
                db.execute(
                    sa.update(DocumentVersion)
                    .where(DocumentVersion.id == version_id)
                    .values(
                        routing_index_status=previous.get("routing_index_status"),
                        routing_index_path=previous.get("routing_index_path"),
                        routing_index_error=previous.get("routing_index_error"),
                        routing_index_version=previous.get("routing_index_version") or "v1",
                    )
                )
                restored.append({"version_id": version_id, "restored_node_count": len(previous_nodes)})
            db.commit()
        payload["status"] = "completed"
        payload["dry_run"] = False
        payload["execute"] = True
        payload["results"] = {"restored": restored}
        return payload
    finally:
        engine.dispose()


def scan_command(args: argparse.Namespace) -> int:
    payload = scan_payload(args)
    _emit(args, payload)
    return 2 if payload["status"] == "blocked" else 0


def backfill_command(args: argparse.Namespace) -> int:
    payload = backfill_payload(args)
    _emit(args, payload)
    return 2 if payload["status"] == "blocked" else 0


def rollback_command(args: argparse.Namespace) -> int:
    payload = rollback_payload(args)
    _emit(args, payload)
    return 2 if payload["status"] == "blocked" else 0


def _add_scan_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--database-url", help="Override DATABASE_URL for this tool run")
    parser.add_argument("--summary-threshold", type=float, default=1.0)
    parser.add_argument("--sample-limit", type=int, default=20)
    parser.add_argument("--output", help="Optional JSON output path")
    parser.add_argument("--max-versions", type=int, default=None, help="Limit planned mutation list")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Phase IE-5 routing asset dry-run/backfill/validate helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="只读扫描 routing asset 缺失与 summary 覆盖率")
    _add_scan_options(scan_parser)
    scan_parser.set_defaults(func=scan_command)

    validate_parser = subparsers.add_parser("validate", help="只读样本验证，输出节点数/覆盖率/失败率/缺失率")
    _add_scan_options(validate_parser)
    validate_parser.set_defaults(func=scan_command)

    backfill_parser = subparsers.add_parser("backfill", help="默认 dry-run；加 --execute 才回填 routing_index/base nodes")
    _add_scan_options(backfill_parser)
    backfill_parser.add_argument("--execute", action="store_true")
    backfill_parser.add_argument("--include-low-summary", action="store_true")
    backfill_parser.add_argument("--rollback-manifest", help="Override rollback manifest output path for --execute")
    backfill_parser.set_defaults(func=backfill_command)

    rollback_parser = subparsers.add_parser("rollback", help="默认 dry-run；加 --execute 才按 manifest 恢复 DB 元数据/节点")
    rollback_parser.add_argument("--database-url", help="Override DATABASE_URL for this tool run")
    rollback_parser.add_argument("--manifest", required=True)
    rollback_parser.add_argument("--execute", action="store_true")
    rollback_parser.add_argument("--output", help="Optional JSON output path")
    rollback_parser.set_defaults(func=rollback_command)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
