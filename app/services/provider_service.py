import json
import logging
import uuid
from datetime import datetime
from urllib import error, request

from cryptography.fernet import InvalidToken
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import decrypt_text, encrypt_text
from app.core.errors import AppError, ErrorCode
from app.core.url_validator import validate_provider_url
from app.models import ChatRun, ChatSkill, ModelProvider, ProviderWorkspaceShare, Workspace
from app.services.audit_service import emit_audit_event


logger = logging.getLogger(__name__)
settings = get_settings()

PROVIDER_SCOPE_TENANT = "tenant"
PROVIDER_SCOPE_WORKSPACE = "workspace"
PROVIDER_SCOPE_SYSTEM = "system"
PROVIDER_SHARE_NONE = "none"
PROVIDER_SHARE_ALL = "all"
PROVIDER_SHARE_SELECTED = "selected"
RERANK_MODEL_KEYWORDS = (
    "rerank",
    "re-rank",
    "bge-reranker",
    "jina-reranker",
    "cohere-rerank",
)


def normalize_rerank_provider_type(provider_type: str | None, base_url: str | None) -> str | None:
    normalized_base = str(base_url or "").strip().lower()
    if "/services/rerank/" in normalized_base:
        return "dashscope_rerank"
    return provider_type


def normalize_execution_model(provider_type: str | None, model: str | None) -> str | None:
    if model is None:
        return None
    normalized = model.strip()
    if not normalized:
        return normalized
    normalized = normalized.removeprefix("litellm/")
    if provider_type == "openai_compatible" and not normalized.startswith("openai/"):
        return f"openai/{normalized}"
    return normalized


