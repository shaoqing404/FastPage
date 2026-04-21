from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_principal
from app.core.db import get_db
from app.core.principal import Principal
from app.schemas.providers import ModelProviderCreate, ModelProviderImportResponse, ModelProviderOut, ModelProviderUpdate
from app.services.provider_service import (
    create_provider,
    delete_provider,
    import_provider_to_workspace,
    list_bindable_catalog,
    list_tenant_providers,
    probe_provider_models,
    serialize_provider,
    update_provider,
)
from app.services.workspace_access_service import require_workspace_capability


router = APIRouter(prefix="/api/v1/model-providers", tags=["providers"])


@router.post("", response_model=ModelProviderOut)
def create_provider_endpoint(
    payload: ModelProviderCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    require_workspace_capability(
        principal,
        "can_manage_providers",
        detail="Missing workspace capability: can_manage_providers",
    )
    provider = create_provider(
        db,
        principal.tenant_id,
        payload,
        workspace_id=principal.workspace_id,
        actor_id=principal.user_id,
        actor_type=principal.kind,
    )
    return serialize_provider(db, provider, current_workspace_id=principal.workspace_id)


@router.get("", response_model=list[ModelProviderOut])
def list_providers(
    scope: str = Query(default="all"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    require_workspace_capability(
        principal,
        "can_manage_providers",
        detail="Missing workspace capability: can_manage_providers",
    )
    providers = list_tenant_providers(db, principal.tenant_id, scope=scope, workspace_id=principal.workspace_id)
    return [serialize_provider(db, provider, current_workspace_id=principal.workspace_id) for provider in providers]


@router.get("/catalog", response_model=list[ModelProviderOut])
def list_provider_catalog(
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    providers = list_bindable_catalog(db, principal.tenant_id, principal.workspace_id)
    return [serialize_provider(db, provider, current_workspace_id=principal.workspace_id) for provider in providers]


@router.patch("/{provider_id}", response_model=ModelProviderOut)
def patch_provider(
    provider_id: str,
    payload: ModelProviderUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    require_workspace_capability(
        principal,
        "can_manage_providers",
        detail="Missing workspace capability: can_manage_providers",
    )
    provider = update_provider(db, principal.tenant_id, provider_id, payload, actor_id=principal.user_id, actor_type=principal.kind)
    return serialize_provider(db, provider, current_workspace_id=principal.workspace_id)


@router.delete("/{provider_id}", status_code=204)
def remove_provider(
    provider_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
) -> Response:
    require_workspace_capability(
        principal,
        "can_manage_providers",
        detail="Missing workspace capability: can_manage_providers",
    )
    delete_provider(db, principal.tenant_id, provider_id, actor_id=principal.user_id, actor_type=principal.kind)
    return Response(status_code=204)


@router.post("/{provider_id}/probe-models", response_model=ModelProviderOut)
def probe_provider_models_endpoint(
    provider_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    require_workspace_capability(
        principal,
        "can_manage_providers",
        detail="Missing workspace capability: can_manage_providers",
    )
    provider = probe_provider_models(db, principal.tenant_id, provider_id, actor_id=principal.user_id, actor_type=principal.kind)
    return serialize_provider(db, provider, current_workspace_id=principal.workspace_id)


@router.post("/{provider_id}/import-to-workspace", response_model=ModelProviderImportResponse)
def import_provider_to_workspace_endpoint(
    provider_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    require_workspace_capability(
        principal,
        "can_manage_providers",
        detail="Missing workspace capability: can_manage_providers",
    )
    if principal.workspace_id is None:
        raise HTTPException(status_code=400, detail="Current workspace is required")
    provider = import_provider_to_workspace(
        db,
        principal.tenant_id,
        provider_id,
        workspace_id=principal.workspace_id,
        actor_id=principal.user_id,
        actor_type=principal.kind,
    )
    return {
        "source_provider_id": provider_id,
        "provider": serialize_provider(db, provider, current_workspace_id=principal.workspace_id),
    }
