import json
import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi import HTTPException, status
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.principal import Principal
from app.models import ChatRun, ComplianceRun, Document, DocumentVersion, ParseJob, RunObservationEvent
from app.services.task_queue_service import publish_chat_event, publish_runtime_observation
from app.services.telemetry_service import (
    routing_asset_build_telemetry,
    routing_asset_item,
    telemetry_payload,
)
from app.services.workspace_access_service import require_workspace_capability
from app.services.workspace_scope_service import get_workspace_visibility_filter


settings = get_settings()
logger = logging.getLogger(__name__)

OBSERVATION_TERMINAL_EVENT_TYPES = {"run_completed", "run_failed"}
OBSERVATION_PAYLOAD_JSON_MAX_BYTES = 60_000
_EPHEMERAL_OBSERVATION_SEQUENCES: dict[tuple[str, str], int] = {}


def _json_loads(text: str | None, fallback):
    if not text:
        return fallback
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return fallback


def _trim_text(text: str | None) -> dict[str, Any]:
    normalized = str(text or "")
    truncated = False
    if len(normalized) > settings.observation_text_max_chars:
        normalized = normalized[: settings.observation_text_max_chars].rstrip() + "\n...[truncated]"
        truncated = True
    return {
        "text": normalized,
        "text_length": len(str(text or "")),
        "text_truncated": truncated,
    }


def _run_observation_table_exists(db: Session) -> bool:
    bind = db.get_bind()
    return bind is not None and inspect(bind).has_table(RunObservationEvent.__tablename__)


def _next_ephemeral_sequence(run_kind: str, run_id: str) -> int:
    key = (run_kind, run_id)
    next_sequence = _EPHEMERAL_OBSERVATION_SEQUENCES.get(key, 0) + 1
    _EPHEMERAL_OBSERVATION_SEQUENCES[key] = next_sequence
    return next_sequence


def sanitize_observation_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    raw = jsonable_encoder(payload or {})
    for key in ("prompt", "prompt_text", "response_text", "delta", "error"):
        if key in raw:
            raw[key] = _trim_text(raw.get(key))
    request = raw.get("request")
    if isinstance(request, dict) and "messages" in request:
        request = dict(request)
        request["messages"] = _trim_text(json.dumps(request.get("messages"), ensure_ascii=False))
        raw["request"] = request
    response = raw.get("response")
    if isinstance(response, dict):
        raw["response"] = {"keys": sorted(response.keys())[:40]}
    return raw


def serialize_observation_payload_for_storage(payload: dict[str, Any] | None) -> str:
    sanitized = sanitize_observation_payload(payload)
    payload_json = json.dumps(sanitized, ensure_ascii=False)
    payload_bytes = len(payload_json.encode("utf-8"))
    if payload_bytes <= OBSERVATION_PAYLOAD_JSON_MAX_BYTES:
        return payload_json
    preview_text = payload_json[:10_000].rstrip()
    compacted = {
        "payload_truncated": True,
        "payload_original_bytes": payload_bytes,
        "payload_preview": {
            "text": preview_text + "\n...[truncated]",
            "text_length": len(payload_json),
            "text_truncated": True,
        },
    }
    return json.dumps(compacted, ensure_ascii=False)


def _build_ephemeral_run_observation_event(
    *,
    run_kind: str,
    run_id: str,
    event_type: str,
    step: str | None,
    status_value: str | None,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "run_kind": run_kind,
        "run_id": run_id,
        "sequence_no": _next_ephemeral_sequence(run_kind, run_id),
        "event_type": event_type,
        "step": step,
        "status": status_value,
        "payload": sanitize_observation_payload(payload),
        "created_at": datetime.utcnow(),
    }