def _normalize_model_candidates(default_model: str | None, supported_models: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for model in [default_model, *(supported_models or [])]:
        if not isinstance(model, str):
            continue
        candidate = model.strip()
        if not candidate or candidate in normalized:
            continue
        normalized.append(candidate)
    return normalized


def normalized_supported_execution_models(
    provider_type: str | None,
    default_model: str | None,
    supported_models: list[str] | None,
) -> list[str]:
    normalized: list[str] = []
    for candidate in _normalize_model_candidates(default_model, supported_models):
        resolved = normalize_execution_model(provider_type, candidate)
        if resolved and resolved not in normalized:
            normalized.append(resolved)
    return normalized


def validate_provider_model_selection(
    *,
    provider_id: str | None,
    provider_type: str | None,
    provider_name: str | None,
    default_model: str | None,
    supported_models: list[str] | None,
    model: str | None,
    subject: str = "Model",
) -> str:
    resolved_model = normalize_execution_model(provider_type, model or default_model)
    if not resolved_model:
        raise AppError(
            code=ErrorCode.VALIDATION_ERROR,
            message=f"{subject} could not be resolved because no model is configured",
            status_code=400,
        )

    if not provider_id:
        return resolved_model

    raw_supported_models = _normalize_model_candidates(default_model, supported_models)
    supported_execution_models = normalized_supported_execution_models(
        provider_type,
        default_model,
        raw_supported_models,
    )
    if not supported_execution_models or resolved_model in supported_execution_models:
        return resolved_model

    requested_model = (model or default_model or "").strip() or resolved_model
    resolved_suffix = f' (resolved as "{resolved_model}")' if requested_model != resolved_model else ""
    supported_preview = ", ".join(raw_supported_models[:10])
    if len(raw_supported_models) > 10:
        supported_preview = f"{supported_preview}, ..."
    raise AppError(
        code=ErrorCode.PROVIDER_MODEL_UNSUPPORTED,
        message=(
            f'{subject} "{requested_model}"{resolved_suffix} is not supported by provider '
            f'"{provider_name or provider_id}". Supported models: {supported_preview}'
        ),
        status_code=400,
        details={
            "provider_id": provider_id,
            "provider_name": provider_name,
            "provider_type": provider_type,
            "requested_model": requested_model,
            "resolved_model": resolved_model,
            "supported_models": raw_supported_models,
        },
    )


def _normalize_supported_models(default_model: str, supported_models: list[str] | None) -> list[str]:
    normalized = _normalize_model_candidates(default_model, supported_models)
    return normalized or [default_model]


def _is_rerank_model_name(model_name: str | None) -> bool:
    lowered = str(model_name or "").strip().lower()
    if not lowered:
        return False
    return any(keyword in lowered for keyword in RERANK_MODEL_KEYWORDS)


def classify_provider_capabilities(default_model: str | None, supported_models: list[str] | None) -> dict:
    models = _normalize_model_candidates(default_model, supported_models)
    rerank_models = [model for model in models if _is_rerank_model_name(model)]
    chat_models = [model for model in models if model not in rerank_models]
    return {
        "chat_models": chat_models,
        "rerank_models": rerank_models,
        "default_rerank_model": rerank_models[0] if rerank_models else None,
    }


def provider_scope(provider: ModelProvider) -> str:
    if provider.managed_by_system:
        return PROVIDER_SCOPE_SYSTEM
    if provider.workspace_id:
        return PROVIDER_SCOPE_WORKSPACE
    return PROVIDER_SCOPE_TENANT


def _list_workspace_share_rows(db: Session, provider_ids: list[str]) -> dict[str, list[str]]:
    if not provider_ids:
        return {}
    rows = db.scalars(
        select(ProviderWorkspaceShare).where(ProviderWorkspaceShare.provider_id.in_(provider_ids))
    ).all()
    mapping: dict[str, list[str]] = {provider_id: [] for provider_id in provider_ids}
    for row in rows:
        mapping.setdefault(row.provider_id, []).append(row.workspace_id)
    return mapping


def _is_shared_to_workspace(provider: ModelProvider, workspace_id: str | None, shared_workspace_ids: list[str] | None = None) -> bool:
    if workspace_id is None:
        return True
    scope = provider_scope(provider)
    if scope == PROVIDER_SCOPE_SYSTEM:
        return False
    if scope == PROVIDER_SCOPE_WORKSPACE:
        return provider.workspace_id == workspace_id
    if provider.share_mode == PROVIDER_SHARE_ALL:
        return True
    if provider.share_mode == PROVIDER_SHARE_SELECTED:
        return workspace_id in (shared_workspace_ids or [])
    return False


def is_provider_available_to_workspace(
    provider: ModelProvider,
    workspace_id: str | None,
    *,
    shared_workspace_ids: list[str] | None = None,
) -> bool:
    if not provider.enabled:
        return False
    return _is_shared_to_workspace(provider, workspace_id, shared_workspace_ids)


def can_bind_provider_to_workspace(
    provider: ModelProvider,
    workspace_id: str | None,
    *,
    shared_workspace_ids: list[str] | None = None,
) -> bool:
    if provider_scope(provider) == PROVIDER_SCOPE_SYSTEM:
        return False
    return is_provider_available_to_workspace(provider, workspace_id, shared_workspace_ids=shared_workspace_ids)


def can_bind_provider_to_workspace_via_db(
    db: Session,
    provider: ModelProvider,
    workspace_id: str | None,
) -> bool:
    shared_workspace_ids = _list_workspace_share_rows(db, [provider.id]).get(provider.id, [])
    return can_bind_provider_to_workspace(
        provider,
        workspace_id,
        shared_workspace_ids=shared_workspace_ids,
    )


def serialize_provider(
    db: Session,
    provider: ModelProvider,
    *,
    current_workspace_id: str | None = None,
    shared_workspace_ids: list[str] | None = None,
) -> dict:
    supported_models = json.loads(provider.supported_models_json or "[]")
    if not isinstance(supported_models, list):
        supported_models = []
    normalized_supported_models = _normalize_supported_models(provider.default_model, supported_models)
    if shared_workspace_ids is None:
        shared_workspace_ids = _list_workspace_share_rows(db, [provider.id]).get(provider.id, [])
    source_provider = db.get(ModelProvider, provider.source_provider_id) if provider.source_provider_id else None
    return {
        "id": provider.id,
        "tenant_id": provider.tenant_id,
        "workspace_id": provider.workspace_id,
        "provider_type": provider.provider_type,
        "name": provider.name,
        "base_url": provider.base_url,
        "default_model": provider.default_model,
        "supported_models": normalized_supported_models,
        "extra_headers": json.loads(provider.extra_headers_json or "{}"),
        "enabled": provider.enabled,
        "is_default": provider.is_default,
        "managed_by_system": provider.managed_by_system,
        "scope": provider_scope(provider),
        "share_mode": provider.share_mode or PROVIDER_SHARE_NONE,
        "shared_workspace_ids": shared_workspace_ids,
        "available_in_current_workspace": is_provider_available_to_workspace(
            provider,
            current_workspace_id,
            shared_workspace_ids=shared_workspace_ids,
        ),
        "bindable_in_current_workspace": can_bind_provider_to_workspace(
            provider,
            current_workspace_id,
            shared_workspace_ids=shared_workspace_ids,
        ),
        "source_provider_id": provider.source_provider_id,
        "source_provider_name": source_provider.name if source_provider is not None else None,
        "is_workspace_default_candidate": can_bind_provider_to_workspace(
            provider,
            current_workspace_id,
            shared_workspace_ids=shared_workspace_ids,
        ),
        "capabilities": classify_provider_capabilities(provider.default_model, normalized_supported_models),
        "created_at": provider.created_at,
        "updated_at": provider.updated_at,
    }


def list_tenant_providers(
    db: Session,
    tenant_id: str,
    *,
    scope: str = "all",
    workspace_id: str | None = None,
) -> list[ModelProvider]:
    stmt = select(ModelProvider).where(ModelProvider.tenant_id == tenant_id)
    if scope == PROVIDER_SCOPE_TENANT:
        stmt = stmt.where(ModelProvider.workspace_id.is_(None), ModelProvider.managed_by_system.is_(False))
    elif scope == PROVIDER_SCOPE_WORKSPACE:
        stmt = stmt.where(ModelProvider.workspace_id == workspace_id)
    return db.scalars(stmt.order_by(ModelProvider.created_at.desc())).all()


def list_bindable_catalog(db: Session, tenant_id: str, workspace_id: str | None) -> list[ModelProvider]:
    providers = list_tenant_providers(db, tenant_id, scope="all", workspace_id=workspace_id)
    share_map = _list_workspace_share_rows(db, [provider.id for provider in providers])
    return [
        provider
        for provider in providers
        if can_bind_provider_to_workspace(provider, workspace_id, shared_workspace_ids=share_map.get(provider.id, []))
    ]


def get_provider_or_404(db: Session, tenant_id: str, provider_id: str) -> ModelProvider:
    provider = db.get(ModelProvider, provider_id)
    if provider is None or provider.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")
    return provider


def _clear_tenant_default_provider(db: Session, tenant_id: str, keep_provider_id: str | None = None) -> None:
    providers = db.scalars(select(ModelProvider).where(ModelProvider.tenant_id == tenant_id, ModelProvider.is_default.is_(True))).all()
    for provider in providers:
        if keep_provider_id and provider.id == keep_provider_id:
            continue
        provider.is_default = False


def _validate_provider_scope(scope: str) -> None:
    if scope == PROVIDER_SCOPE_SYSTEM:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="System provider scope cannot be created manually")
    if scope not in {PROVIDER_SCOPE_TENANT, PROVIDER_SCOPE_WORKSPACE}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Provider scope is invalid")


