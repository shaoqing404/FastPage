import asyncio
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

import litellm
from fastapi import HTTPException, status
from sqlalchemy import and_, exists, or_, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.principal import Principal
from app.models import ChatRun, ChatSession, ChatSkill, Document, DocumentVersion, User
from app.services.document_service import get_document_or_404
from app.services.knowledge_base_service import resolve_ready_knowledge_base_manuals
from app.services.pageindex_service import (
    build_answer_with_marker,
    build_context_from_citations_async,
    build_generation_prompt,
    build_query_rewrite_prompt,
    extract_json_with_repair,
    format_history_context,
    load_structure_file,
    rerank_candidates_async,
    retrieve_candidates_for_manual_async,
)
from app.services.provider_service import resolve_provider_config, resolve_rerank_config, validate_provider_model_selection
from app.services.runtime_observation_service import record_run_observation_event
from app.services.session_service import _is_default_workspace, append_message, get_session_or_404, list_session_messages
from app.services.skill_trace_service import SkillTraceRecorder
from app.services.task_queue_service import (
    close_chat_event_stream,
    enqueue_chat_run,
    open_chat_event_subscription,
    publish_chat_event,
)
from app.services.workspace_access_service import can_read_skill
from pageindex.utils import count_tokens, is_fatal_llm_model_error, llm_completion


settings = get_settings()
logger = logging.getLogger(__name__)

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

RUN_LOG_PROMPT_PREVIEW_CHARS = 4000


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
    if "rerank_mode" in retrieval:
        rerank_mode = str(retrieval["rerank_mode"]).strip().lower()
        if rerank_mode not in {"auto", "off", "provider", "system"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="rerank mode must be one of: auto, off, provider, system",
            )
        retrieval["rerank_mode"] = rerank_mode
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


def _preview_log_text(text: str | None, *, max_chars: int = RUN_LOG_PROMPT_PREVIEW_CHARS) -> str:
    normalized = (text or "").replace("\r\n", "\n").strip()
    if not normalized:
        return ""
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rstrip() + "\n...[truncated]"


def _extract_request_prompt_text(request: dict | None) -> str:
    if not isinstance(request, dict):
        return ""
    messages = request.get("messages")
    if isinstance(messages, list) and messages:
        last_message = messages[-1]
        if isinstance(last_message, dict):
            content = last_message.get("content", "")
            if isinstance(content, list):
                return json.dumps(content, ensure_ascii=False)
            return str(content or "")
    prompt = request.get("prompt")
    if prompt is None:
        return ""
    return str(prompt)


def _log_chat_run_stage(run: ChatRun, stage: str, **fields) -> None:
    payload = {
        "run_id": run.id,
        "status": run.status,
        "skill_id": run.skill_id,
        "session_id": run.session_id,
        "document_id": run.document_id,
        "version_id": run.version_id,
        "worker_node_code": run.worker_node_code,
    }
    payload.update(fields)
    logger.info("chat_run[%s] %s", stage, json.dumps(payload, ensure_ascii=False, default=str))


def _log_chat_run_llm_event(run: ChatRun, event: dict) -> None:
    request = event.get("request") or {}
    prompt_text = _extract_request_prompt_text(request)
    payload = {
        "run_id": run.id,
        "skill_id": run.skill_id,
        "label": event.get("label"),
        "phase": event.get("phase"),
        "attempt": event.get("attempt"),
        "ok": event.get("ok"),
        "duration_ms": event.get("duration_ms"),
        "model": request.get("model") or run.model,
        "temperature": request.get("temperature"),
        "prompt_chars": len(prompt_text),
        "error": event.get("error"),
        "finish_reason": event.get("finish_reason"),
    }
    logger.info("chat_run[llm] %s", json.dumps(payload, ensure_ascii=False, default=str))
    preview = _preview_log_text(prompt_text)
    if preview:
        logger.info(
            "chat_run[llm_prompt] run_id=%s label=%s phase=%s\n%s",
            run.id,
            event.get("label"),
            event.get("phase"),
            preview,
        )


def _make_run_trace_hook(run: ChatRun, trace_recorder: SkillTraceRecorder | None):
    def hook(event: dict) -> None:
        if trace_recorder and event.get("phase") != "request":
            trace_recorder.append_llm_call(event)
        _log_chat_run_llm_event(run, event)
        try:
            asyncio.get_running_loop().create_task(_record_chat_llm_event(run, event))
        except RuntimeError:
            pass

    return hook


