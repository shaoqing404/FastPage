import asyncio
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

import litellm
from fastapi import HTTPException, status
from sqlalchemy import and_, exists, or_, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.principal import Principal
from app.models import ChatRun, ChatSession, ChatSkill, Document, DocumentVersion, User
from app.services.document_service import get_document_or_404
from app.services.pageindex_service import (
    build_answer_context,
    build_answer_with_marker,
    build_citations,
    build_generation_prompt,
    build_query_rewrite_prompt,
    choose_relevant_nodes,
    format_history_context,
    load_structure_file,
)
from app.services.provider_service import resolve_provider_config, validate_provider_model_selection
from app.services.session_service import _is_default_workspace, append_message, get_session_or_404, list_session_messages
from app.services.skill_trace_service import SkillTraceRecorder
from app.services.storage_service import local_artifact_path
from app.services.task_queue_service import (
    close_chat_event_stream,
    enqueue_chat_run,
    open_chat_event_subscription,
    publish_chat_event,
)
from app.services.workspace_access_service import can_read_skill
from pageindex.utils import count_tokens, extract_json, is_fatal_llm_model_error, llm_completion


settings = get_settings()

DEFAULT_CONVERSATION_CONFIG = {
    "query_rewrite_with_history": True,
    "include_history": True,
    "include_assistant_messages": True,
    "history_turn_limit": 4,
    "history_token_budget": 1800,
}

TERMINAL_RUN_STATUSES = {"completed", "failed", "cancelled"}
NONTERMINAL_RUN_STATUSES = {"accepted", "queued", "retrieving", "answering"}
ACTIVE_RUN_STATUSES = {"retrieving", "answering"}
SESSION_ORDERED_STATUSES = {"accepted", "queued", "retrieving", "answering"}

OPTION_LABELS = {
    "history_turn_limit": "history turn limit",
    "history_token_budget": "history token budget",
    "top_k": "sections to retrieve",
    "selection_mode": "section selection method",
    "max_context_pages": "max context pages",
    "max_context_tokens": "max context tokens",
    "temperature": "answer temperature",
}


class ChatRunCancelled(Exception):
    def __init__(self, reason: str, *, terminal_status: str = "cancelled") -> None:
        super().__init__(reason)
        self.reason = reason
        self.terminal_status = terminal_status


def _coerce_positive_int(name: str, value) -> int:
    label = OPTION_LABELS.get(name, name.replace("_", " "))
    try:
        coerced = int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{label} must be an integer",
        ) from exc
    if coerced <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{label} must be greater than 0",
        )
    return coerced


def _coerce_float(name: str, value) -> float:
    label = OPTION_LABELS.get(name, name.replace("_", " "))
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{label} must be a number",
        ) from exc


def _validate_execution_options(
    conversation_config: dict | None,
    retrieval_config: dict | None,
    generation_config: dict | None,
) -> tuple[dict, dict, dict]:
    conversation = {**DEFAULT_CONVERSATION_CONFIG, **dict(conversation_config or {})}
    retrieval = dict(retrieval_config or {})
    generation = dict(generation_config or {})

    for field in ("query_rewrite_with_history", "include_history", "include_assistant_messages"):
        conversation[field] = bool(conversation.get(field, DEFAULT_CONVERSATION_CONFIG[field]))

    if "history_turn_limit" in conversation:
        conversation["history_turn_limit"] = _coerce_positive_int("history_turn_limit", conversation["history_turn_limit"])
    if "history_token_budget" in conversation:
        conversation["history_token_budget"] = _coerce_positive_int("history_token_budget", conversation["history_token_budget"])
    if "top_k" in retrieval:
        retrieval["top_k"] = _coerce_positive_int("top_k", retrieval["top_k"])
    if "max_context_pages" in retrieval and retrieval["max_context_pages"] not in (None, ""):
        retrieval["max_context_pages"] = _coerce_positive_int("max_context_pages", retrieval["max_context_pages"])
    if "max_context_tokens" in retrieval and retrieval["max_context_tokens"] not in (None, ""):
        retrieval["max_context_tokens"] = _coerce_positive_int("max_context_tokens", retrieval["max_context_tokens"])
    if "selection_mode" in retrieval:
        selection_mode = str(retrieval["selection_mode"])
        if selection_mode not in {"outline_llm", "lexical_fallback"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="section selection method must be one of: outline_llm, lexical_fallback",
            )
        retrieval["selection_mode"] = selection_mode
    if "temperature" in generation and generation["temperature"] not in (None, ""):
        temperature = _coerce_float("temperature", generation["temperature"])
        if temperature < 0 or temperature > 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="temperature must be between 0 and 2",
            )
        generation["temperature"] = temperature

    return conversation, retrieval, generation