def _validate_share_mode(scope: str, share_mode: str) -> None:
    if scope == PROVIDER_SCOPE_WORKSPACE and share_mode not in {PROVIDER_SHARE_NONE, ""}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Workspace provider cannot be shared")
    if share_mode not in {PROVIDER_SHARE_NONE, PROVIDER_SHARE_ALL, PROVIDER_SHARE_SELECTED}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Provider share_mode is invalid")


def _replace_provider_shares(db: Session, provider: ModelProvider, shared_workspace_ids: list[str]) -> None:
    db.query(ProviderWorkspaceShare).filter(ProviderWorkspaceShare.provider_id == provider.id).delete(synchronize_session=False)
    now = datetime.utcnow()
    for workspace_id in dict.fromkeys(workspace_id for workspace_id in shared_workspace_ids if workspace_id):
        db.add(
            ProviderWorkspaceShare(
                id=str(uuid.uuid4()),
                provider_id=provider.id,
                workspace_id=workspace_id,
                created_at=now,
                updated_at=now,
            )
        )


def create_provider(
    db: Session,
    tenant_id: str,
    payload,
    *,
    workspace_id: str | None = None,
    actor_id: str | None = None,
    actor_type: str = "user",
) -> ModelProvider:
    try:
        validated_url = validate_provider_url(
            payload.base_url,
            allow_private=settings.provider_url_allow_private_nets,
        )
    except ValueError as exc:
        raise AppError(
            code=ErrorCode.PROVIDER_URL_INVALID,
            message=str(exc),
            status_code=400,
        ) from exc

    scope = getattr(payload, "scope", PROVIDER_SCOPE_TENANT)
    share_mode = getattr(payload, "share_mode", PROVIDER_SHARE_ALL)
    shared_workspace_ids = list(getattr(payload, "shared_workspace_ids", []) or [])
    _validate_provider_scope(scope)
    _validate_share_mode(scope, share_mode)
    if scope == PROVIDER_SCOPE_WORKSPACE and workspace_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Workspace provider requires a current workspace")
    if scope == PROVIDER_SCOPE_WORKSPACE and getattr(payload, "is_default", False):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Workspace provider cannot be tenant default")
    if scope == PROVIDER_SCOPE_TENANT and share_mode == PROVIDER_SHARE_SELECTED and not shared_workspace_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Selected-share provider requires shared workspaces")

    now = datetime.utcnow()
    supported_models = _normalize_supported_models(payload.default_model, getattr(payload, "supported_models", None))
    provider = ModelProvider(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        workspace_id=workspace_id if scope == PROVIDER_SCOPE_WORKSPACE else None,
        provider_type=payload.provider_type,
        name=payload.name,
        base_url=validated_url,
        api_key_encrypted=encrypt_text(settings.secret_key, payload.api_key),
        default_model=payload.default_model,
        supported_models_json=json.dumps(supported_models, ensure_ascii=False),
        extra_headers_json=json.dumps(payload.extra_headers, ensure_ascii=False),
        enabled=payload.enabled,
        is_default=bool(payload.is_default) if scope == PROVIDER_SCOPE_TENANT else False,
        managed_by_system=False,
        share_mode=PROVIDER_SHARE_NONE if scope == PROVIDER_SCOPE_WORKSPACE else share_mode,
        source_provider_id=None,
        created_at=now,
        updated_at=now,
    )
    if provider.is_default:
        _clear_tenant_default_provider(db, tenant_id)
    db.add(provider)
    db.flush()
    if scope == PROVIDER_SCOPE_TENANT and share_mode == PROVIDER_SHARE_SELECTED:
        _replace_provider_shares(db, provider, shared_workspace_ids)
    emit_audit_event(
        db,
        tenant_id=tenant_id,
        actor_type=actor_type,
        actor_id=actor_id or "unknown",
        action="provider.create",
        target_type="provider",
        target_id=provider.id,
        result="success",
        meta={"scope": scope},
    )
    db.commit()
    db.refresh(provider)
    return provider