def _humanize_run_error(error: str | None) -> str | None:
    if not error:
        return error
    normalized = error.strip()
    lowered = normalized.lower()

    known_messages = (
        ("llm provider not provided", "模型提供方未正确解析。当前运行拿到了模型名，但没有可用的 provider 类型。请优先检查技能绑定的 provider、系统默认 provider，以及模型名是否与 provider 类型匹配。"),
        ("fatal model configuration error", "模型配置无效，当前 provider 无法识别或调用这个模型。请检查已绑定 provider、默认模型和模型名格式是否匹配。"),
        ("model_not_found", "模型不存在或当前 provider 不支持这个模型。请检查模型名和 provider 配置。"),
        ("unknown model", "模型不存在或当前 provider 不支持这个模型。请检查模型名和 provider 配置。"),
        ("unsupported model", "当前 provider 不支持这个模型。请检查模型名和 provider 的支持列表。"),
        ("no model resolved for this skill", "当前技能没有解析出可运行的模型。请先绑定可用 provider，或选择一个有效模型。"),
        ("skill has no target document", "当前技能没有可查询的目标文档。请先绑定知识库或文档。"),
        ("document is not ready for querying yet", "目标文档尚未完成索引，暂时不能运行。请等待文档状态变为可查询后再试。"),
        ("llm completion failed after", "模型调用失败。请检查 provider 连通性、API key、模型名和上游服务状态。"),
    )
    for pattern, localized in known_messages:
        if pattern in lowered:
            return f"{localized}\n原始错误: {normalized}"
    return normalized


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


def _skill_manual_snapshot(skill: ChatSkill, manuals: list[dict]) -> dict:
    knowledge_base_id = getattr(skill, "knowledge_base_id", None)
    return {
        "mode": "knowledge_base" if knowledge_base_id else "documents",
        "knowledge_base_id": knowledge_base_id,
        "manuals": [
            {
                "document_id": manual["document"].id,
                "version_id": manual["version"].id,
                "document_label": manual["document_label"],
                "version_label": manual["version_label"],
                "storage_path": getattr(manual["version"], "storage_path", None),
                "parsed_structure_path": getattr(manual["version"], "parsed_structure_path", None),
            }
            for manual in manuals
        ],
    }


def resolve_skill_run_targets(
    db: Session,
    *,
    principal: Principal,
    skill: ChatSkill,
    document_id: str | None = None,
) -> tuple[Document | None, DocumentVersion | None, dict]:
    knowledge_base_id = getattr(skill, "knowledge_base_id", None)
    knowledge_base = getattr(skill, "knowledge_base", None)
    workspace_id = getattr(skill, "workspace_id", principal.workspace_id)
    documents = list(getattr(skill, "documents", []) or [])

    if knowledge_base_id and knowledge_base is not None:
        manuals = resolve_ready_knowledge_base_manuals(
            db,
            principal,
            workspace_id,
            knowledge_base,
        )
        return None, None, _skill_manual_snapshot(skill, manuals)

    if document_id:
        document, version = resolve_document_version(db, principal, document_id, None)
        manual = {
            "document": document,
            "version": version,
            "document_label": document.display_name,
            "version_label": f"v{version.version_no}",
        }
        return document, version, _skill_manual_snapshot(skill, [manual])

    if not documents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Skill has no target document")
    document, version = resolve_document_version(db, principal, documents[0].document_id, None)
    manual = {
        "document": document,
        "version": version,
        "document_label": document.display_name,
        "version_label": f"v{version.version_no}",
    }
    return document, version, _skill_manual_snapshot(skill, [manual])


async def _record_chat_observation(
    run: ChatRun,
    *,
    event_type: str,
    step: str | None = None,
    status_value: str | None = None,
    payload: dict | None = None,
) -> None:
    await record_run_observation_event(
        run_kind="chat",
        run_id=run.id,
        tenant_id=run.tenant_id,
        workspace_id=run.workspace_id,
        event_type=event_type,
        step=step,
        status_value=status_value,
        payload=payload,
    )


async def _record_chat_step_started(run: ChatRun, step: str, payload: dict | None = None) -> None:
    await _record_chat_observation(run, event_type="step_started", step=step, status_value=run.status, payload=payload)


async def _record_chat_step_completed(run: ChatRun, step: str, payload: dict | None = None) -> None:
    await _record_chat_observation(run, event_type="step_completed", step=step, status_value=run.status, payload=payload)


