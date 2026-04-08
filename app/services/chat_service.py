import asyncio
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime

import litellm
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ChatRun, ChatSession, Document, DocumentVersion, User
from app.services.pageindex_service import (
    build_answer_context,
    answer_question_against_structure_async,
    build_answer_with_marker,
    build_citations,
    build_generation_prompt,
    build_query_rewrite_prompt,
    choose_relevant_nodes,
    estimate_history_tokens,
    format_history_context,
    load_structure_file,
)
from app.services.provider_service import resolve_provider_config
from app.services.session_service import append_message, get_session_or_404, list_session_messages
from app.services.skill_trace_service import SkillTraceRecorder
from app.services.storage_service import local_artifact_path
from pageindex.utils import count_tokens, extract_json, llm_completion


DEFAULT_CONVERSATION_CONFIG = {
    "query_rewrite_with_history": True,
    "include_history": True,
    "include_assistant_messages": True,
    "history_turn_limit": 4,
    "history_token_budget": 1800,
}


def _coerce_positive_int(name: str, value) -> int:
    try:
        coerced = int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{name} must be an integer",
        ) from exc
    if coerced <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{name} must be greater than 0",
        )
    return coerced


def _coerce_float(name: str, value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{name} must be a number",
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
        conversation["history_token_budget"] = _coerce_positive_int(
            "history_token_budget",
            conversation["history_token_budget"],
        )

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
                detail="selection_mode must be one of: outline_llm, lexical_fallback",
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

    all_messages = list_session_messages(db, tenant_id=tenant_id, session_id=session_id)
    include_assistant = bool(conversation_config.get("include_assistant_messages", True))
    if not include_assistant:
        all_messages = [message for message in all_messages if message.role != "assistant"]

    # Drop the current user message if it has already been appended in a retry path.
    if all_messages and all_messages[-1].role == "user" and all_messages[-1].content.strip() == current_question.strip():
        all_messages = all_messages[:-1]

    max_turns = int(conversation_config.get("history_turn_limit", DEFAULT_CONVERSATION_CONFIG["history_turn_limit"]))
    history_budget = int(
        conversation_config.get("history_token_budget", DEFAULT_CONVERSATION_CONFIG["history_token_budget"])
    )

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


async def create_chat_run(
    db: Session,
    *,
    user: User,
    document: Document,
    version: DocumentVersion,
    question: str,
    model: str | None,
    request_config: dict,
    conversation_config: dict | None = None,
    retrieval_config: dict | None = None,
    generation_config: dict | None = None,
    skill=None,
    provider_id: str | None = None,
    session_id: str | None = None,
) -> ChatRun:
    if not version.parsed_structure_path or version.parse_status != "index_ready":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document is not ready for querying yet",
        )

    session: ChatSession | None = None
    if session_id:
        session = get_session_or_404(db, user.tenant_id, session_id)
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

    provider_config = resolve_provider_config(
        db,
        user.tenant_id,
        skill=skill,
        explicit_provider_id=provider_id,
    )
    resolved_model = model or (skill.model if skill else None) or provider_config.get("default_model")
    if not resolved_model:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No model resolved for this request")

    conversation_config, retrieval_config, generation_config = _validate_execution_options(
        conversation_config,
        retrieval_config,
        generation_config,
    )

    history_messages: list[dict] = []
    history_metadata = {
        "used": False,
        "history_messages_used": 0,
        "history_turns_used": 0,
        "history_token_estimate": 0,
    }
    if session and skill:
        history_messages, history_metadata = _load_session_history(
            db,
            tenant_id=user.tenant_id,
            session_id=session.id,
            model=resolved_model,
            conversation_config=conversation_config,
            current_question=question,
        )

    run = ChatRun(
        id=str(uuid.uuid4()),
        tenant_id=user.tenant_id,
        user_id=user.id,
        session_id=session.id if session else None,
        document_id=document.id,
        skill_id=skill.id if skill else None,
        provider_id=provider_config.get("provider_id"),
        model=resolved_model,
        question=question,
        status="accepted",
        selected_sections_json="[]",
        citations_json="[]",
        execution_context_json="{}",
        metrics_json="{}",
        started_at=datetime.utcnow(),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    structure = load_structure_file(version.parsed_structure_path)
    run.status = "retrieving"
    db.commit()

    trace_recorder = (
        SkillTraceRecorder(
            tenant_id=user.tenant_id,
            run_id=run.id,
            user=user,
            skill=skill,
            document=document,
            version=version,
            question=question,
            model=resolved_model,
            request_config=request_config,
        )
        if skill
        else None
    )

    if session:
        append_message(
            db,
            session_id=session.id,
            tenant_id=user.tenant_id,
            user_id=user.id,
            role="user",
            content=question,
            run_id=run.id,
        )

    try:
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

        request_options = {
            key: value
            for key, value in (request_config or {}).items()
            if key not in {"system_prompt"}
        }
        retrieval_options = dict(retrieval_config or {})
        generation_options = dict(generation_config or {})
        request_options.update(
            {
            "api_base": provider_config["base_url"],
            "api_key": provider_config["api_key"],
            "extra_headers": provider_config.get("extra_headers") or {},
            }
        )
        retrieval_options.update(
            {
                "api_base": provider_config["base_url"],
                "api_key": provider_config["api_key"],
                "extra_headers": provider_config.get("extra_headers") or {},
            }
        )
        generation_options.update(
            {
                "api_base": provider_config["base_url"],
                "api_key": provider_config["api_key"],
                "extra_headers": provider_config.get("extra_headers") or {},
            }
        )
        conversation_options = dict(conversation_config or {})
        conversation_options.update(history_metadata)
        with local_artifact_path(version.storage_path) as pdf_path:
            run.status = "answering"
            db.commit()
            answer, selected_nodes, metrics, execution_context = await answer_question_against_structure_async(
                pdf_path=str(pdf_path),
                structure=structure,
                question=question,
                model=resolved_model,
                system_prompt=skill.system_prompt if skill else request_config.get("system_prompt"),
                request_options=request_options,
                retrieval_options=retrieval_options,
                generation_options=generation_options,
                conversation_options=conversation_options,
                history_messages=history_messages if skill else None,
                trace_hook=trace_recorder.append_llm_call if trace_recorder else None,
            )

        serialized_sections = [
            {
                "node_id": node.get("node_id"),
                "title": node.get("title"),
                "start_index": node.get("start_index"),
                "end_index": node.get("end_index"),
            }
            for node in selected_nodes
        ]
        citations = build_citations(selected_nodes)
        answer_text = answer
        answer_with_marker = build_answer_with_marker(answer_text, citations)
        run.status = "completed"
        run.answer = answer_text
        run.answer_text = answer_text
        run.answer_with_marker = answer_with_marker
        run.selected_sections_json = json.dumps(serialized_sections, ensure_ascii=False)
        run.citations_json = json.dumps(citations, ensure_ascii=False)
        run.execution_context_json = json.dumps(
            {
                "provider": {
                    "id": provider_config.get("provider_id"),
                    "name": provider_config.get("name"),
                    "type": provider_config.get("provider_type"),
                },
                "model": {
                    "resolved_model": resolved_model,
                },
                "conversation": {
                    **conversation_config,
                    "history_used": execution_context["history"]["used"],
                    "history_messages_used": execution_context["history"]["messages_used"],
                    "history_turns_used": execution_context["history"]["history_turns_used"],
                    "history_token_estimate": execution_context["history"]["history_token_estimate"],
                },
                "retrieval": execution_context["retrieval"],
                "generation": execution_context["generation"],
            },
            ensure_ascii=False,
        )
        run.metrics_json = json.dumps(metrics, ensure_ascii=False)
        run.finished_at = datetime.utcnow()
        db.commit()
        db.refresh(run)
        if session:
            append_message(
                db,
                session_id=session.id,
                tenant_id=user.tenant_id,
                user_id=user.id,
                role="assistant",
                content=answer_text,
                run_id=run.id,
            )
        if trace_recorder:
            trace_recorder.finalize(
                status="completed",
                answer=answer_text,
                metrics=metrics,
                selected_sections=serialized_sections,
                execution_context=json.loads(run.execution_context_json or "{}"),
            )
        return run
    except Exception as exc:
        run.status = "failed"
        run.finished_at = datetime.utcnow()
        run.metrics_json = json.dumps({"error": str(exc)}, ensure_ascii=False)
        db.commit()
        db.refresh(run)
        if trace_recorder:
            trace_recorder.finalize(
                status="failed",
                error=str(exc),
                execution_context=json.loads(run.execution_context_json or "{}"),
            )
        raise


def serialize_run(run: ChatRun) -> dict:
    return {
        "id": run.id,
        "tenant_id": run.tenant_id,
        "user_id": run.user_id,
        "session_id": run.session_id,
        "document_id": run.document_id,
        "skill_id": run.skill_id,
        "provider_id": run.provider_id,
        "model": run.model,
        "question": run.question,
        "answer": run.answer,
        "answer_text": run.answer_text or run.answer,
        "answer_with_marker": run.answer_with_marker or run.answer,
        "status": run.status,
        "execution_context": json.loads(run.execution_context_json or "{}"),
        "selected_sections": json.loads(run.selected_sections_json or "[]"),
        "citations": json.loads(run.citations_json or "[]"),
        "metrics": json.loads(run.metrics_json or "{}"),
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "created_at": run.created_at,
    }


async def stream_skill_run_events(
    db: Session,
    *,
    user: User,
    skill,
    document: Document,
    version: DocumentVersion,
    question: str,
    request_config: dict,
    conversation_config: dict | None,
    retrieval_config: dict | None,
    generation_config: dict | None,
    session_id: str | None = None,
    disconnect_check: Callable[[], Awaitable[bool]] | None = None,
):
    if not version.parsed_structure_path or version.parse_status != "index_ready":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document is not ready for querying yet",
        )

    session: ChatSession | None = None
    if session_id:
        session = get_session_or_404(db, user.tenant_id, session_id)
        if session.skill_id and session.skill_id != skill.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Session is bound to a different skill",
            )

    provider_config = resolve_provider_config(
        db,
        user.tenant_id,
        skill=skill,
        explicit_provider_id=None,
    )
    resolved_model = skill.model or provider_config.get("default_model")
    if not resolved_model:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No model resolved for this request")

    conversation_config, retrieval_config, generation_config = _validate_execution_options(
        conversation_config,
        retrieval_config,
        generation_config,
    )

    history_messages: list[dict] = []
    history_info = {
        "used": False,
        "history_messages_used": 0,
        "history_turns_used": 0,
        "history_token_estimate": 0,
    }
    if session:
        history_messages, history_info = _load_session_history(
            db,
            tenant_id=user.tenant_id,
            session_id=session.id,
            model=resolved_model,
            conversation_config=conversation_config,
            current_question=question,
        )

    run = ChatRun(
        id=str(uuid.uuid4()),
        tenant_id=user.tenant_id,
        user_id=user.id,
        session_id=session.id if session else None,
        document_id=document.id,
        skill_id=skill.id,
        provider_id=provider_config.get("provider_id"),
        model=resolved_model,
        question=question,
        status="accepted",
        selected_sections_json="[]",
        citations_json="[]",
        execution_context_json="{}",
        metrics_json="{}",
        started_at=datetime.utcnow(),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    trace_recorder = SkillTraceRecorder(
        tenant_id=user.tenant_id,
        run_id=run.id,
        user=user,
        skill=skill,
        document=document,
        version=version,
        question=question,
        model=resolved_model,
        request_config=request_config,
    )

    if session:
        append_message(
            db,
            session_id=session.id,
            tenant_id=user.tenant_id,
            user_id=user.id,
            role="user",
            content=question,
            run_id=run.id,
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

    try:
        async def ensure_client_connected() -> None:
            if disconnect_check and await disconnect_check():
                raise asyncio.CancelledError

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

        request_options = {
            key: value
            for key, value in (request_config or {}).items()
            if key not in {"system_prompt"}
        }
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

        run.status = "retrieving"
        db.commit()
        await ensure_client_connected()
        yield {"event": "status", "data": {"status": "retrieving"}}

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
        retrieval_query = question
        rewritten_query = None
        rewrite_applied = False
        if conversation_config.get("query_rewrite_with_history", True) and history_context:
            try:
                rewrite_response = llm_completion(
                    model=resolved_model,
                    prompt=build_query_rewrite_prompt(question, history_context),
                    request_options=retrieval_options,
                    trace_hook=trace_recorder.append_llm_call,
                    trace_label="query_rewrite",
                    stats_hook=stats_hook,
                )
                rewrite_payload = extract_json(rewrite_response)
                candidate = rewrite_payload.get("rewritten_query") if isinstance(rewrite_payload, dict) else None
                if isinstance(candidate, str) and candidate.strip():
                    rewritten_query = candidate.strip()
                    retrieval_query = rewritten_query
                    rewrite_applied = retrieval_query != question
            except Exception:
                retrieval_query = question

        selected_nodes = choose_relevant_nodes(
            structure,
            retrieval_query,
            resolved_model,
            request_options=retrieval_options,
            trace_hook=trace_recorder.append_llm_call,
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
        db.commit()
        await ensure_client_connected()
        yield {"event": "context", "data": {"execution_context": execution_context}}

        run.status = "answering"
        db.commit()
        await ensure_client_connected()
        yield {"event": "status", "data": {"status": "answering"}}

        answer_prompt = build_generation_prompt(
            question,
            selected_nodes,
            context,
            system_prompt=skill.system_prompt or request_config.get("system_prompt"),
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
            await ensure_client_connected()
            chunk_usage = _extract_usage_from_stream_chunk(chunk)
            if chunk_usage:
                streamed_usage = chunk_usage
            choices = getattr(chunk, "choices", None)
            if not choices:
                continue
            choice = chunk.choices[0]
            finish_reason = getattr(choice, "finish_reason", None) or finish_reason
            delta = ""
            if getattr(choice, "delta", None) is not None:
                delta = choice.delta.content or ""
            if not delta:
                continue
            answer_parts.append(delta)
            seq += 1
            await ensure_client_connected()
            yield {"event": "answer_delta", "data": {"delta": delta, "seq": seq}}

        await ensure_client_connected()
        answer_text = "".join(answer_parts).strip()
        answer_ms = int((time.perf_counter() - answer_started) * 1000)
        citations = build_citations(selected_nodes)
        answer_with_marker = build_answer_with_marker(answer_text, citations)
        if streamed_usage:
            usage_totals["successful_llm_calls"] += 1
            _accumulate_usage_totals(usage_totals, streamed_usage)
            stream_usage_source = "provider_stream"
        else:
            fallback_usage = {
                "prompt_tokens": count_tokens(answer_prompt, model=resolved_model) + history_info["history_token_estimate"],
                "completion_tokens": count_tokens(answer_text, model=resolved_model),
                "total_tokens": count_tokens(answer_prompt, model=resolved_model)
                + history_info["history_token_estimate"]
                + count_tokens(answer_text, model=resolved_model),
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
        run.status = "completed"
        run.answer = answer_text
        run.answer_text = answer_text
        run.answer_with_marker = answer_with_marker
        run.selected_sections_json = json.dumps(serialized_sections, ensure_ascii=False)
        run.citations_json = json.dumps(citations, ensure_ascii=False)
        run.metrics_json = json.dumps(metrics, ensure_ascii=False)
        run.finished_at = datetime.utcnow()
        db.commit()
        db.refresh(run)

        if session:
            append_message(
                db,
                session_id=session.id,
                tenant_id=user.tenant_id,
                user_id=user.id,
                role="assistant",
                content=answer_text,
                run_id=run.id,
            )
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

        await ensure_client_connected()
        yield {"event": "status", "data": {"status": "completed"}}
        await ensure_client_connected()
        yield {"event": "run_completed", "data": serialize_run(run)}
    except asyncio.CancelledError:
        run.status = "failed"
        run.finished_at = datetime.utcnow()
        run.metrics_json = json.dumps({"error": "client aborted stream"}, ensure_ascii=False)
        db.commit()
        trace_recorder.finalize(status="failed", error="client aborted stream", execution_context=json.loads(run.execution_context_json or "{}"))
        raise
    except Exception as exc:
        run.status = "failed"
        run.finished_at = datetime.utcnow()
        run.metrics_json = json.dumps({"error": str(exc)}, ensure_ascii=False)
        db.commit()
        trace_recorder.finalize(status="failed", error=str(exc), execution_context=json.loads(run.execution_context_json or "{}"))
        yield {"event": "status", "data": {"status": "failed"}}
        yield {
            "event": "error",
            "data": {
                "code": "skill_stream_failed",
                "message": str(exc),
                "detail": str(exc),
            },
        }


def resolve_document_version(
    db: Session,
    user: User,
    document_id: str,
    version_id: str | None = None,
) -> tuple[Document, DocumentVersion]:
    document = db.get(Document, document_id)
    if document is None or document.tenant_id != user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    target_version_id = version_id or document.active_version_id
    if target_version_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Document has no active version")
    version = db.get(DocumentVersion, target_version_id)
    if version is None or version.document_id != document.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document version not found")
    return document, version