def update_provider(
    db: Session,
    tenant_id: str,
    provider_id: str,
    payload,
    *,
    actor_id: str | None = None,
    actor_type: str = "user",
) -> ModelProvider:
    provider = get_provider_or_404(db, tenant_id, provider_id)
    if provider.managed_by_system:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="System-managed provider is synced from environment and cannot be edited",
        )
    update_dict = payload.model_dump(exclude_unset=True)

    if "base_url" in update_dict:
        try:
            update_dict["base_url"] = validate_provider_url(
                update_dict["base_url"],
                allow_private=settings.provider_url_allow_private_nets,
            )
        except ValueError as exc:
            raise AppError(
                code=ErrorCode.PROVIDER_URL_INVALID,
                message=str(exc),
                status_code=400,
            ) from exc

    if provider_scope(provider) == PROVIDER_SCOPE_WORKSPACE and update_dict.get("is_default") is True:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Workspace provider cannot be tenant default")

    current_supported_models = json.loads(provider.supported_models_json or "[]")
    if not isinstance(current_supported_models, list):
        current_supported_models = []
    if "api_key" in update_dict:
        provider.api_key_encrypted = encrypt_text(settings.secret_key, update_dict.pop("api_key"))
    if "extra_headers" in update_dict:
        provider.extra_headers_json = json.dumps(update_dict.pop("extra_headers"), ensure_ascii=False)
    next_default_model = update_dict.get("default_model", provider.default_model)
    if "supported_models" in update_dict:
        provider.supported_models_json = json.dumps(
            _normalize_supported_models(next_default_model, update_dict.pop("supported_models")),
            ensure_ascii=False,
        )
    elif "default_model" in update_dict:
        provider.supported_models_json = json.dumps(
            _normalize_supported_models(next_default_model, current_supported_models),
            ensure_ascii=False,
        )

    if provider_scope(provider) == PROVIDER_SCOPE_WORKSPACE:
        update_dict.pop("share_mode", None)
        update_dict.pop("shared_workspace_ids", None)
        update_dict["is_default"] = False
    else:
        next_share_mode = update_dict.pop("share_mode", provider.share_mode)
        next_shared_workspace_ids = update_dict.pop("shared_workspace_ids", None)
        _validate_share_mode(PROVIDER_SCOPE_TENANT, next_share_mode)
        if next_share_mode == PROVIDER_SHARE_SELECTED:
            shared_workspace_ids = next_shared_workspace_ids if next_shared_workspace_ids is not None else _list_workspace_share_rows(db, [provider.id]).get(provider.id, [])
            if not shared_workspace_ids:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Selected-share provider requires shared workspaces")
            _replace_provider_shares(db, provider, shared_workspace_ids)
        elif next_shared_workspace_ids is not None:
            _replace_provider_shares(db, provider, next_shared_workspace_ids)
        if next_share_mode != PROVIDER_SHARE_SELECTED:
            db.query(ProviderWorkspaceShare).filter(ProviderWorkspaceShare.provider_id == provider.id).delete(synchronize_session=False)
        provider.share_mode = next_share_mode
        if update_dict.get("is_default") is True:
            _clear_tenant_default_provider(db, tenant_id, keep_provider_id=provider.id)

    for field, value in update_dict.items():
        setattr(provider, field, value)
    provider.updated_at = datetime.utcnow()
    emit_audit_event(
        db,
        tenant_id=tenant_id,
        actor_type=actor_type,
        actor_id=actor_id or "unknown",
        action="provider.update",
        target_type="provider",
        target_id=provider.id,
        result="success",
        meta={"scope": provider_scope(provider)},
    )
    db.commit()
    db.refresh(provider)
    return provider