async def _record_chat_llm_event(run: ChatRun, event: dict) -> None:
    request = event.get("request") or {}
    payload = {
        "label": event.get("label"),
        "phase": event.get("phase"),
        "attempt": event.get("attempt"),
        "ok": event.get("ok"),
        "duration_ms": event.get("duration_ms"),
        "model": request.get("model") or run.model,
        "temperature": request.get("temperature"),
        "prompt_text": _extract_request_prompt_text(request),
        "response_text": event.get("response_text"),
        "finish_reason": event.get("finish_reason"),
        "error": event.get("error"),
    }
    await _record_chat_observation(
        run,
        event_type="llm_request" if event.get("phase") == "request" else "llm_response",
        step=event.get("label"),
        status_value=run.status,
        payload=payload,
    )


async def _retry_async(step_name: str, operation, *, retries: int, base_delay_ms: int, run: ChatRun) -> Any:
    attempt = 0
    while True:
        try:
            return await operation()
        except Exception as exc:
            attempt += 1
            if attempt > retries:
                raise
            await _record_chat_observation(
                run,
                event_type="step_failed",
                step=step_name,
                status_value=run.status,
                payload={
                    "attempt": attempt,
                    "retrying": True,
                    "error": str(exc),
                    "next_retry_delay_ms": base_delay_ms * (2 ** (attempt - 1)),
                },
            )
            await asyncio.sleep((base_delay_ms * (2 ** (attempt - 1))) / 1000)


def _load_run_manual_targets(run: ChatRun, skill: ChatSkill | None) -> tuple[list[dict], str | None]:
    request_config = _json_loads(run.request_config_json, {})
    target_snapshot = request_config.get("_run_target")
    if isinstance(target_snapshot, dict):
        manuals = target_snapshot.get("manuals")
        if isinstance(manuals, list) and manuals:
            return [dict(manual) for manual in manuals if isinstance(manual, dict)], target_snapshot.get("knowledge_base_id")
    if run.document_id and run.version_id:
        return [
            {
                "document_id": run.document_id,
                "version_id": run.version_id,
                "document_label": None,
                "version_label": None,
            }
        ], skill.knowledge_base_id if skill else None
    return [], skill.knowledge_base_id if skill else None


