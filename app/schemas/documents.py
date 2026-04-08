from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    document_id: str
    version_no: int
    storage_path: str
    file_hash: str
    parse_status: str
    parsed_structure_path: str | None
    parse_error: str | None
    created_at: datetime


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    tenant_id: str
    owner_user_id: str
    display_name: str
    source_filename: str
    active_version_id: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class ParseRequest(BaseModel):
    version_id: str | None = None
    model: str | None = None


class RestoreVersionResponse(BaseModel):
    document_id: str
    active_version_id: str