async def record_run_observation_event(
    *,
    run_kind: str,
    run_id: str,
    tenant_id: str,
    workspace_id: str | None,
    event_type: str,
    step: str | None = None,
    status_value: str | None = None,
    payload: dict[str, Any] | None = None,
):
    db = SessionLocal()
    payload_json = serialize_observation_payload_for_storage(payload)
    serialized: dict[str, Any] | None = None
    try:
        if not _run_observation_table_exists(db):
            serialized = _build_ephemeral_run_observation_event(
                run_kind=run_kind,
                run_id=run_id,
                event_type=event_type,
                step=step,
                status_value=status_value,
                payload=_json_loads(payload_json, {}),
            )
            await publish_runtime_observation(run_kind, run_id, {"event": "observation", "data": serialized})
            if run_kind == "chat":
                await publish_chat_event(run_id, {"event": "observation", "data": serialized})
            return serialized
        next_sequence = (
            db.scalar(
                select(func.max(RunObservationEvent.sequence_no)).where(
                    RunObservationEvent.run_kind == run_kind,
                    RunObservationEvent.run_id == run_id,
                )
            )
            or 0
        ) + 1
        event = RunObservationEvent(
            id=str(uuid.uuid4()),
            run_kind=run_kind,
            run_id=run_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            sequence_no=next_sequence,
            event_type=event_type,
            step=step,
            status=status_value,
            payload_json=payload_json,
            created_at=datetime.utcnow(),
        )
        db.add(event)
        db.commit()
        db.refresh(event)
    except SQLAlchemyError as exc:
        db.rollback()
        logger.warning(
            "Failed to persist runtime observation event %s for %s %s: %s",
            event_type,
            run_kind,
            run_id,
            exc,
        )
        fallback_payload = _json_loads(payload_json, {})
        if isinstance(fallback_payload, dict):
            fallback_payload = {
                **fallback_payload,
                "observation_persistence": {
                    "persisted": False,
                    "fallback": "ephemeral",
                    "error_type": type(exc).__name__,
                },
            }
        else:
            fallback_payload = {}
        serialized = _build_ephemeral_run_observation_event(
            run_kind=run_kind,
            run_id=run_id,
            event_type=event_type,
            step=step,
            status_value=status_value,
            payload=fallback_payload,
        )
    finally:
        db.close()
    if serialized is None:
        serialized = serialize_run_observation_event(event)
    await publish_runtime_observation(run_kind, run_id, {"event": "observation", "data": serialized})
    if run_kind == "chat":
        await publish_chat_event(run_id, {"event": "observation", "data": serialized})
    return serialized


def serialize_run_observation_event(event: RunObservationEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "run_kind": event.run_kind,
        "run_id": event.run_id,
        "sequence_no": event.sequence_no,
        "event_type": event.event_type,
        "step": event.step,
        "status": event.status,
        "payload": _json_loads(event.payload_json, {}),
        "created_at": event.created_at,
    }


def _load_chat_run_snapshot(run: ChatRun, events: list[RunObservationEvent]) -> dict[str, Any]:
    metrics = _json_loads(run.metrics_json, {})
    current_step = next((event.step for event in reversed(events) if event.step), None)
    return {
        "run_kind": "chat",
        "run_id": run.id,
        "status": run.status,
        "current_step": current_step,
        "worker_node_code": run.worker_node_code,
        "queue": {
            "queue_ms": metrics.get("queue_ms"),
            "claimed_at": run.claimed_at,
            "heartbeat_at": run.heartbeat_at,
        },
        "timings": {
            "retrieve_ms": metrics.get("retrieve_ms"),
            "answer_ms": metrics.get("answer_ms"),
            "total_ms": metrics.get("total_ms"),
            "wall_clock_ms": metrics.get("wall_clock_ms"),
            "ttft_ms": metrics.get("ttft_ms"),
            "answer_pre_provider_ms": metrics.get("answer_pre_provider_ms"),
            "provider_stream_open_ms": metrics.get("provider_stream_open_ms"),
            "provider_first_chunk_ms": metrics.get("provider_first_chunk_ms"),
            "provider_ttft_ms": metrics.get("provider_ttft_ms"),
            "provider_first_delta_after_first_chunk_ms": metrics.get("provider_first_delta_after_first_chunk_ms"),
            "provider_stream_ms": metrics.get("provider_stream_ms"),
            "first_delta_to_stream_end_ms": metrics.get("first_delta_to_stream_end_ms"),
            "heartbeat_drain_ms": metrics.get("heartbeat_drain_ms"),
        },
        "streaming": {
            "heartbeat_count": metrics.get("heartbeat_count"),
            "cancel_check_count": metrics.get("cancel_check_count"),
            "answer_delta_observation_count": metrics.get("answer_delta_observation_count"),
            "streamed_delta_count": metrics.get("streamed_delta_count"),
            "output_chars": metrics.get("output_chars"),
        },
        "execution_context": _json_loads(run.execution_context_json, {}),
        "partial_answer": run.answer_text or run.answer,
        "events": [serialize_run_observation_event(event) for event in events],
    }


def _load_compliance_run_snapshot(run: ComplianceRun, events: list[RunObservationEvent]) -> dict[str, Any]:
    metrics = _json_loads(run.metrics_json, {})
    current_step = next((event.step for event in reversed(events) if event.step), None)
    return {
        "run_kind": "compliance",
        "run_id": run.id,
        "status": run.status,
        "current_step": current_step,
        "worker_node_code": run.worker_node_code,
        "queue": {
            "queue_ms": metrics.get("queue_ms"),
            "claimed_at": run.claimed_at,
            "heartbeat_at": run.heartbeat_at,
        },
        "timings": {
            "retrieve_ms": metrics.get("retrieve_ms"),
            "merge_ms": metrics.get("merge_ms"),
            "answer_ms": metrics.get("answer_ms"),
            "total_ms": metrics.get("total_ms"),
            "wall_clock_ms": metrics.get("wall_clock_ms"),
        },
        "execution_context": _json_loads(run.execution_context_json, {}),
        "partial_answer": run.answer,
        "events": [serialize_run_observation_event(event) for event in events],
    }


