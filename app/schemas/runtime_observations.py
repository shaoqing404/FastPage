from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


RunKind = Literal["chat", "compliance", "parse_job"]


class RunObservationEventOut(BaseModel):
    id: str
    run_kind: RunKind
    run_id: str
    sequence_no: int
    event_type: str
    step: str | None
    status: str | None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class RunObservationSnapshotOut(BaseModel):
    run_kind: RunKind
    run_id: str
    status: str
    current_step: str | None = None
    worker_node_code: str | None = None
    queue: dict[str, Any] = Field(default_factory=dict)
    timings: dict[str, Any] = Field(default_factory=dict)
    execution_context: dict[str, Any] = Field(default_factory=dict)
    partial_answer: str | None = None
    events: list[RunObservationEventOut] = Field(default_factory=list)
