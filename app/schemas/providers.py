from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


ProviderType = Literal["openai_compatible", "dashscope", "deepseek"]


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


class ModelProviderOut(BaseModel):
    id: str
    tenant_id: str
    provider_type: str
    name: str
    base_url: str
    default_model: str
    supported_models: list[str]
    extra_headers: dict[str, Any]
    enabled: bool
    is_default: bool
    managed_by_system: bool
    created_at: datetime
    updated_at: datetime