def _load_parse_job_snapshot(
    db: Session,
    job: ParseJob,
    events: list[RunObservationEvent],
) -> dict[str, Any]:
    version = db.get(DocumentVersion, job.version_id)
    routing_item = None
    if version is not None:
        routing_item = routing_asset_item(
            document_id=job.document_id,
            version_id=job.version_id,
            routing_index_status=getattr(version, "routing_index_status", None),
            routing_index_path=getattr(version, "routing_index_path", None),
            routing_index_version=getattr(version, "routing_asset_schema_version", None),
        )
    telemetry = telemetry_payload(
        routing_asset_build=routing_asset_build_telemetry(
            items=[routing_item] if routing_item is not None else [],
            mode="parse_job_snapshot",
            dry_run=False,
            backfill=False,
            attempted=job.status in {"parsing", "index_ready", "failed"},
        )
    )
    return {
        "run_kind": "parse_job",
        "run_id": job.id,
        "status": job.status,
        "current_step": job.current_step,
        "worker_node_code": None,
        "queue": {},
        "timings": {
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "duration_ms": job.duration_ms,
        },
        "execution_context": {
            "parse_job": {
                "document_id": job.document_id,
                "version_id": job.version_id,
                "model": job.model,
                "progress_percent": job.progress_percent,
                "error_message": job.error_message,
            },
            "telemetry": telemetry,
        },
        "partial_answer": None,
        "events": [serialize_run_observation_event(event) for event in events],
    }


def get_routing_asset_debug_snapshot(
    db: Session,
    principal: Principal,
    *,
    backfill: bool = False,
    sample_limit: int = 20,
) -> dict[str, Any]:
    require_workspace_capability(
        principal,
        "can_view_runs",
        detail="Missing workspace capability: can_view_runs",
    )
    rows = db.execute(
        select(DocumentVersion, Document)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(
            Document.tenant_id == principal.tenant_id,
            get_workspace_visibility_filter(db, principal, Document),
        )
        .order_by(Document.created_at.desc(), DocumentVersion.created_at.desc())
    ).all()
    items = [
        routing_asset_item(
            document_id=document.id,
            version_id=version.id,
            routing_index_status=getattr(version, "routing_index_status", None),
            routing_index_path=getattr(version, "routing_index_path", None),
            routing_index_version=getattr(version, "routing_asset_schema_version", None),
        )
        for version, document in rows
    ]
    routing_telemetry = routing_asset_build_telemetry(
        items=items,
        mode="backfill" if backfill else "debug",
        dry_run=True,
        backfill=backfill,
        attempted=False,
    )
    sample_limit = max(0, min(int(sample_limit), 100))
    missing_samples = [item for item in items if item.get("state") == "missing"][:sample_limit]
    failed_samples = [item for item in items if item.get("state") == "failed"][:sample_limit]
    return {
        "telemetry": telemetry_payload(routing_asset_build=routing_telemetry),
        "routing_asset_build": routing_telemetry,
        "samples": {
            "missing": missing_samples,
            "failed": failed_samples,
        },
    }


def get_runtime_observation_snapshot(
    db: Session,
    principal: Principal,
    *,
    run_kind: str,
    run_id: str,
    limit: int = 200,
) -> dict[str, Any]:
    require_workspace_capability(
        principal,
        "can_view_runs",
        detail="Missing workspace capability: can_view_runs",
    )
    if run_kind == "chat":
        run = db.get(ChatRun, run_id)
        if run is None or run.tenant_id != principal.tenant_id or run.workspace_id != principal.workspace_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    elif run_kind == "compliance":
        run = db.get(ComplianceRun, run_id)
        if run is None or run.tenant_id != principal.tenant_id or run.workspace_id != principal.workspace_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    elif run_kind == "parse_job":
        run = db.get(ParseJob, run_id)
        if run is None or run.tenant_id != principal.tenant_id or run.workspace_id != principal.workspace_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unsupported run kind")

    if _run_observation_table_exists(db):
        events = db.scalars(
            select(RunObservationEvent)
            .where(
                RunObservationEvent.run_kind == run_kind,
                RunObservationEvent.run_id == run_id,
            )
            .order_by(RunObservationEvent.sequence_no.asc())
            .limit(limit)
        ).all()
    else:
        events = []
    if run_kind == "chat":
        return _load_chat_run_snapshot(run, events)
    if run_kind == "parse_job":
        return _load_parse_job_snapshot(db, run, events)
    return _load_compliance_run_snapshot(run, events)
