import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.principal import Principal
from app.models import ChatRun, ComplianceRun, RunObservationEvent
from app.services.task_queue_service import publish_chat_event, publish_runtime_observation
from app.services.workspace_access_service import require_workspace_capability


settings = get_settings()

OBSERVATION_TERMINAL_EVENT_TYPES = {"run_completed", "run_failed"}


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


def sanitize_observation_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict(payload or {})
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
    try:
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
            payload_json=json.dumps(sanitize_observation_payload(payload), ensure_ascii=False),
            created_at=datetime.utcnow(),
        )
        db.add(event)
        db.commit()
        db.refresh(event)
    finally:
        db.close()
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
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unsupported run kind")

    events = db.scalars(
        select(RunObservationEvent)
        .where(
            RunObservationEvent.run_kind == run_kind,
            RunObservationEvent.run_id == run_id,
        )
        .order_by(RunObservationEvent.sequence_no.asc())
        .limit(limit)
    ).all()
    if run_kind == "chat":
        return _load_chat_run_snapshot(run, events)
    return _load_compliance_run_snapshot(run, events)