def import_provider_to_workspace(
    db: Session,
    tenant_id: str,
    provider_id: str,
    *,
    workspace_id: str,
    actor_id: str | None = None,
    actor_type: str = "user",
) -> ModelProvider:
    source = get_provider_or_404(db, tenant_id, provider_id)
    if provider_scope(source) != PROVIDER_SCOPE_TENANT:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only tenant providers can be imported into a workspace")
    shared_workspace_ids = _list_workspace_share_rows(db, [source.id]).get(source.id, [])
    if not can_bind_provider_to_workspace(source, workspace_id, shared_workspace_ids=shared_workspace_ids):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Provider is not accessible from this workspace")

    now = datetime.utcnow()
    imported = ModelProvider(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        provider_type=source.provider_type,
        name=f"{source.name} (Workspace)",
        base_url=source.base_url,
        api_key_encrypted=source.api_key_encrypted,
        default_model=source.default_model,
        supported_models_json=source.supported_models_json,
        extra_headers_json=source.extra_headers_json,
        enabled=source.enabled,
        is_default=False,
        managed_by_system=False,
        share_mode=PROVIDER_SHARE_NONE,
        source_provider_id=source.id,
        created_at=now,
        updated_at=now,
    )
    db.add(imported)
    emit_audit_event(
        db,
        tenant_id=tenant_id,
        actor_type=actor_type,
        actor_id=actor_id or "unknown",
        action="provider.import_to_workspace",
        target_type="provider",
        target_id=imported.id,
        result="success",
        meta={"source_provider_id": source.id, "workspace_id": workspace_id},
    )
    db.commit()
    db.refresh(imported)
    return imported


