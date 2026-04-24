import logging
import uuid
import asyncio
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import default_llm_model, get_settings
from app.core.db import SessionLocal
from app.models import Document, DocumentRoutingNode, DocumentVersion, ParseJob
from app.services.pageindex_service import (
    build_routing_index_payload,
    parse_pdf_to_structure_async,
    routing_build_options_from_settings,
)
from app.services.runtime_observation_service import record_run_observation_event
from app.services.storage_service import local_artifact_path, write_document_routing_index, write_document_structure
from app.services.task_queue_service import enqueue_parse_job
from app.services.telemetry_service import routing_asset_build_telemetry, routing_asset_item, telemetry_payload


settings = get_settings()
logger = logging.getLogger(__name__)


def _format_exception(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def _job_update(
    db: Session,
    job: ParseJob,
    *,
    status: str,
    current_step: str,
    progress_percent: int,
    error_message: str | None = None,
) -> None:
    job.status = status
    job.current_step = current_step
    job.progress_percent = progress_percent
    job.error_message = error_message
    if status == "parsing" and job.started_at is None:
        job.started_at = datetime.utcnow()
    if status in {"index_ready", "failed"}:
        job.finished_at = datetime.utcnow()
        if job.started_at:
            job.duration_ms = int((job.finished_at - job.started_at).total_seconds() * 1000)
    db.commit()


async def _record_parse_observation(
    job: ParseJob,
    *,
    event_type: str,
    step: str | None = None,
    status_value: str | None = None,
    payload: dict | None = None,
) -> None:
    try:
        await record_run_observation_event(
            run_kind="parse_job",
            run_id=job.id,
            tenant_id=job.tenant_id,
            workspace_id=job.workspace_id,
            event_type=event_type,
            step=step,
            status_value=status_value,
            payload=payload,
        )
    except Exception as exc:  # pragma: no cover - telemetry must not break parsing
        logger.warning("Failed to record parse observation for job %s: %s", job.id, exc)


def _routing_asset_item_for_version(document_id: str, version: DocumentVersion) -> dict:
    return routing_asset_item(
        document_id=document_id,
        version_id=version.id,
        routing_index_status=getattr(version, "routing_index_status", None),
        routing_index_path=getattr(version, "routing_index_path", None),
        routing_index_version=getattr(version, "routing_asset_schema_version", None),
    )


def _routing_asset_telemetry_for_version(
    *,
    document_id: str,
    version: DocumentVersion,
    status: str,
    attempted: bool,
    node_count: int | None = None,
    hook_results: dict | None = None,
    error: str | None = None,
) -> dict:
    return telemetry_payload(
        routing_asset_build=routing_asset_build_telemetry(
            items=[_routing_asset_item_for_version(document_id, version)],
            mode="online_parse",
            dry_run=False,
            backfill=False,
            attempted=attempted,
            status=status,
            node_count=node_count,
            hook_results=hook_results,
            error=error,
        )
    )


def _document_routing_nodes_from_payload(
    *,
    document_id: str,
    version_id: str,
    routing_index: dict,
) -> list[DocumentRoutingNode]:
    return [
        DocumentRoutingNode(
            id=str(uuid.uuid4()),
            document_id=document_id,
            version_id=version_id,
            node_id=node["node_id"],
            parent_node_id=node["parent_node_id"],
            depth=int(node["depth"]),
            title=node["title"],
            breadcrumb=node["breadcrumb"],
            page_start=node["page_start"],
            page_end=node["page_end"],
            route_summary=node["route_summary"],
            contrastive_summary=node["contrastive_summary"],
            aliases_json=node["aliases_json"],
            keywords_json=node["keywords_json"],
            manual_profile_text=node["manual_profile_text"],
        )
        for node in routing_index["nodes"]
    ]


def _persist_routing_index_build(
    *,
    db: Session,
    tenant_id: str,
    document_id: str,
    version: DocumentVersion,
    routing_index: dict,
) -> str:
    routing_index_path = write_document_routing_index(
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version.id,
        data=routing_index,
    )
    routing_nodes = _document_routing_nodes_from_payload(
        document_id=document_id,
        version_id=version.id,
        routing_index=routing_index,
    )
    (
        db.query(DocumentRoutingNode)
        .filter(DocumentRoutingNode.version_id == version.id)
        .delete(synchronize_session=False)
    )
    db.add_all(routing_nodes)
    version.routing_index_status = "index_ready"
    version.routing_index_path = routing_index_path
    version.routing_index_error = None
    db.commit()
    return routing_index_path


async def run_parse_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(ParseJob, job_id)
        if job is None:
            return
        version = db.get(DocumentVersion, job.version_id)
        document = db.get(Document, job.document_id)
        if version is None or document is None:
            _job_update(db, job, status="failed", current_step="missing_artifacts", progress_percent=100, error_message="Document version not found")
            await _record_parse_observation(
                job,
                event_type="run_failed",
                step="missing_artifacts",
                status_value="failed",
                payload={"error": "Document version not found"},
            )
            return

        document_label = document.display_name or document.source_filename

        _job_update(db, job, status="queued", current_step="queued", progress_percent=5)
        version.parse_status = "queued"
        version.routing_index_status = "queued"
        version.routing_index_error = None
        version.routing_index_path = None
        document.status = "queued"
        db.commit()
        await _record_parse_observation(
            job,
            event_type="run_status",
            status_value="queued",
            payload={"document_id": document.id, "version_id": version.id},
        )

        _job_update(db, job, status="parsing", current_step="parsing_pdf", progress_percent=25)
        version.parse_status = "parsing"
        version.routing_index_status = "parsing"
        version.routing_index_error = None
        version.routing_index_path = None
        document.status = "parsing"
        db.commit()
        await _record_parse_observation(
            job,
            event_type="step_started",
            step="parsing_pdf",
            status_value="parsing",
            payload={"model": job.model or default_llm_model()},
        )

        with local_artifact_path(version.storage_path) as pdf_path:
            result = await parse_pdf_to_structure_async(str(pdf_path), job.model or default_llm_model())
        structure_path = write_document_structure(
            tenant_id=job.tenant_id,
            document_id=document.id,
            version_id=version.id,
            data=result,
        )

        version.parsed_structure_path = str(structure_path)
        version.parse_status = "index_ready"
        version.parse_error = None
        document.status = "index_ready"
        document.active_version_id = version.id
        document.updated_at = datetime.utcnow()
        db.commit()
        await _record_parse_observation(
            job,
            event_type="step_completed",
            step="parsing_pdf",
            status_value=job.status,
            payload={"parsed_structure_path_present": bool(version.parsed_structure_path)},
        )

        routing_index_path = None
        parsed_structure = result["structure"] if isinstance(result, dict) and "structure" in result else result
        try:
            await _record_parse_observation(
                job,
                event_type="step_started",
                step="routing_asset_build",
                status_value=job.status,
                payload={
                    "telemetry": telemetry_payload(
                        routing_asset_build=routing_asset_build_telemetry(
                            items=[_routing_asset_item_for_version(document.id, version)],
                            mode="online_parse",
                            dry_run=False,
                            backfill=False,
                            attempted=True,
                            status="started",
                        )
                    )
                },
            )
            routing_index = build_routing_index_payload(
                parsed_structure,
                document_label=document_label,
                document_id=document.id,
                version_id=version.id,
                source_doc_name=result.get("doc_name") if isinstance(result, dict) else None,
                routing_index_version=version.routing_index_version,
                build_options=routing_build_options_from_settings(settings),
            )
            routing_index_path = _persist_routing_index_build(
                db=db,
                tenant_id=job.tenant_id,
                document_id=document.id,
                version=version,
                routing_index=routing_index,
            )
            await _record_parse_observation(
                job,
                event_type="step_completed",
                step="routing_asset_build",
                status_value=job.status,
                payload={
                    "telemetry": _routing_asset_telemetry_for_version(
                        document_id=document.id,
                        version=version,
                        status="completed",
                        attempted=True,
                        node_count=len(routing_index["nodes"]),
                        hook_results=(routing_index.get("build_metadata") or {}).get("hook_results"),
                    )
                },
            )
        except Exception as routing_exc:
            db.rollback()
            routing_error = _format_exception(routing_exc)
            fresh_version = db.get(DocumentVersion, version.id)
            if fresh_version is not None:
                fresh_version.routing_index_status = "failed"
                fresh_version.routing_index_path = routing_index_path
                fresh_version.routing_index_error = routing_error
            db.commit()
            logger.warning(
                "Routing index generation failed for document %s version %s: %s",
                document.id,
                version.id,
                routing_error,
            )
            await _record_parse_observation(
                job,
                event_type="step_failed",
                step="routing_asset_build",
                status_value=job.status,
                payload={
                    "telemetry": _routing_asset_telemetry_for_version(
                        document_id=document.id,
                        version=fresh_version or version,
                        status="failed",
                        attempted=True,
                        error=routing_error,
                    )
                },
            )

        _job_update(db, job, status="index_ready", current_step="index_ready", progress_percent=100)
        final_version = db.get(DocumentVersion, version.id) or version
        await _record_parse_observation(
            job,
            event_type="run_completed",
            status_value="index_ready",
            payload={
                "telemetry": _routing_asset_telemetry_for_version(
                    document_id=document.id,
                    version=final_version,
                    status="completed" if final_version.routing_index_status == "index_ready" else "partial",
                    attempted=True,
                )
            },
        )
    except Exception as exc:
        db.rollback()
        job = db.get(ParseJob, job_id)
        if job is not None:
            _job_update(db, job, status="failed", current_step="failed", progress_percent=100, error_message=str(exc))
        version = db.get(DocumentVersion, job.version_id) if job else None
        document = db.get(Document, job.document_id) if job else None
        if version is not None:
            version.parse_status = "failed"
            version.parse_error = str(exc)
            version.routing_index_status = "failed"
            version.routing_index_path = None
            version.routing_index_error = _format_exception(exc)
        if document is not None:
            document.status = "failed"
            document.updated_at = datetime.utcnow()
        db.commit()
        if job is not None:
            await _record_parse_observation(
                job,
                event_type="run_failed",
                step="failed",
                status_value="failed",
                payload={"error": _format_exception(exc)},
            )
    finally:
        db.close()


def schedule_parse_job(job_id: str) -> None:
    enqueue_parse_job(job_id)