def _load_session_history(
    db: Session,
    *,
    tenant_id: str,
    workspace_id: str | None,
    session_id: str,
    model: str,
    conversation_config: dict,
    current_question: str,
) -> tuple[list[dict], dict]:
    include_history = bool(conversation_config.get("include_history", True))
    if not include_history:
        return [], {
            "used": False,
            "history_messages_used": 0,
            "history_turns_used": 0,
            "history_token_estimate": 0,
        }

    all_messages = list_session_messages(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        session_id=session_id,
    )
    include_assistant = bool(conversation_config.get("include_assistant_messages", True))
    if not include_assistant:
        all_messages = [message for message in all_messages if message.role != "assistant"]

    if all_messages and all_messages[-1].role == "user" and all_messages[-1].content.strip() == current_question.strip():
        all_messages = all_messages[:-1]

    max_turns = int(conversation_config.get("history_turn_limit", DEFAULT_CONVERSATION_CONFIG["history_turn_limit"]))
    history_budget = int(conversation_config.get("history_token_budget", DEFAULT_CONVERSATION_CONFIG["history_token_budget"]))

    user_messages = [message for message in all_messages if message.role == "user"]
    if user_messages:
        cutoff_user = user_messages[-max_turns] if len(user_messages) >= max_turns else user_messages[0]
        turn_window = [message for message in all_messages if message.sequence_no >= cutoff_user.sequence_no]
    else:
        turn_window = []

    selected: list[dict] = []
    total_tokens = 0
    for message in reversed(turn_window):
        estimated = count_tokens(message.content or "", model=model)
        if selected and total_tokens + estimated > history_budget:
            break
        selected.append(
            {
                "id": message.id,
                "role": message.role,
                "content": message.content,
                "sequence_no": message.sequence_no,
                "run_id": message.run_id,
            }
        )
        total_tokens += estimated

    selected.reverse()
    return selected, {
        "used": bool(selected),
        "history_messages_used": len(selected),
        "history_turns_used": len([item for item in selected if item["role"] == "user"]),
        "history_token_estimate": total_tokens,
    }


def _build_execution_context(
    *,
    provider_config: dict,
    resolved_model: str,
    conversation_config: dict,
    history_info: dict,
    retrieval_info: dict,
    generation_info: dict,
) -> dict:
    return {
        "provider": {
            "id": provider_config.get("provider_id"),
            "name": provider_config.get("name"),
            "type": provider_config.get("provider_type"),
            "scope": provider_config.get("scope"),
            "resolution_source": provider_config.get("resolution_source"),
        },
        "model": {
            "resolved_model": resolved_model,
        },
        "conversation": {
            **conversation_config,
            "history_used": history_info.get("used", False),
            "history_messages_used": history_info.get("history_messages_used", 0),
            "history_turns_used": history_info.get("history_turns_used", 0),
            "history_token_estimate": history_info.get("history_token_estimate", 0),
        },
        "retrieval": retrieval_info,
        "generation": generation_info,
    }


def _accumulate_usage_totals(usage_totals: dict, usage: dict | None) -> None:
    if not usage:
        return
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    total_tokens = usage.get("total_tokens")
    if total_tokens is None:
        total_tokens = prompt_tokens + completion_tokens
    usage_totals["input_tokens"] += prompt_tokens
    usage_totals["output_tokens"] += completion_tokens
    usage_totals["total_tokens"] += int(total_tokens or 0)


def _extract_usage_from_stream_chunk(chunk) -> dict | None:
    usage = getattr(chunk, "usage", None)
    if usage is None and isinstance(chunk, dict):
        usage = chunk.get("usage")
    if usage is None:
        return None
    if hasattr(usage, "model_dump"):
        usage = usage.model_dump()
    elif hasattr(usage, "dict"):
        usage = usage.dict()
    if not isinstance(usage, dict):
        return None
    return {
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "total_tokens": int(
            usage.get("total_tokens")
            or (int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0))
        ),
    }


def _json_loads(text: str | None, fallback):
    if not text:
        return fallback
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return fallback


def _load_run_snapshot(
    db: Session,
    *,
    tenant_id: str,
    run_id: str,
    refresh_transaction: bool = False,
) -> ChatRun:
    if refresh_transaction:
        db.rollback()
    run = db.get(ChatRun, run_id)
    if run is None or run.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return run


def _run_metrics_with_error(run: ChatRun, error: str) -> str:
    metrics = _json_loads(run.metrics_json, {})
    metrics["error"] = error
    return json.dumps(metrics, ensure_ascii=False)


def _session_ordering_filter(run: ChatRun):
    return and_(
        ChatRun.session_id == run.session_id,
        ChatRun.status.in_(SESSION_ORDERED_STATUSES),
        ChatRun.id != run.id,
        or_(
            ChatRun.created_at < run.created_at,
            and_(ChatRun.created_at == run.created_at, ChatRun.id < run.id),
        ),
    )


def _run_workspace_filter(db: Session, principal: Principal):
    if _is_default_workspace(db, principal.tenant_id, principal.workspace_id):
        return or_(ChatRun.workspace_id == principal.workspace_id, ChatRun.workspace_id.is_(None))
    return ChatRun.workspace_id == principal.workspace_id