def delete_provider(db: Session, tenant_id: str, provider_id: str, *, actor_id: str | None = None, actor_type: str = "user") -> None:
    provider = get_provider_or_404(db, tenant_id, provider_id)
    if provider.managed_by_system:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="System-managed provider cannot be deleted",
        )
    skill_refs = db.scalar(select(ChatSkill.id).where(ChatSkill.provider_id == provider.id).limit(1))
    if skill_refs:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Provider is still bound to skills")
    run_refs = db.scalar(
        select(ChatRun.id).where(
            ChatRun.tenant_id == tenant_id,
            ChatRun.provider_id == provider.id,
        ).limit(1)
    )
    if run_refs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provider is still referenced by chat runs",
        )
    workspace_default_refs = db.scalar(
        select(Workspace.id).where(
            Workspace.tenant_id == tenant_id,
            Workspace.default_provider_id == provider.id,
        ).limit(1)
    )
    if workspace_default_refs:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Provider is still configured as a workspace default")
    db.query(ProviderWorkspaceShare).filter(ProviderWorkspaceShare.provider_id == provider.id).delete(synchronize_session=False)
    emit_audit_event(
        db,
        tenant_id=tenant_id,
        actor_type=actor_type,
        actor_id=actor_id or "unknown",
        action="provider.delete",
        target_type="provider",
        target_id=provider.id,
        result="success",
    )
    db.delete(provider)
    db.commit()


def _probe_model_endpoint_candidates(base_url: str) -> list[str]:
    base = base_url.rstrip("/")
    candidates: list[str] = []
    if base.endswith("/chat/completions"):
        candidates.append(f"{base[:-len('/chat/completions')]}/models")
    candidates.append(f"{base}/models")
    deduped: list[str] = []
    for candidate in candidates:
        if candidate not in deduped:
            deduped.append(candidate)
    return deduped


def _extract_model_ids(payload: object) -> list[str]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    model_ids: list[str] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        if isinstance(model_id, str) and model_id.strip() and model_id not in model_ids:
            model_ids.append(model_id.strip())
    return model_ids


def _sanitize_upstream_error(raw: str, max_len: int = 200) -> str:
    cleaned = raw.replace("\n", " ").strip()
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len] + "...(truncated)"
    return cleaned


