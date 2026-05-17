from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


ProviderType = Literal["openai_compatible", "dashscope", "deepseek"]
ProviderScope = Literal["tenant", "workspace", "system"]
ProviderShareMode = Literal["none", "all", "selected"]
EndpointCapability = Literal["chat", "embedding", "rerank"]
EndpointAdapter = Literal["openai_chat", "openai_embedding", "generic_rerank", "dashscope_rerank"]


class ModelProviderEndpointCreate(BaseModel):
    capability: EndpointCapability
    adapter: EndpointAdapter
    base_url: str
    model: str
    api_key: str | None = None
    extra_headers: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    is_default: bool = False


class ModelProviderEndpointUpdate(BaseModel):
    id: str | None = None
    capability: EndpointCapability | None = None
    adapter: EndpointAdapter | None = None
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    extra_headers: dict[str, Any] | None = None
    config: dict[str, Any] | None = None
    enabled: bool | None = None
    is_default: bool | None = None


class ModelProviderEndpointOut(BaseModel):
    id: str
    provider_id: str
    capability: str
    adapter: str
    base_url: str
    model: str
    extra_headers: dict[str, Any]
    config: dict[str, Any]
    enabled: bool
    is_default: bool
    health_status: str
    last_probe_at: datetime | None
    last_probe_latency_ms: int | None
    last_probe_error: str | None
    created_at: datetime
    updated_at: datetime


class ModelProviderCreate(BaseModel):
    provider_type: ProviderType
    name: str
    base_url: str
    api_key: str | None = ""
    default_model: str
    supported_models: list[str] = Field(default_factory=list)
    extra_headers: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    is_default: bool = False
    scope: ProviderScope = "tenant"
    share_mode: ProviderShareMode = "all"
    shared_workspace_ids: list[str] = Field(default_factory=list)
    endpoints: list[ModelProviderEndpointCreate] = Field(default_factory=list)


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
    endpoints: list[ModelProviderEndpointUpdate] | None = None


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
    capabilities: dict[str, Any] = Field(
        default_factory=dict,
        description="Additive capability contract for chat, rerank, and embedding model families.",
    )
    endpoints: list[ModelProviderEndpointOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ModelProviderImportResponse(BaseModel):
    source_provider_id: str
    provider: ModelProviderOut


class ProbeRuntimeRequest(BaseModel):
    capability: EndpointCapability | None = None
    endpoint_id: str | None = None


class ProbeRuntimeDraftRequest(BaseModel):
    provider_type: ProviderType
    base_url: str
    api_key: str | None = ""
    endpoints: list[ModelProviderEndpointCreate] = Field(default_factory=list)
    capability: EndpointCapability | None = None
    endpoint_id: str | None = None


class ProbeRuntimeResult(BaseModel):
    capability: str
    adapter: str
    model: str
    status: str
    latency_ms: int | None = None
    error_redacted: str | None = None
    dimensions: int | None = None
    sample_count: int | None = None