def _load_visible_skill_map(db: Session, principal: Principal, skill_ids: set[str]) -> dict[str, ChatSkill]:
    if not skill_ids:
        return {}
    skills = db.scalars(
        select(ChatSkill).where(
            ChatSkill.id.in_(skill_ids),
            ChatSkill.tenant_id == principal.tenant_id,
            ChatSkill.workspace_id == principal.workspace_id,
        )
    ).all()
    return {
        skill.id: skill
        for skill in skills
        if can_read_skill(principal, skill)
    }


async def _publish_chat_event(run_id: str, event: str, data: dict) -> None:
    await publish_chat_event(run_id, {"event": event, "data": data})


def serialize_run(run: ChatRun) -> dict:
    return {
        "id": run.id,
        "tenant_id": run.tenant_id,
        "user_id": run.user_id,
        "session_id": run.session_id,
        "document_id": run.document_id,
        "version_id": run.version_id,
        "skill_id": run.skill_id,
        "provider_id": run.provider_id,
        "model": run.model,
        "question": run.question,
        "answer": run.answer,
        "answer_text": run.answer_text or run.answer,
        "answer_with_marker": run.answer_with_marker or run.answer,
        "status": run.status,
        "cancel_requested": bool(run.cancel_requested),
        "cancel_reason": run.cancel_reason,
        "execution_context": _json_loads(run.execution_context_json, {}),
        "selected_sections": _json_loads(run.selected_sections_json, []),
        "citations": _json_loads(run.citations_json, []),
        "metrics": _json_loads(run.metrics_json, {}),
        "last_error": run.last_error,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }


def _resolve_session_for_run(
    db: Session,
    *,
    principal: Principal,
    session_id: str | None,
    skill: ChatSkill | None,
) -> ChatSession | None:
    if not session_id:
        return None
    session = get_session_or_404(db, principal, session_id)
    if skill and session.skill_id and session.skill_id != skill.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Session is bound to a different skill",
        )
    if not skill and session.skill_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Skill-bound session cannot be used for direct ask",
        )
    return session