def probe_provider_models(db: Session, tenant_id: str, provider_id: str, *, actor_id: str | None = None, actor_type: str = "user") -> ModelProvider:
    provider = get_provider_or_404(db, tenant_id, provider_id)
    try:
        api_key = decrypt_text(settings.secret_key, provider.api_key_encrypted)
    except InvalidToken as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provider secret cannot be decrypted with current SECRET_KEY; recreate or update this provider",
        ) from exc

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        **(json.loads(provider.extra_headers_json or "{}")),
    }
    last_error: str | None = None
    for endpoint in _probe_model_endpoint_candidates(provider.base_url):
        req = request.Request(endpoint, headers=headers, method="GET")
        try:
            with request.urlopen(req, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            last_error = _sanitize_upstream_error(f"{exc.code} {body or exc.reason}")
            continue
        except Exception as exc:  # pragma: no cover
            last_error = _sanitize_upstream_error(str(exc))
            continue

        model_ids = _extract_model_ids(payload)
        if not model_ids:
            last_error = "Provider returned no model ids from /models"
            continue
        provider.supported_models_json = json.dumps(
            _normalize_supported_models(provider.default_model, model_ids),
            ensure_ascii=False,
        )
        provider.updated_at = datetime.utcnow()
        emit_audit_event(
            db,
            tenant_id=tenant_id,
            actor_type=actor_type,
            actor_id=actor_id or "unknown",
            action="provider.probe",
            target_type="provider",
            target_id=provider.id,
            result="success",
            meta={"models_found": len(model_ids)},
        )
        db.commit()
        db.refresh(provider)
        return provider

    raise AppError(
        code=ErrorCode.PROVIDER_PROBE_FAILED,
        message=f"Failed to probe provider models: {last_error or 'unknown error'}",
        status_code=502,
    )


def resolve_tenant_default_provider(db: Session, tenant_id: str, *, workspace_id: str | None = None) -> ModelProvider | None:
    providers = db.scalars(
        select(ModelProvider).where(
            ModelProvider.tenant_id == tenant_id,
            ModelProvider.enabled.is_(True),
            ModelProvider.is_default.is_(True),
        )
    ).all()
    if not providers:
        return None
    share_map = _list_workspace_share_rows(db, [provider.id for provider in providers])
    for provider in providers:
        if can_bind_provider_to_workspace(provider, workspace_id, shared_workspace_ids=share_map.get(provider.id, [])):
            return provider
    return None


def resolve_workspace_default_provider(db: Session, tenant_id: str, workspace_id: str | None) -> ModelProvider | None:
    if workspace_id is None:
        return None
    workspace = db.get(Workspace, workspace_id)
    if workspace is None or workspace.tenant_id != tenant_id or not workspace.default_provider_id:
        return None
    provider = get_provider_or_404(db, tenant_id, workspace.default_provider_id)
    share_map = _list_workspace_share_rows(db, [provider.id])
    if not can_bind_provider_to_workspace(provider, workspace_id, shared_workspace_ids=share_map.get(provider.id, [])):
        return None
    return provider


def resolve_provider_config(
    db: Session,
    tenant_id: str,
    *,
    skill: ChatSkill | None = None,
    explicit_provider_id: str | None = None,
    workspace_id: str | None = None,
) -> dict:
    target_workspace_id = skill.workspace_id if skill is not None else workspace_id
    provider = None
    resolution_source = None

    if explicit_provider_id:
        provider = get_provider_or_404(db, tenant_id, explicit_provider_id)
        resolution_source = "runtime_override"
    elif skill and skill.provider_id:
        provider = get_provider_or_404(db, tenant_id, skill.provider_id)
        resolution_source = "skill_saved_provider"
    else:
        provider = resolve_workspace_default_provider(db, tenant_id, target_workspace_id)
        if provider is not None:
            resolution_source = "workspace_default_provider"
        else:
            provider = resolve_tenant_default_provider(db, tenant_id, workspace_id=target_workspace_id)
            if provider is not None:
                resolution_source = "tenant_default_provider"

    if provider:
        shared_workspace_ids = _list_workspace_share_rows(db, [provider.id]).get(provider.id, [])
        if target_workspace_id is not None and not can_bind_provider_to_workspace(
            provider,
            target_workspace_id,
            shared_workspace_ids=shared_workspace_ids,
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Provider is not accessible from this workspace",
            )
        try:
            api_key = decrypt_text(settings.secret_key, provider.api_key_encrypted)
        except InvalidToken as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Provider secret cannot be decrypted with current SECRET_KEY; recreate or update this provider",
            ) from exc
        return {
            "provider_id": provider.id,
            "provider_type": provider.provider_type,
            "name": provider.name,
            "base_url": provider.base_url,
            "api_key": api_key,
            "default_model": provider.default_model,
            "supported_models": _normalize_supported_models(
                provider.default_model,
                json.loads(provider.supported_models_json or "[]") if provider.supported_models_json else [],
            ),
            "extra_headers": json.loads(provider.extra_headers_json or "{}"),
            "resolution_source": resolution_source,
            "scope": provider_scope(provider),
            "capabilities": classify_provider_capabilities(
                provider.default_model,
                _normalize_supported_models(
                    provider.default_model,
                    json.loads(provider.supported_models_json or "[]") if provider.supported_models_json else [],
                ),
            ),
        }

    return {
        "provider_id": None,
        "provider_type": "system_default",
        "name": "system-default",
        "base_url": settings.llm_base_url,
        "api_key": settings.llm_api_key,
        "default_model": None,
        "extra_headers": {},
        "resolution_source": "system_default_provider",
        "scope": PROVIDER_SCOPE_SYSTEM,
        "capabilities": {
            "chat_models": [],
            "rerank_models": [],
            "default_rerank_model": None,
        },
    }


