import json

from fastapi import APIRouter, Depends, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_principal
from app.core.db import get_db
from app.core.principal import Principal
from app.schemas.chat import (
    AskRequest,
    ChatMessageOut,
    ChatRunOut,
    ChatSessionCreateRequest,
    ChatSessionOut,
    SkillRunRequest,
)
from app.services.chat_service import (
    create_chat_run,
    get_run_or_404,
    list_runs_for_principal,
    request_run_cancel,
    resolve_document_version,
    serialize_run,
)
from app.services.chat_service import stream_skill_run_events
from app.services.document_service import get_document_or_404
from app.services.session_service import create_session, get_session_or_404, get_skill_session_or_404, list_session_messages, list_sessions
from app.services.skill_service import get_skill_or_404
from app.services.storage_service import artifact_exists, get_trace_uri_for_run, read_json_artifact


router = APIRouter(prefix="/api/v1", tags=["chat"])


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(jsonable_encoder(data), ensure_ascii=False)}\n\n"


@router.post("/chat/ask", response_model=ChatRunOut)
async def ask_question(payload: AskRequest, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    document, version = resolve_document_version(db, principal, payload.document_id, payload.version_id)
    run = await create_chat_run(
        db,
        principal=principal,
        user=principal.user,
        document=document,
        version=version,
        question=payload.question,
        model=payload.model,
        request_config=payload.request_config,
        retrieval_config=payload.retrieval_config,
        generation_config=payload.generation_config,
        provider_id=payload.provider_id,
        session_id=payload.session_id,
    )
    return serialize_run(run)


@router.post("/chat/skills/{skill_id}/run", response_model=ChatRunOut)
async def run_skill(
    skill_id: str,
    payload: SkillRunRequest,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    skill = get_skill_or_404(db, principal, skill_id)
    request_config = json.loads(skill.request_config_json or "{}")
    conversation_config = json.loads(skill.conversation_config_json or "{}")
    retrieval_config = json.loads(skill.retrieval_config_json or "{}")
    generation_config = json.loads(skill.generation_config_json or "{}")
    document_ids = [link.document_id for link in skill.documents]
    if payload.document_id:
        document_id = payload.document_id
    elif document_ids:
        document_id = document_ids[0]
    else:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Skill has no target document")
    document, version = resolve_document_version(db, principal, document_id, None)
    session_id = payload.session_id
    if not session_id and payload.auto_create_session:
        session = create_session(
            db,
            principal,
            payload.session_title or skill.name,
            skill_id=skill.id,
        )
        session_id = session.id
    if payload.stream:
        async def event_stream():
            async for event in stream_skill_run_events(
                db,
                principal=principal,
                user=principal.user,
                skill=skill,
                document=document,
                version=version,
                question=payload.question,
                request_config=request_config,
                conversation_config={**conversation_config, **payload.conversation_config},
                retrieval_config={**retrieval_config, **payload.retrieval_config},
                generation_config={**generation_config, **payload.generation_config},
                provider_id=payload.provider_id,
                session_id=session_id,
                disconnect_check=request.is_disconnected,
            ):
                yield _sse(event["event"], event["data"])

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    run = await create_chat_run(
        db,
        principal=principal,
        user=principal.user,
        document=document,
        version=version,
        question=payload.question,
        model=skill.model,
        request_config=request_config,
        conversation_config={**conversation_config, **payload.conversation_config},
        retrieval_config={**retrieval_config, **payload.retrieval_config},
        generation_config={**generation_config, **payload.generation_config},
        skill=skill,
        provider_id=payload.provider_id,
        session_id=session_id,
    )
    return serialize_run(run)


@router.post("/chat/skills/{skill_id}/run/stream")
async def run_skill_stream(
    skill_id: str,
    payload: SkillRunRequest,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    skill = get_skill_or_404(db, principal, skill_id)
    request_config = json.loads(skill.request_config_json or "{}")
    conversation_config = json.loads(skill.conversation_config_json or "{}")
    retrieval_config = json.loads(skill.retrieval_config_json or "{}")
    generation_config = json.loads(skill.generation_config_json or "{}")
    document_ids = [link.document_id for link in skill.documents]
    if payload.document_id:
        document_id = payload.document_id
    elif document_ids:
        document_id = document_ids[0]
    else:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Skill has no target document")
    document, version = resolve_document_version(db, principal, document_id, None)
    session_id = payload.session_id
    if not session_id and payload.auto_create_session:
        session = create_session(
            db,
            principal,
            payload.session_title or skill.name,
            skill_id=skill.id,
        )
        session_id = session.id
    payload.stream = True

    async def event_stream():
        async for event in stream_skill_run_events(
            db,
            principal=principal,
            user=principal.user,
            skill=skill,
            document=document,
            version=version,
            question=payload.question,
            request_config=request_config,
            conversation_config={**conversation_config, **payload.conversation_config},
            retrieval_config={**retrieval_config, **payload.retrieval_config},
            generation_config={**generation_config, **payload.generation_config},
            provider_id=payload.provider_id,
            session_id=session_id,
            disconnect_check=request.is_disconnected,
        ):
            yield _sse(event["event"], event["data"])

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/runs", response_model=list[ChatRunOut])
def list_runs(
    skill_id: str | None = None,
    document_id: str | None = None,
    session_id: str | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    if skill_id:
        get_skill_or_404(db, principal, skill_id)
    if document_id:
        get_document_or_404(db, principal, document_id)
    if session_id:
        get_session_or_404(db, principal, session_id)
    runs = list_runs_for_principal(
        db,
        principal,
        skill_id=skill_id,
        document_id=document_id,
        session_id=session_id,
    )
    return [serialize_run(run) for run in runs]


@router.get("/runs/{run_id}", response_model=ChatRunOut)
def get_run(run_id: str, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    return serialize_run(get_run_or_404(db, principal, run_id))


@router.post("/runs/{run_id}/cancel", response_model=ChatRunOut)
async def cancel_run(run_id: str, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    run = await request_run_cancel(
        db,
        principal=principal,
        run_id=run_id,
        reason="cancelled by user",
    )
    return serialize_run(run)


@router.get("/runs/{run_id}/trace")
def get_run_trace(run_id: str, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    run = get_run_or_404(db, principal, run_id)
    if not run.skill_id:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Run is not a skill execution")
    trace_path = get_trace_uri_for_run(principal.tenant_id, run.skill_id, run.id)
    if not artifact_exists(trace_path):
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trace not found")
    return read_json_artifact(trace_path)


@router.post("/chat/sessions", response_model=ChatSessionOut)
def create_chat_session(
    payload: ChatSessionCreateRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    return create_session(db, principal, payload.title, skill_id=payload.skill_id)


@router.get("/chat/sessions", response_model=list[ChatSessionOut])
def list_chat_sessions(
    skill_id: str | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    return list_sessions(db, principal, skill_id=skill_id)


@router.get("/chat/sessions/{session_id}", response_model=ChatSessionOut)
def get_chat_session(
    session_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    return get_session_or_404(db, principal, session_id)


@router.get("/chat/sessions/{session_id}/messages", response_model=list[ChatMessageOut])
def get_session_messages(
    session_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    _ = get_session_or_404(db, principal, session_id)
    return list_session_messages(db, principal=principal, session_id=session_id)


@router.post("/chat/skills/{skill_id}/sessions", response_model=ChatSessionOut)
def create_skill_chat_session(
    skill_id: str,
    payload: ChatSessionCreateRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    return create_session(db, principal, payload.title, skill_id=skill_id)


@router.get("/chat/skills/{skill_id}/sessions", response_model=list[ChatSessionOut])
def list_skill_chat_sessions(
    skill_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    return list_sessions(db, principal, skill_id=skill_id)


@router.get("/chat/skills/{skill_id}/sessions/{session_id}", response_model=ChatSessionOut)
def get_skill_chat_session(
    skill_id: str,
    session_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    return get_skill_session_or_404(db, principal, skill_id, session_id)


@router.get("/chat/skills/{skill_id}/sessions/{session_id}/messages", response_model=list[ChatMessageOut])
def get_skill_session_messages(
    skill_id: str,
    session_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    _ = get_skill_session_or_404(db, principal, skill_id, session_id)
    return list_session_messages(db, principal=principal, session_id=session_id)
