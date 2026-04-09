import json
import logging
import uuid
from datetime import datetime
from urllib import error, request

from fastapi import HTTPException, status
from cryptography.fernet import InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import decrypt_text, encrypt_text
from app.core.errors import AppError, ErrorCode
from app.core.url_validator import validate_provider_url
from app.models import ChatRun, ChatSkill, ModelProvider
from app.services.audit_service import emit_audit_event


logger = logging.getLogger(__name__)
settings = get_settings()


def _normalize_supported_models(default_model: str, supported_models: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for model in [default_model, *(supported_models or [])]:
        candidate = model.strip()
        if not candidate or candidate in normalized:
            continue
        normalized.append(candidate)
    return normalized or [default_model]


def serialize_provider(provider: ModelProvider) -> dict:
    supported_models = json.loads(provider.supported_models_json or "[]")
    if not isinstance(supported_models, list):
        supported_models = []
    normalized_supported_models = _normalize_supported_models(provider.default_model, supported_models)
    return {
        "id": provider.id,
        "tenant_id": provider.tenant_id,
        "provider_type": provider.provider_type,
        "name": provider.name,
        "base_url": provider.base_url,
        "default_model": provider.default_model,
        "supported_models": normalized_supported_models,
        "extra_headers": json.loads(provider.extra_headers_json or "{}"),
        "enabled": provider.enabled,
        "is_default": provider.is_default,
        "managed_by_system": provider.managed_by_system,
        "created_at": provider.created_at,
        "updated_at": provider.updated_at,
    }


def list_tenant_providers(db: Session, tenant_id: str) -> list[ModelProvider]:
    return db.scalars(select(ModelProvider).where(ModelProvider.tenant_id == tenant_id).order_by(ModelProvider.created_at.desc())).all()


def get_provider_or_404(db: Session, tenant_id: str, provider_id: str) -> ModelProvider:
    provider = db.get(ModelProvider, provider_id)
    if provider is None or provider.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")
    return provider


def can_bind_provider_to_workspace(provider: ModelProvider, workspace_id: str) -> bool:
    if provider.workspace_id is None:
        return True
    return provider.workspace_id == workspace_id


def _clear_default_provider(db: Session, tenant_id: str, keep_provider_id: str | None = None) -> None:
    providers = db.scalars(select(ModelProvider).where(ModelProvider.tenant_id == tenant_id, ModelProvider.is_default.is_(True))).all()
    for provider in providers:
        if keep_provider_id and provider.id == keep_provider_id:
            continue
        provider.is_default = False


def create_provider(db: Session, tenant_id: str, payload, *, actor_id: str | None = None, actor_type: str = "user") -> ModelProvider:
    # Validate base_url before persisting.
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

    now = datetime.utcnow()
    supported_models = _normalize_supported_models(payload.default_model, getattr(payload, "supported_models", None))
    provider = ModelProvider(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        provider_type=payload.provider_type,
        name=payload.name,
        base_url=validated_url,
        api_key_encrypted=encrypt_text(settings.secret_key, payload.api_key),
        default_model=payload.default_model,
        supported_models_json=json.dumps(supported_models, ensure_ascii=False),
        extra_headers_json=json.dumps(payload.extra_headers, ensure_ascii=False),
        enabled=payload.enabled,
        is_default=payload.is_default,
        managed_by_system=False,
        created_at=now,
        updated_at=now,
    )
    if provider.is_default:
        _clear_default_provider(db, tenant_id)
    db.add(provider)
    emit_audit_event(
        db,
        tenant_id=tenant_id,
        actor_type=actor_type,
        actor_id=actor_id or "unknown",
        action="provider.create",
        target_type="provider",
        target_id=provider.id,
        result="success",
    )
    db.commit()
    db.refresh(provider)
    return provider


def update_provider(db: Session, tenant_id: str, provider_id: str, payload, *, actor_id: str | None = None, actor_type: str = "user") -> ModelProvider:
    provider = get_provider_or_404(db, tenant_id, provider_id)
    if provider.managed_by_system:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="System-managed provider is synced from environment and cannot be edited",
        )
    update_dict = payload.model_dump(exclude_unset=True)

    # Validate base_url if it's being changed.
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
    if update_dict.get("is_default") is True:
        _clear_default_provider(db, tenant_id, keep_provider_id=provider.id)
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
    )
    db.commit()
    db.refresh(provider)
    return provider


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
    """Truncate and strip secrets from upstream error bodies."""
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
        except Exception as exc:  # pragma: no cover - network/runtime failure path
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


def resolve_provider_config(
    db: Session,
    tenant_id: str,
    *,
    skill: ChatSkill | None = None,
    explicit_provider_id: str | None = None,
    workspace_id: str | None = None,
) -> dict:
    provider = None
    if skill and skill.provider_id:
        provider = get_provider_or_404(db, tenant_id, skill.provider_id)
    elif explicit_provider_id:
        provider = get_provider_or_404(db, tenant_id, explicit_provider_id)
    else:
        provider = db.scalar(
            select(ModelProvider).where(
                ModelProvider.tenant_id == tenant_id,
                ModelProvider.enabled.is_(True),
                ModelProvider.is_default.is_(True),
            )
        )

    if provider:
        target_workspace_id = skill.workspace_id if skill is not None else workspace_id
        if target_workspace_id is not None and not can_bind_provider_to_workspace(provider, target_workspace_id):
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
        }

    return {
        "provider_id": None,
        "provider_type": "system_default",
        "name": "system-default",
        "base_url": settings.llm_base_url,
        "api_key": settings.llm_api_key,
        "default_model": None,
        "extra_headers": {},
    }