def _create_pending_run(
    db: Session,
    *,
    principal: Principal,
    user: User,
    document: Document,
    version: DocumentVersion,
    question: str,
    model: str | None,
    request_config: dict,
    conversation_config: dict | None = None,
    retrieval_config: dict | None = None,
    generation_config: dict | None = None,
    skill: ChatSkill | None = None,
    provider_id: str | None = None,
    session_id: str | None = None,
) -> ChatRun:
    if not version.parsed_structure_path or version.parse_status != "index_ready":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document is not ready for querying yet",
        )

    session = _resolve_session_for_run(db, principal=principal, session_id=session_id, skill=skill)
    provider_config = resolve_provider_config(
        db,
        principal.tenant_id,
        skill=skill,
        explicit_provider_id=provider_id,
        workspace_id=principal.workspace_id,
    )
    resolved_model = validate_provider_model_selection(
        provider_id=provider_config.get("provider_id"),
        provider_type=provider_config.get("provider_type"),
        provider_name=provider_config.get("name"),
        default_model=provider_config.get("default_model"),
        supported_models=provider_config.get("supported_models"),
        model=model or (skill.model if skill else None),
        subject="Chat run model",
    )

    conversation_config, retrieval_config, generation_config = _validate_execution_options(
        conversation_config,
        retrieval_config,
        generation_config,
    )

    workspace_id = (
        session.workspace_id if session and session.workspace_id else None
    ) or document.workspace_id or (skill.workspace_id if skill else None)
    run = ChatRun(
        id=str(uuid.uuid4()),
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        user_id=user.id,
        session_id=session.id if session else None,
        document_id=document.id,
        version_id=version.id,
        skill_id=skill.id if skill else None,
        provider_id=provider_config.get("provider_id"),
        model=resolved_model,
        question=question,
        status="accepted",
        cancel_requested=False,
        cancel_reason=None,
        request_config_json=json.dumps(request_config or {}, ensure_ascii=False),
        conversation_config_json=json.dumps(conversation_config, ensure_ascii=False),
        retrieval_config_json=json.dumps(retrieval_config, ensure_ascii=False),
        generation_config_json=json.dumps(generation_config, ensure_ascii=False),
        selected_sections_json="[]",
        citations_json="[]",
        execution_context_json="{}",
        metrics_json="{}",
        last_error=None,
        worker_node_code=None,
        claimed_at=None,
        heartbeat_at=None,
        started_at=None,
        finished_at=None,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _mark_run_queued(db: Session, run_id: str) -> ChatRun:
    run = db.get(ChatRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    if run.status == "accepted":
        run.status = "queued"
    run.heartbeat_at = datetime.utcnow()
    db.commit()
    db.refresh(run)
    enqueue_chat_run(run.id)
    return run


async def _create_and_enqueue_run(
    db: Session,
    *,
    principal: Principal,
    user: User,
    document: Document,
    version: DocumentVersion,
    question: str,
    model: str | None,
    request_config: dict,
    conversation_config: dict | None = None,
    retrieval_config: dict | None = None,
    generation_config: dict | None = None,
    skill: ChatSkill | None = None,
    provider_id: str | None = None,
    session_id: str | None = None,
) -> ChatRun:
    run = _create_pending_run(
        db,
        principal=principal,
        user=user,
        document=document,
        version=version,
        question=question,
        model=model,
        request_config=request_config,
        conversation_config=conversation_config,
        retrieval_config=retrieval_config,
        generation_config=generation_config,
        skill=skill,
        provider_id=provider_id,
        session_id=session_id,
    )
    return _mark_run_queued(db, run.id)


async def wait_for_chat_run_terminal(
    db: Session,
    *,
    tenant_id: str,
    run_id: str,
    timeout_seconds: float | None = None,
) -> ChatRun:
    started = time.monotonic()
    while True:
        run = _load_run_snapshot(
            db,
            tenant_id=tenant_id,
            run_id=run_id,
            refresh_transaction=True,
        )
        if run.status in TERMINAL_RUN_STATUSES:
            return run
        if timeout_seconds is not None and time.monotonic() - started > timeout_seconds:
            raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Timed out waiting for chat run")
        await asyncio.sleep(settings.chat_run_poll_interval_ms / 1000)


async def create_chat_run(
    db: Session,
    *,
    principal: Principal,
    user: User,
    document: Document,
    version: DocumentVersion,
    question: str,
    model: str | None,
    request_config: dict,
    conversation_config: dict | None = None,
    retrieval_config: dict | None = None,
    generation_config: dict | None = None,
    skill: ChatSkill | None = None,
    provider_id: str | None = None,
    session_id: str | None = None,
) -> ChatRun:
    run = await _create_and_enqueue_run(
        db,
        principal=principal,
        user=user,
        document=document,
        version=version,
        question=question,
        model=model,
        request_config=request_config,
        conversation_config=conversation_config,
        retrieval_config=retrieval_config,
        generation_config=generation_config,
        skill=skill,
        provider_id=provider_id,
        session_id=session_id,
    )
    return await wait_for_chat_run_terminal(
        db,
        tenant_id=principal.tenant_id,
        run_id=run.id,
        timeout_seconds=settings.chat_run_request_timeout_seconds,
    )


def get_run_or_404(db: Session, principal: Principal, run_id: str) -> ChatRun:
    run = db.scalar(
        select(ChatRun).where(
            ChatRun.id == run_id,
            ChatRun.tenant_id == principal.tenant_id,
            _run_workspace_filter(db, principal),
        )
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    if run.skill_id:
        visible_skills = _load_visible_skill_map(db, principal, {run.skill_id})
        if run.skill_id not in visible_skills:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return run


def list_runs_for_principal(
    db: Session,
    principal: Principal,
    *,
    skill_id: str | None = None,
    document_id: str | None = None,
    session_id: str | None = None,
) -> list[ChatRun]:
    stmt = select(ChatRun).where(
        ChatRun.tenant_id == principal.tenant_id,
        _run_workspace_filter(db, principal),
    )
    if skill_id:
        stmt = stmt.where(ChatRun.skill_id == skill_id)
    if document_id:
        stmt = stmt.where(ChatRun.document_id == document_id)
    if session_id:
        stmt = stmt.where(ChatRun.session_id == session_id)
    runs = db.scalars(stmt.order_by(ChatRun.created_at.desc())).all()
    skill_ids = {run.skill_id for run in runs if run.skill_id}
    if not skill_ids:
        return runs
    visible_skills = _load_visible_skill_map(db, principal, skill_ids)
    return [run for run in runs if run.skill_id is None or run.skill_id in visible_skills]


def _claim_session_slot(db: Session, run: ChatRun) -> bool:
    if not run.session_id:
        return True
    older_exists = exists().where(_session_ordering_filter(run))
    result = db.execute(
        update(ChatSession)
        .where(
            ChatSession.id == run.session_id,
            ChatSession.tenant_id == run.tenant_id,
            ChatSession.active_run_id.is_(None),
            ~older_exists,
        )
        .values(active_run_id=run.id, updated_at=datetime.utcnow())
    )
    db.commit()
    return result.rowcount > 0


def _release_session_slot(db: Session, run: ChatRun) -> None:
    if not run.session_id:
        return
    db.execute(
        update(ChatSession)
        .where(
            ChatSession.id == run.session_id,
            ChatSession.active_run_id == run.id,
        )
        .values(active_run_id=None, updated_at=datetime.utcnow())
    )
    db.commit()


def _touch_run_heartbeat(db: Session, run: ChatRun) -> ChatRun:
    run.heartbeat_at = datetime.utcnow()
    db.commit()
    db.refresh(run)
    return run


def _raise_if_cancel_requested(db: Session, run: ChatRun) -> ChatRun:
    db.refresh(run)
    if not run.cancel_requested:
        return run
    reason = run.cancel_reason or "cancel requested"
    terminal_status = "failed" if reason == "client aborted stream" else "cancelled"
    raise ChatRunCancelled(reason, terminal_status=terminal_status)


async def request_run_cancel(
    db: Session,
    *,
    principal: Principal,
    run_id: str,
    reason: str,
) -> ChatRun:
    run = get_run_or_404(db, principal, run_id)
    if run.status in TERMINAL_RUN_STATUSES:
        return run

    run.cancel_requested = True
    run.cancel_reason = reason
    if run.status in {"accepted", "queued"}:
        return await _finalize_run(
            db,
            run=run,
            status_value="failed" if reason == "client aborted stream" else "cancelled",
            last_error=reason if reason == "client aborted stream" else None,
        )

    db.commit()
    db.refresh(run)
    return run


def mark_orphaned_chat_runs_for_retry(db: Session) -> list[str]:
    cutoff = datetime.utcnow() - timedelta(seconds=settings.chat_run_lease_timeout_seconds)
    stale_runs = db.scalars(
        select(ChatRun).where(
            ChatRun.status.in_(ACTIVE_RUN_STATUSES | {"queued"}),
            ChatRun.heartbeat_at.is_not(None),
            ChatRun.heartbeat_at < cutoff,
        )
    ).all()
    requeued_ids: list[str] = []
    for run in stale_runs:
        run.status = "queued"
        run.worker_node_code = None
        run.claimed_at = None
        run.heartbeat_at = datetime.utcnow()
        run.last_error = "worker lease expired; requeued"
        run.metrics_json = _run_metrics_with_error(run, "worker lease expired; requeued")
        if run.session_id:
            db.execute(
                update(ChatSession)
                .where(ChatSession.id == run.session_id, ChatSession.active_run_id == run.id)
                .values(active_run_id=None, updated_at=datetime.utcnow())
            )
        requeued_ids.append(run.id)
    if requeued_ids:
        db.commit()
    return requeued_ids


async def _finalize_run(
    db: Session,
    *,
    run: ChatRun,
    status_value: str,
    last_error: str | None = None,
    publish_terminal_events: bool = True,
) -> ChatRun:
    run.status = status_value
    run.finished_at = datetime.utcnow()
    run.worker_node_code = None
    run.claimed_at = None
    run.heartbeat_at = datetime.utcnow()
    run.last_error = last_error
    if last_error:
        run.metrics_json = _run_metrics_with_error(run, last_error)
    db.commit()
    db.refresh(run)
    _release_session_slot(db, run)
    if publish_terminal_events:
        await _publish_chat_event(run.id, "status", {"status": run.status})
        if run.status == "completed":
            await _publish_chat_event(run.id, "run_completed", serialize_run(run))
        elif run.status == "failed":
            await _publish_chat_event(
                run.id,
                "error",
                {
                    "code": "skill_stream_failed",
                    "message": last_error or "run failed",
                    "detail": last_error or "run failed",
                },
            )
    await close_chat_event_stream(run.id)
    return run


async def run_chat_run(run_id: str) -> None:
    db = SessionLocal()
    trace_recorder: SkillTraceRecorder | None = None
    try:
        requeued_ids = mark_orphaned_chat_runs_for_retry(db)
        for stale_run_id in requeued_ids:
            enqueue_chat_run(stale_run_id)

        run = db.get(ChatRun, run_id)
        if run is None or run.status in TERMINAL_RUN_STATUSES:
            return

        if run.cancel_requested and run.status in {"accepted", "queued"}:
            await _finalize_run(
                db,
                run=run,
                status_value="failed" if run.cancel_reason == "client aborted stream" else "cancelled",
                last_error=run.cancel_reason,
            )
            return

        if not _claim_session_slot(db, run):
            await asyncio.sleep(settings.chat_run_queue_retry_delay_ms / 1000)
            enqueue_chat_run(run.id)
            return

        run = db.get(ChatRun, run_id)
        if run is None or run.status in TERMINAL_RUN_STATUSES:
            return

        run.status = "retrieving"
        now = datetime.utcnow()
        run.started_at = run.started_at or now
        run.claimed_at = now
        run.heartbeat_at = now
        run.worker_node_code = settings.worker_node_code
        run.last_error = None
        db.commit()
        db.refresh(run)

        user = db.get(User, run.user_id)
        document = db.get(Document, run.document_id) if run.document_id else None
        version = db.get(DocumentVersion, run.version_id) if run.version_id else None
        skill = db.get(ChatSkill, run.skill_id) if run.skill_id else None
        session = db.get(ChatSession, run.session_id) if run.session_id else None
        if user is None or document is None or version is None:
            raise RuntimeError("Run dependencies not found")
        if not version.parsed_structure_path or version.parse_status != "index_ready":
            raise RuntimeError("Document is not ready for querying yet")

        request_config = _json_loads(run.request_config_json, {})
        conversation_config = _json_loads(run.conversation_config_json, {})
        retrieval_config = _json_loads(run.retrieval_config_json, {})
        generation_config = _json_loads(run.generation_config_json, {})
        provider_config = resolve_provider_config(
            db,
            run.tenant_id,
            skill=skill,
            explicit_provider_id=run.provider_id,
        )
        resolved_model = validate_provider_model_selection(
            provider_id=provider_config.get("provider_id"),
            provider_type=provider_config.get("provider_type"),
            provider_name=provider_config.get("name"),
            default_model=provider_config.get("default_model"),
            supported_models=provider_config.get("supported_models"),
            model=run.model,
            subject="Chat run model",
        )

        history_messages: list[dict] = []
        history_info = {
            "used": False,
            "history_messages_used": 0,
            "history_turns_used": 0,
            "history_token_estimate": 0,
        }
        if session and skill:
            history_messages, history_info = _load_session_history(
                db,
                tenant_id=run.tenant_id,
                workspace_id=session.workspace_id,
                session_id=session.id,
                model=resolved_model,
                conversation_config=conversation_config,
                current_question=run.question,
            )

        trace_recorder = (
            SkillTraceRecorder(
                tenant_id=run.tenant_id,
                run_id=run.id,
                user=user,
                skill=skill,
                document=document,
                version=version,
                question=run.question,
                model=resolved_model,
                request_config=request_config,
            )
            if skill
            else None
        )

        run = _raise_if_cancel_requested(db, run)
        if session:
            append_message(
                db,
                session_id=session.id,
                tenant_id=run.tenant_id,
                user_id=run.user_id,
                role="user",
                content=run.question,
                run_id=run.id,
            )
        await _publish_chat_event(run.id, "status", {"status": "retrieving"})

        usage_totals = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "successful_llm_calls": 0,
        }

        def stats_hook(event: dict) -> None:
            if not event.get("ok"):
                return
            usage = event.get("usage") or {}
            usage_totals["successful_llm_calls"] += 1
            _accumulate_usage_totals(usage_totals, usage)

        request_options = {key: value for key, value in request_config.items() if key not in {"system_prompt"}}
        request_options.update(
            {
                "api_base": provider_config["base_url"],
                "api_key": provider_config["api_key"],
                "extra_headers": provider_config.get("extra_headers") or {},
            }
        )
        retrieval_options = {
            **dict(retrieval_config or {}),
            "api_base": provider_config["base_url"],
            "api_key": provider_config["api_key"],
            "extra_headers": provider_config.get("extra_headers") or {},
        }
        generation_options = {
            **dict(generation_config or {}),
            "api_base": provider_config["base_url"],
            "api_key": provider_config["api_key"],
            "extra_headers": provider_config.get("extra_headers") or {},
        }

        structure = load_structure_file(version.parsed_structure_path)
        retrieve_started = time.perf_counter()
        top_k = int(retrieval_options.pop("top_k", 5) or 5)
        selection_mode = retrieval_options.pop("selection_mode", "outline_llm")
        max_context_pages = retrieval_options.pop("max_context_pages", None)
        max_context_tokens = retrieval_options.pop("max_context_tokens", None)

        history_context = (
            format_history_context(history_messages)
            if conversation_config.get("include_history", True) and history_messages
            else ""
        )
        retrieval_query = run.question
        rewritten_query = None
        rewrite_applied = False
        if conversation_config.get("query_rewrite_with_history", True) and history_context:
            try:
                rewrite_response = llm_completion(
                    model=resolved_model,
                    prompt=build_query_rewrite_prompt(run.question, history_context),
                    raise_on_error=True,
                    request_options=retrieval_options,
                    trace_hook=trace_recorder.append_llm_call if trace_recorder else None,
                    trace_label="query_rewrite",
                    stats_hook=stats_hook,
                )
                rewrite_payload = extract_json(rewrite_response)
                candidate = rewrite_payload.get("rewritten_query") if isinstance(rewrite_payload, dict) else None
                if isinstance(candidate, str) and candidate.strip():
                    rewritten_query = candidate.strip()
                    retrieval_query = rewritten_query
                    rewrite_applied = retrieval_query != run.question
            except Exception as exc:
                if is_fatal_llm_model_error(exc):
                    raise
                retrieval_query = run.question

        run = _touch_run_heartbeat(db, run)
        run = _raise_if_cancel_requested(db, run)
        selected_nodes = choose_relevant_nodes(
            structure,
            retrieval_query,
            resolved_model,
            request_options=retrieval_options,
            trace_hook=trace_recorder.append_llm_call if trace_recorder else None,
            stats_hook=stats_hook,
            top_k=top_k,
            selection_mode=selection_mode,
        )
        with local_artifact_path(version.storage_path) as pdf_path:
            context = build_answer_context(
                selected_nodes,
                str(pdf_path),
                resolved_model,
                max_context_pages=int(max_context_pages) if max_context_pages is not None else None,
                max_context_tokens=int(max_context_tokens) if max_context_tokens is not None else None,
            )

        retrieve_ms = int((time.perf_counter() - retrieve_started) * 1000)
        retrieval_info = {
            "query": retrieval_query,
            "rewritten_query": rewritten_query,
            "rewrite_applied": rewrite_applied,
            "top_k": top_k,
            "selection_mode": selection_mode,
            "max_context_pages": int(max_context_pages) if max_context_pages is not None else None,
            "max_context_tokens": int(max_context_tokens) if max_context_tokens is not None else None,
        }
        generation_info = {
            "temperature": generation_options.get("temperature"),
        }
        execution_context = _build_execution_context(
            provider_config=provider_config,
            resolved_model=resolved_model,
            conversation_config=conversation_config,
            history_info=history_info,
            retrieval_info=retrieval_info,
            generation_info=generation_info,
        )
        run.execution_context_json = json.dumps(execution_context, ensure_ascii=False)
        run.status = "answering"
        run.heartbeat_at = datetime.utcnow()
        db.commit()
        db.refresh(run)
        run = _raise_if_cancel_requested(db, run)
        await _publish_chat_event(run.id, "context", {"execution_context": execution_context})
        await _publish_chat_event(run.id, "status", {"status": "answering"})

        answer_prompt = build_generation_prompt(
            run.question,
            selected_nodes,
            context,
            system_prompt=request_config.get("system_prompt") or (skill.system_prompt if skill else None),
            history_context=history_context or None,
        )
        completion_kwargs = {
            "model": resolved_model.removeprefix("litellm/"),
            "messages": [{"role": "user", "content": answer_prompt}],
            "temperature": generation_options.get("temperature", 0),
            "stream": True,
            **generation_options,
        }
        stream_options = dict(completion_kwargs.get("stream_options") or {})
        stream_options["include_usage"] = True
        completion_kwargs["stream_options"] = stream_options
        answer_started = time.perf_counter()
        response = litellm.completion(**completion_kwargs)
        answer_parts: list[str] = []
        seq = 0
        finish_reason = None
        streamed_usage = None
        for chunk in response:
            run = _touch_run_heartbeat(db, run)
            run = _raise_if_cancel_requested(db, run)
            chunk_usage = _extract_usage_from_stream_chunk(chunk)
            if chunk_usage:
                streamed_usage = chunk_usage
            choices = getattr(chunk, "choices", None)
            if not choices:
                continue
            choice = choices[0]
            finish_reason = getattr(choice, "finish_reason", None) or finish_reason
            delta = ""
            if getattr(choice, "delta", None) is not None:
                delta = choice.delta.content or ""
            if not delta:
                continue
            answer_parts.append(delta)
            seq += 1
            await _publish_chat_event(run.id, "answer_delta", {"delta": delta, "seq": seq})

        answer_text = "".join(answer_parts).strip()
        answer_ms = int((time.perf_counter() - answer_started) * 1000)
        citations = build_citations(selected_nodes)
        answer_with_marker = build_answer_with_marker(answer_text, citations)
        if streamed_usage:
            usage_totals["successful_llm_calls"] += 1
            _accumulate_usage_totals(usage_totals, streamed_usage)
            stream_usage_source = "provider_stream"
        else:
            prompt_tokens = count_tokens(answer_prompt, model=resolved_model)
            completion_tokens = count_tokens(answer_text, model=resolved_model)
            fallback_usage = {
                "prompt_tokens": prompt_tokens + history_info["history_token_estimate"],
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + history_info["history_token_estimate"] + completion_tokens,
            }
            usage_totals["successful_llm_calls"] += 1
            _accumulate_usage_totals(usage_totals, fallback_usage)
            stream_usage_source = "estimated_fallback"
        metrics = {
            "retrieve_ms": retrieve_ms,
            "answer_ms": answer_ms,
            "total_ms": retrieve_ms + answer_ms,
            "input_tokens": usage_totals["input_tokens"],
            "output_tokens": usage_totals["output_tokens"],
            "total_tokens": usage_totals["total_tokens"],
            "manual_count": 1,
            "selected_section_count": len(selected_nodes),
            "successful_llm_calls": usage_totals["successful_llm_calls"],
            "citations_count": len(citations),
            "stream_usage_source": stream_usage_source,
        }
        serialized_sections = [
            {
                "node_id": node.get("node_id"),
                "title": node.get("title"),
                "start_index": node.get("start_index"),
                "end_index": node.get("end_index"),
            }
            for node in selected_nodes
        ]
        run.answer = answer_text
        run.answer_text = answer_text
        run.answer_with_marker = answer_with_marker
        run.selected_sections_json = json.dumps(serialized_sections, ensure_ascii=False)
        run.citations_json = json.dumps(citations, ensure_ascii=False)
        run.metrics_json = json.dumps(metrics, ensure_ascii=False)
        run.last_error = None
        run.heartbeat_at = datetime.utcnow()
        db.commit()
        db.refresh(run)

        if session:
            append_message(
                db,
                session_id=session.id,
                tenant_id=run.tenant_id,
                user_id=run.user_id,
                role="assistant",
                content=answer_text,
                run_id=run.id,
            )
        if trace_recorder:
            trace_recorder.append_llm_call(
                {
                    "type": "llm_completion",
                    "label": "final_answer_stream",
                    "ok": True,
                    "request": {
                        "model": completion_kwargs["model"],
                        "temperature": completion_kwargs.get("temperature"),
                    },
                    "response_text": answer_text,
                    "finish_reason": finish_reason,
                }
            )
            trace_recorder.finalize(
                status="completed",
                answer=answer_text,
                metrics=metrics,
                selected_sections=serialized_sections,
                execution_context=execution_context,
            )
        await _finalize_run(db, run=run, status_value="completed")
    except ChatRunCancelled as exc:
        run = db.get(ChatRun, run_id)
        if run is not None:
            if trace_recorder:
                trace_recorder.finalize(
                    status=exc.terminal_status,
                    error=exc.reason,
                    execution_context=_json_loads(run.execution_context_json, {}),
                )
            await _finalize_run(db, run=run, status_value=exc.terminal_status, last_error=exc.reason)
    except Exception as exc:
        run = db.get(ChatRun, run_id)
        if run is not None:
            if trace_recorder:
                trace_recorder.finalize(
                    status="failed",
                    error=str(exc),
                    execution_context=_json_loads(run.execution_context_json, {}),
                )
            await _finalize_run(db, run=run, status_value="failed", last_error=str(exc))
        else:
            await close_chat_event_stream(run_id)
        return
    finally:
        db.close()


async def stream_skill_run_events(
    db: Session,
    *,
    principal: Principal,
    user: User,
    skill,
    document: Document,
    version: DocumentVersion,
    question: str,
    model: str | None,
    request_config: dict,
    conversation_config: dict | None,
    retrieval_config: dict | None,
    generation_config: dict | None,
    provider_id: str | None = None,
    session_id: str | None = None,
    disconnect_check: Callable[[], Awaitable[bool]] | None = None,
):
    run = _create_pending_run(
        db,
        principal=principal,
        user=user,
        document=document,
        version=version,
        question=question,
        model=model,
        request_config=request_config,
        conversation_config=conversation_config,
        retrieval_config=retrieval_config,
        generation_config=generation_config,
        skill=skill,
        provider_id=provider_id,
        session_id=session_id,
    )

    yield {
        "event": "run_started",
        "data": {
            "run_id": run.id,
            "session_id": run.session_id,
            "created_at": run.created_at.isoformat() if run.created_at else None,
        },
    }
    yield {"event": "status", "data": {"status": "accepted"}}

    subscription = await open_chat_event_subscription(run.id)
    try:
        _mark_run_queued(db, run.id)
        yield {"event": "status", "data": {"status": "queued"}}
        while True:
            if disconnect_check and await disconnect_check():
                await request_run_cancel(
                    db,
                    principal=principal,
                    run_id=run.id,
                    reason="client aborted stream",
                )
                raise asyncio.CancelledError
            try:
                event = await subscription.next_event(timeout=max(settings.chat_run_poll_interval_ms / 1000, 0.2))
            except asyncio.TimeoutError:
                current = _load_run_snapshot(
                    db,
                    tenant_id=run.tenant_id,
                    run_id=run.id,
                    refresh_transaction=True,
                )
                if current.status in TERMINAL_RUN_STATUSES:
                    if current.status == "completed":
                        yield {"event": "status", "data": {"status": "completed"}}
                        yield {"event": "run_completed", "data": serialize_run(current)}
                        return
                    if current.status == "cancelled":
                        yield {"event": "status", "data": {"status": "cancelled"}}
                        return
                    if current.status == "failed":
                        yield {"event": "status", "data": {"status": "failed"}}
                        yield {
                            "event": "error",
                            "data": {
                                "code": "skill_stream_failed",
                                "message": current.last_error or "run failed",
                                "detail": current.last_error or "run failed",
                            },
                        }
                        return
                    return
                continue
            except StopAsyncIteration:
                current = _load_run_snapshot(
                    db,
                    tenant_id=run.tenant_id,
                    run_id=run.id,
                    refresh_transaction=True,
                )
                if current.status == "completed":
                    yield {"event": "status", "data": {"status": "completed"}}
                    yield {"event": "run_completed", "data": serialize_run(current)}
                elif current.status == "cancelled":
                    yield {"event": "status", "data": {"status": "cancelled"}}
                elif current.status == "failed":
                    yield {"event": "status", "data": {"status": "failed"}}
                    yield {
                        "event": "error",
                        "data": {
                            "code": "skill_stream_failed",
                            "message": current.last_error or "run failed",
                            "detail": current.last_error or "run failed",
                        },
                    }
                return

            yield event
            if event["event"] == "run_completed":
                return
            if event["event"] == "error":
                return
            if event["event"] == "status" and event["data"].get("status") == "cancelled":
                return
    finally:
        await subscription.close()


def resolve_document_version(
    db: Session,
    principal: Principal,
    document_id: str,
    version_id: str | None = None,
) -> tuple[Document, DocumentVersion]:
    document = get_document_or_404(db, principal, document_id)
    target_version_id = version_id or document.active_version_id
    if target_version_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Document has no active version")
    version = db.get(DocumentVersion, target_version_id)
    if version is None or version.document_id != document.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document version not found")
    return document, version