def _citation_from_candidate(candidate: dict, *, knowledge_base_id: str | None, index: int) -> dict:
    return {
        "citation_id": f"cit_{index}",
        "knowledge_base_id": knowledge_base_id,
        "document_id": candidate.get("document_id"),
        "version_id": candidate.get("version_id"),
        "node_id": candidate.get("node_id"),
        "title": candidate.get("title"),
        "page_start": candidate.get("page_start"),
        "page_end": candidate.get("page_end"),
        "snippet_id": f"{candidate.get('document_id')}:{candidate.get('version_id')}:{candidate.get('node_id')}",
        "document_label": candidate.get("document_label"),
        "version_label": candidate.get("version_label"),
        "rerank_score": candidate.get("rerank_score"),
        "_node": candidate.get("_node"),
        "_storage_path": candidate.get("_storage_path"),
    }


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
    exposed_error = _humanize_run_error(run.last_error)
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
        "last_error": exposed_error,
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
    document: Document | None,
    version: DocumentVersion | None,
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
    if version is not None and (not version.parsed_structure_path or version.parse_status != "index_ready"):
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
    ) or (document.workspace_id if document is not None else None) or (skill.workspace_id if skill else None)
    run = ChatRun(
        id=str(uuid.uuid4()),
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        user_id=user.id,
        session_id=session.id if session else None,
        document_id=document.id if document is not None else None,
        version_id=version.id if version is not None else None,
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
    document: Document | None,
    version: DocumentVersion | None,
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
    document: Document | None,
    version: DocumentVersion | None,
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
    await _record_chat_observation(
        run,
        event_type="run_status",
        status_value="accepted",
        payload={"created_at": run.created_at.isoformat() if run.created_at else None},
    )
    await _record_chat_observation(run, event_type="run_status", status_value="queued", payload=None)
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
            await _record_chat_observation(run, event_type="run_completed", status_value=run.status, payload=serialize_run(run))
            await _publish_chat_event(run.id, "run_completed", serialize_run(run))
        elif run.status == "failed":
            exposed_error = _humanize_run_error(last_error or "run failed")
            await _record_chat_observation(
                run,
                event_type="run_failed",
                status_value=run.status,
                payload={"error": exposed_error},
            )
            await _publish_chat_event(
                run.id,
                "error",
                {
                    "code": "skill_stream_failed",
                    "message": exposed_error,
                    "detail": exposed_error,
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
            _log_chat_run_stage(
                run,
                "session_wait_requeue",
                reason="older_session_run_active",
                retry_delay_ms=settings.chat_run_queue_retry_delay_ms,
            )
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
        queue_ms = (
            max(int((run.started_at - run.created_at).total_seconds() * 1000), 0)
            if run.started_at and run.created_at
            else 0
        )
        _log_chat_run_stage(
            run,
            "claimed",
            queue_ms=queue_ms,
            question_preview=_preview_log_text(run.question, max_chars=300),
        )
        await _record_chat_observation(
            run,
            event_type="run_status",
            status_value=run.status,
            payload={"queue_ms": queue_ms, "worker_node_code": run.worker_node_code},
        )

        user = db.get(User, run.user_id)
        document = db.get(Document, run.document_id) if run.document_id else None
        version = db.get(DocumentVersion, run.version_id) if run.version_id else None
        skill = db.get(ChatSkill, run.skill_id) if run.skill_id else None
        session = db.get(ChatSession, run.session_id) if run.session_id else None
        if user is None:
            raise RuntimeError("Run dependencies not found")

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
        _log_chat_run_stage(
            run,
            "provider_resolved",
            provider_id=provider_config.get("provider_id"),
            provider_type=provider_config.get("provider_type"),
            provider_name=provider_config.get("name"),
            resolved_model=resolved_model,
        )
        await _record_chat_observation(
            run,
            event_type="run_status",
            status_value=run.status,
            payload={
                "provider_id": provider_config.get("provider_id"),
                "provider_name": provider_config.get("name"),
                "resolved_model": resolved_model,
            },
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
        _log_chat_run_stage(
            run,
            "history_prepared",
            history_used=history_info["used"],
            history_messages_used=history_info["history_messages_used"],
            history_turns_used=history_info["history_turns_used"],
            history_token_estimate=history_info["history_token_estimate"],
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
            if skill and document is not None and version is not None
            else None
        )
        run_trace_hook = _make_run_trace_hook(run, trace_recorder)

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
        rerank_mode = str(retrieval_options.get("rerank_mode") or "auto")
        retrieve_started = time.perf_counter()
        top_k = int(retrieval_options.pop("top_k", 5) or 5)
        candidate_top_k = max(top_k * 3, 12)
        selection_mode = retrieval_options.pop("selection_mode", "outline_llm")
        max_context_pages = retrieval_options.pop("max_context_pages", None)
        max_context_tokens = retrieval_options.pop("max_context_tokens", None)
        retrieval_options.pop("rerank_mode", None)
        _log_chat_run_stage(
            run,
            "retrieval_started",
            top_k=top_k,
            candidate_top_k=candidate_top_k,
            selection_mode=selection_mode,
            max_context_pages=max_context_pages,
            max_context_tokens=max_context_tokens,
        )

        history_context = (
            format_history_context(history_messages)
            if conversation_config.get("include_history", True) and history_messages
            else ""
        )
        retrieval_query = run.question
        rewritten_query = None
        rewrite_applied = False
        retrieval_warnings: list[str] = []
        rewrite_strategy = "not_used"
        outline_diagnostics: dict[str, object] = {}
        if conversation_config.get("query_rewrite_with_history", True) and history_context:
            try:
                rewrite_response = llm_completion(
                    model=resolved_model,
                    prompt=build_query_rewrite_prompt(run.question, history_context),
                    raise_on_error=True,
                    request_options=retrieval_options,
                    trace_hook=run_trace_hook,
                    trace_label="query_rewrite",
                    stats_hook=stats_hook,
                )
                rewrite_payload, rewrite_meta = extract_json_with_repair(
                    raw_response=rewrite_response,
                    model=resolved_model,
                    request_options=retrieval_options,
                    trace_hook=run_trace_hook,
                    stats_hook=stats_hook,
                    trace_label="query_rewrite",
                    schema_hint='{"rewritten_query": "..."}',
                    expected_keys=("rewritten_query",),
                )
                if rewrite_meta.get("repair_succeeded"):
                    retrieval_warnings.append("查询改写返回的 JSON 不规范，系统已自动修复后继续运行。")
                    rewrite_strategy = "llm_json_repaired"
                elif rewrite_meta.get("repair_applied"):
                    retrieval_warnings.append("查询改写返回的 JSON 无法修复，系统已回退为原始问题继续检索。")
                    rewrite_strategy = "original_after_invalid_json"
                else:
                    rewrite_strategy = "llm_json_ok"
                candidate = rewrite_payload.get("rewritten_query") if isinstance(rewrite_payload, dict) else None
                if isinstance(candidate, str) and candidate.strip():
                    rewritten_query = candidate.strip()
                    retrieval_query = rewritten_query
                    rewrite_applied = retrieval_query != run.question
            except Exception as exc:
                if is_fatal_llm_model_error(exc):
                    raise
                retrieval_query = run.question
                rewrite_strategy = "original_after_llm_error"
                retrieval_warnings.append("查询改写模型调用失败，系统已回退为原始问题继续检索。")

        run = _touch_run_heartbeat(db, run)
        run = _raise_if_cancel_requested(db, run)
        await _record_chat_step_started(run, "resolve_manuals")
        manual_targets, knowledge_base_id = _load_run_manual_targets(run, skill)
        resolved_manuals: list[dict] = []
        for manual_target in manual_targets:
            target_document = db.get(Document, manual_target.get("document_id"))
            target_version = db.get(DocumentVersion, manual_target.get("version_id"))
            if target_document is None or target_version is None:
                raise RuntimeError("Run manual target is missing")
            if not target_version.parsed_structure_path or target_version.parse_status != "index_ready":
                raise RuntimeError("Document is not ready for querying yet")
            resolved_manuals.append(
                {
                    "document_id": target_document.id,
                    "version_id": target_version.id,
                    "document_label": manual_target.get("document_label") or target_document.display_name,
                    "version_label": manual_target.get("version_label") or f"v{target_version.version_no}",
                    "storage_path": manual_target.get("storage_path") or target_version.storage_path,
                    "parsed_structure_path": manual_target.get("parsed_structure_path") or target_version.parsed_structure_path,
                }
            )
        if not resolved_manuals:
            raise RuntimeError("Skill has no target document")
        if len(resolved_manuals) > settings.run_max_manuals:
            raise RuntimeError(f"Skill resolved too many manuals ({len(resolved_manuals)}). Maximum allowed is {settings.run_max_manuals}.")
        await _record_chat_step_completed(
            run,
            "resolve_manuals",
            {
                "manual_count": len(resolved_manuals),
                "knowledge_base_id": knowledge_base_id,
            },
        )

        await _record_chat_step_started(run, "load_structures")
        loaded_manuals = resolved_manuals
        await _record_chat_step_completed(run, "load_structures", {"manual_count": len(loaded_manuals), "lazy_loaded": True})

        await _record_chat_step_started(
            run,
            "retrieve_candidates",
            {"manual_count": len(loaded_manuals), "candidate_top_k": candidate_top_k},
        )
        semaphore = asyncio.Semaphore(max(1, min(settings.retrieval_max_concurrency, len(loaded_manuals))))

        async def retrieve_manual_candidates(manual: dict) -> list[dict]:
            diagnostics: dict[str, object] = {}

            async def operation():
                async with semaphore:
                    structure = load_structure_file(manual["parsed_structure_path"])
                    candidates = await retrieve_candidates_for_manual_async(
                        structure,
                        retrieval_query,
                        resolved_model,
                        request_options=retrieval_options,
                        trace_hook=run_trace_hook,
                        stats_hook=stats_hook,
                        candidate_top_k=candidate_top_k,
                        selection_mode=selection_mode,
                        diagnostics=diagnostics,
                    )
                    del structure
                    return candidates

            candidates = await _retry_async(
                "retrieve_candidates",
                operation,
                retries=settings.run_step_max_retries,
                base_delay_ms=settings.run_step_retry_base_ms,
                run=run,
            )
            retrieval_warnings.extend(
                warning
                for warning in diagnostics.get("warnings", [])
                if isinstance(warning, str) and warning not in retrieval_warnings
            )
            return [
                {
                    "candidate_id": f"{manual['document_id']}:{manual['version_id']}:{index}",
                    "document_id": manual["document_id"],
                    "version_id": manual["version_id"],
                    "document_label": manual["document_label"],
                    "version_label": manual["version_label"],
                    "title": candidate.get("title"),
                    "node_id": candidate.get("node_id"),
                    "page_start": candidate.get("start_index"),
                    "page_end": candidate.get("end_index"),
                    "_node": candidate.get("node"),
                    "_storage_path": manual["storage_path"],
                }
                for index, candidate in enumerate(candidates, start=1)
            ]

        per_manual_candidates = await asyncio.gather(*(retrieve_manual_candidates(manual) for manual in loaded_manuals))
        candidate_sections = [candidate for candidates in per_manual_candidates for candidate in candidates]
        documents_with_hits = sum(1 for candidates in per_manual_candidates if candidates)
        await _record_chat_step_completed(
            run,
            "retrieve_candidates",
            {
                "candidate_count": len(candidate_sections),
                "documents_considered": len(loaded_manuals),
                "documents_with_hits": documents_with_hits,
            },
        )

        rerank_config = resolve_rerank_config(provider_config=provider_config, rerank_mode=rerank_mode)
        rerank_diagnostics: dict[str, object] = {}
        reranked_candidates = candidate_sections[:top_k]
        rerank_meta = {
            "applied": False,
            "mode": "disabled",
            "candidate_count": len(candidate_sections),
            "selected_count": len(reranked_candidates),
        }
        rerank_warning = None
        await _record_chat_step_started(
            run,
            "rerank",
            {
                "requested_mode": rerank_mode,
                "resolved_mode": rerank_config.get("resolved_mode"),
                "enabled": rerank_config.get("enabled"),
                "candidate_count": len(candidate_sections),
            },
        )
        if candidate_sections and rerank_config.get("enabled"):
            async def rerank_operation():
                return await rerank_candidates_async(
                    run.question,
                    candidate_sections,
                    rerank_config.get("model"),
                    request_options={
                        "api_base": rerank_config.get("base_url"),
                        "api_key": rerank_config.get("api_key"),
                        "provider_type": rerank_config.get("provider_type"),
                    },
                    trace_hook=run_trace_hook,
                    stats_hook=stats_hook,
                    top_k=top_k,
                    diagnostics=rerank_diagnostics,
                )

            try:
                reranked_candidates, rerank_meta = await _retry_async(
                    "rerank",
                    rerank_operation,
                    retries=settings.run_step_max_retries,
                    base_delay_ms=settings.run_step_retry_base_ms,
                    run=run,
                )
            except Exception as exc:
                reranked_candidates = candidate_sections[:top_k]
                rerank_meta = {
                    "applied": False,
                    "mode": "fallback_original_order_after_error",
                    "candidate_count": len(candidate_sections),
                    "selected_count": len(reranked_candidates),
                }
                rerank_warning = f"Rerank failed and fell back to original retrieval order: {exc}"
                retrieval_warnings.append(rerank_warning)
        elif len(candidate_sections) > top_k:
            reranked_candidates = candidate_sections[:top_k]
            rerank_meta = {
                "applied": False,
                "mode": "original_order_truncate",
                "candidate_count": len(candidate_sections),
                "selected_count": len(reranked_candidates),
            }
        citations_with_internal = [
            _citation_from_candidate(candidate, knowledge_base_id=knowledge_base_id, index=index)
            for index, candidate in enumerate(reranked_candidates, start=1)
        ]
        await _record_chat_step_completed(
            run,
            "rerank",
            {
                "requested_mode": rerank_mode,
                "resolved_mode": rerank_config.get("resolved_mode"),
                "selected_count": len(citations_with_internal),
                "candidate_count": len(candidate_sections),
                "rerank_applied": rerank_meta.get("applied"),
                "rerank_model": rerank_config.get("model"),
                "rerank_provider_source": rerank_config.get("provider_source"),
                "rerank_warning": rerank_warning,
            },
        )

        await _record_chat_step_started(run, "build_context", {"citation_count": len(citations_with_internal)})
        context_blocks = await build_context_from_citations_async(
            citations_with_internal,
            model=resolved_model,
            max_context_pages=int(max_context_pages) if max_context_pages is not None else None,
            max_context_tokens=int(max_context_tokens) if max_context_tokens is not None else None,
        )
        context = "\n\n".join(context_blocks)
        await _record_chat_step_completed(
            run,
            "build_context",
            {"context_block_count": len(context_blocks), "context_chars": len(context)},
        )

        retrieve_ms = int((time.perf_counter() - retrieve_started) * 1000)
        _log_chat_run_stage(
            run,
            "retrieval_completed",
            retrieve_ms=retrieve_ms,
            retrieval_query=retrieval_query,
            rewrite_applied=rewrite_applied,
            rewrite_strategy=rewrite_strategy,
            outline_selection_strategy=outline_diagnostics.get("outline_selection_strategy"),
            selected_section_count=len(citations_with_internal),
            context_chars=len(context),
            warnings=retrieval_warnings,
        )
        retrieval_info = {
            "query": retrieval_query,
            "rewritten_query": rewritten_query,
            "rewrite_applied": rewrite_applied,
            "top_k": top_k,
            "candidate_top_k": candidate_top_k,
            "selection_mode": selection_mode,
            "query_rewrite_strategy": rewrite_strategy,
            "outline_selection_strategy": outline_diagnostics.get("outline_selection_strategy"),
            "max_context_pages": int(max_context_pages) if max_context_pages is not None else None,
            "max_context_tokens": int(max_context_tokens) if max_context_tokens is not None else None,
            "warnings": retrieval_warnings,
            "documents_considered": len(loaded_manuals),
            "documents_with_hits": documents_with_hits,
            "rerank_mode": rerank_mode,
            "rerank_resolved_mode": rerank_config.get("resolved_mode"),
            "rerank_applied": rerank_meta.get("applied"),
            "rerank_model": rerank_config.get("model"),
            "rerank_provider_source": rerank_config.get("provider_source"),
            "rerank_warning": rerank_warning,
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
        execution_context["target"] = {
            "requested_mode": "knowledge_base" if knowledge_base_id else "single_document",
            "resolved_mode": "multi_manual_federated" if len(loaded_manuals) > 1 else "single_manual",
            "knowledge_base_id": knowledge_base_id,
        }
        execution_context["resolved_manuals"] = [
            {
                "document_id": manual["document_id"],
                "version_id": manual["version_id"],
                "label": manual["document_label"],
                "version_label": manual["version_label"],
            }
            for manual in loaded_manuals
        ]
        execution_context["merge"] = {
            "strategy": "rerank_merge" if rerank_meta.get("applied") else "sequential_kb_merge",
            "candidate_count": len(candidate_sections),
            "selected_citation_count": len(citations_with_internal),
        }
        run.execution_context_json = json.dumps(execution_context, ensure_ascii=False)
        run.status = "answering"
        run.heartbeat_at = datetime.utcnow()
        db.commit()
        db.refresh(run)
        run = _raise_if_cancel_requested(db, run)
        await _publish_chat_event(run.id, "context", {"execution_context": execution_context})
        await _publish_chat_event(run.id, "status", {"status": "answering"})
        await _record_chat_observation(run, event_type="run_status", status_value=run.status, payload={"execution_context": execution_context})

        answer_prompt = build_generation_prompt(
            run.question,
            [citation["_node"] for citation in citations_with_internal if citation.get("_node")],
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
        await _record_chat_step_started(run, "final_answer", {"model": completion_kwargs["model"]})
        answer_attempt = 0
        answer_parts: list[str] = []
        seq = 0
        finish_reason = None
        streamed_usage = None
        answer_started = time.perf_counter()
        while True:
            answer_attempt += 1
            answer_request_event = {
                "type": "llm_completion",
                "label": "final_answer_stream",
                "attempt": answer_attempt,
                "phase": "request",
                "request": {
                    "model": completion_kwargs["model"],
                    "messages": completion_kwargs["messages"],
                    "temperature": completion_kwargs.get("temperature"),
                    "stream": True,
                },
            }
            _log_chat_run_llm_event(run, answer_request_event)
            try:
                response = litellm.completion(**completion_kwargs)
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
                    await _record_chat_observation(
                        run,
                        event_type="answer_delta",
                        step="final_answer",
                        status_value=run.status,
                        payload={"seq": seq, "delta": delta},
                    )
                break
            except Exception as exc:
                answer_error_event = {
                    "type": "llm_completion",
                    "label": "final_answer_stream",
                    "attempt": answer_attempt,
                    "phase": "error",
                    "ok": False,
                    "duration_ms": int((time.perf_counter() - answer_started) * 1000),
                    "request": answer_request_event["request"],
                    "error": str(exc),
                }
                if trace_recorder:
                    trace_recorder.append_llm_call(answer_error_event)
                _log_chat_run_llm_event(run, answer_error_event)
                if answer_parts or answer_attempt >= 2:
                    raise
                await _record_chat_observation(
                    run,
                    event_type="step_failed",
                    step="final_answer",
                    status_value=run.status,
                    payload={"attempt": answer_attempt, "retrying": True, "error": str(exc)},
                )
                await asyncio.sleep(settings.run_step_retry_base_ms / 1000)

        answer_text = "".join(answer_parts).strip()
        answer_ms = int((time.perf_counter() - answer_started) * 1000)
        citations = [
            {key: value for key, value in citation.items() if not key.startswith("_")}
            for citation in citations_with_internal
        ]
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
            "queue_ms": queue_ms,
            "retrieve_ms": retrieve_ms,
            "answer_ms": answer_ms,
            "total_ms": retrieve_ms + answer_ms,
            "wall_clock_ms": queue_ms + retrieve_ms + answer_ms,
            "input_tokens": usage_totals["input_tokens"],
            "output_tokens": usage_totals["output_tokens"],
            "total_tokens": usage_totals["total_tokens"],
            "manual_count": len(loaded_manuals),
            "selected_section_count": len(citations),
            "successful_llm_calls": usage_totals["successful_llm_calls"],
            "citations_count": len(citations),
            "stream_usage_source": stream_usage_source,
            "documents_considered": len(loaded_manuals),
            "documents_with_hits": documents_with_hits,
        }
        serialized_sections = citations
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
                    "phase": "response",
                    "ok": True,
                    "request": {
                        "model": completion_kwargs["model"],
                        "messages": completion_kwargs["messages"],
                        "temperature": completion_kwargs.get("temperature"),
                        "stream": True,
                    },
                    "duration_ms": answer_ms,
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
        _log_chat_run_stage(run, "completed", metrics=metrics)
        await _record_chat_step_completed(run, "final_answer", {"answer_ms": answer_ms, "answer_chars": len(answer_text)})
        await _record_chat_step_started(run, "persist_result")
        await _record_chat_step_completed(run, "persist_result", {"citations_count": len(citations)})
        await _finalize_run(db, run=run, status_value="completed")
    except ChatRunCancelled as exc:
        run = db.get(ChatRun, run_id)
        if run is not None:
            _log_chat_run_stage(run, "cancelled", reason=exc.reason, terminal_status=exc.terminal_status)
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
            localized_error = _humanize_run_error(str(exc))
            _log_chat_run_stage(run, "failed", error=localized_error)
            if trace_recorder:
                trace_recorder.finalize(
                    status="failed",
                    error=localized_error,
                    execution_context=_json_loads(run.execution_context_json, {}),
                )
            await _finalize_run(db, run=run, status_value="failed", last_error=localized_error)
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
    document: Document | None,
    version: DocumentVersion | None,
    question: str,
    model: str | None,
    request_config: dict,
    conversation_config: dict | None,
    retrieval_config: dict | None,
    generation_config: dict | None,
    document_id: str | None = None,
    provider_id: str | None = None,
    session_id: str | None = None,
    disconnect_check: Callable[[], Awaitable[bool]] | None = None,
):
    request_config = dict(request_config or {})
    if "_run_target" not in request_config:
        if document is not None and version is not None:
            manual = {
                "document": document,
                "version": version,
                "document_label": getattr(document, "display_name", getattr(document, "source_filename", document.id)),
                "version_label": f"v{getattr(version, 'version_no', '?')}",
            }
            request_config["_run_target"] = _skill_manual_snapshot(skill, [manual])
        else:
            resolved_document, resolved_version, run_target = resolve_skill_run_targets(
                db,
                principal=principal,
                skill=skill,
                document_id=document_id,
            )
            request_config["_run_target"] = run_target
            document = resolved_document
            version = resolved_version
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
    await _record_chat_observation(
        run,
        event_type="run_status",
        status_value="accepted",
        payload={"created_at": run.created_at.isoformat() if run.created_at else None},
    )

    subscription = await open_chat_event_subscription(run.id)
    try:
        _mark_run_queued(db, run.id)
        yield {"event": "status", "data": {"status": "queued"}}
        await _record_chat_observation(run, event_type="run_status", status_value="queued", payload=None)
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
                        exposed_error = _humanize_run_error(current.last_error or "run failed")
                        yield {"event": "status", "data": {"status": "failed"}}
                        yield {
                            "event": "error",
                            "data": {
                                "code": "skill_stream_failed",
                                "message": exposed_error,
                                "detail": exposed_error,
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
                    exposed_error = _humanize_run_error(current.last_error or "run failed")
                    yield {"event": "status", "data": {"status": "failed"}}
                    yield {
                        "event": "error",
                        "data": {
                            "code": "skill_stream_failed",
                            "message": exposed_error,
                            "detail": exposed_error,
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