def resolve_system_rerank_config() -> dict:
    provider_type = normalize_rerank_provider_type(
        settings.system_rerank_provider_type,
        settings.system_rerank_base_url,
    )
    enabled = bool(
        settings.system_rerank_enabled
        and settings.system_rerank_base_url
        and settings.system_rerank_api_key
        and settings.system_rerank_model
    )
    return {
        "enabled": enabled,
        "provider_type": provider_type,
        "base_url": settings.system_rerank_base_url,
        "api_key": settings.system_rerank_api_key,
        "model": settings.system_rerank_model,
        "source": "system" if enabled else "disabled",
    }


def resolve_rerank_config(
    *,
    provider_config: dict,
    rerank_mode: str | None,
) -> dict:
    normalized_mode = str(rerank_mode or "auto").strip().lower()
    if normalized_mode not in {"auto", "off", "provider", "system"}:
        normalized_mode = "auto"
    provider_capabilities = dict(provider_config.get("capabilities") or {})
    provider_rerank_models = list(provider_capabilities.get("rerank_models") or [])
    system_config = resolve_system_rerank_config()

    if normalized_mode == "off":
        return {
            "enabled": False,
            "resolved_mode": "off",
            "provider_source": None,
            "model": None,
            "base_url": None,
            "api_key": None,
            "provider_type": None,
        }

    if normalized_mode in {"auto", "provider"} and provider_rerank_models:
        provider_type = normalize_rerank_provider_type(
            provider_config.get("provider_type"),
            provider_config.get("base_url"),
        )
        resolved_model = normalize_execution_model(
            provider_type,
            provider_capabilities.get("default_rerank_model") or provider_rerank_models[0],
        )
        return {
            "enabled": True,
            "resolved_mode": "provider",
            "provider_source": "provider",
            "model": resolved_model,
            "base_url": provider_config.get("base_url"),
            "api_key": provider_config.get("api_key"),
            "provider_type": provider_type,
        }

    if normalized_mode in {"auto", "system"} and system_config["enabled"]:
        provider_type = normalize_rerank_provider_type(
            system_config["provider_type"],
            system_config["base_url"],
        )
        return {
            "enabled": True,
            "resolved_mode": "system",
            "provider_source": "system",
            "model": normalize_execution_model(provider_type, system_config["model"]),
            "base_url": system_config["base_url"],
            "api_key": system_config["api_key"],
            "provider_type": provider_type,
        }

    return {
        "enabled": False,
        "resolved_mode": "fallback_none" if normalized_mode == "auto" else normalized_mode,
        "provider_source": None,
        "model": None,
        "base_url": None,
        "api_key": None,
        "provider_type": None,
    }
