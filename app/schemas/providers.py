from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


ProviderType = Literal["openai_compatible", "dashscope", "deepseek"]
ProviderScope = Literal["tenant", "workspace", "system"]
ProviderShareMode = Literal["none", "all", "selected"]


class ModelProviderCreate(BaseModel):
    provider_type: ProviderType
    name: str
    base_url: str
    api_key: str
    default_model: str
    supported_models: list[str] = Field(default_factory=list)
    extra_headers: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    is_default: bool = False
    scope: ProviderScope = "tenant"
    share_mode: ProviderShareMode = "all"
    shared_workspace_ids: list[str] = Field(default_factory=list)


class ModelProviderUpdate(BaseModel):
    provider_type: ProviderType | None = None
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    default_model: str | None = None
    supported_models: list[str] | None = None
    extra_headers: dict[str, Any] | None = None
    enabled: bool | None = None
    is_default: bool | None = None
    share_mode: ProviderShareMode | None = None
    shared_workspace_ids: list[str] | None = None


class ModelProviderOut(BaseModel):
    id: str
    tenant_id: str
    workspace_id: str | None
    provider_type: str
    name: str
    base_url: str
    default_model: str
    supported_models: list[str]
    extra_headers: dict[str, Any]
    enabled: bool
    is_default: bool
    managed_by_system: bool
    scope: ProviderScope
    share_mode: ProviderShareMode
    shared_workspace_ids: list[str]
    available_in_current_workspace: bool
    bindable_in_current_workspace: bool
    source_provider_id: str | None
    source_provider_name: str | None
    is_workspace_default_candidate: bool
    created_at: datetime
    updated_at: datetime


class ModelProviderImportResponse(BaseModel):
    source_provider_id: str
    provider: ModelProviderOut
