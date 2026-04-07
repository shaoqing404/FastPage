from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ParseJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    tenant_id: str
    document_id: str
    version_id: str
    model: str | None
    status: str
    current_step: str | None
    progress_percent: int
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    error_message: str | None
    created_at: datetime
