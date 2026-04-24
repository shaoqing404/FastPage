import json

from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_principal
from app.core.db import get_db
from app.core.principal import Principal
from app.schemas.runtime_observations import RunObservationSnapshotOut
from app.services.runtime_observation_service import get_routing_asset_debug_snapshot, get_runtime_observation_snapshot
from app.services.task_queue_service import open_runtime_observation_subscription


router = APIRouter(prefix="/api/v1/runtime-observations", tags=["runtime-observations"])


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(jsonable_encoder(data), ensure_ascii=False)}\n\n"


@router.get("/debug/routing-assets")
def get_routing_asset_debug_snapshot_endpoint(
    backfill: bool = False,
    sample_limit: int = 20,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    return get_routing_asset_debug_snapshot(
        db,
        principal,
        backfill=backfill,
        sample_limit=sample_limit,
    )


@router.get("/{run_kind}/{run_id}", response_model=RunObservationSnapshotOut)
def get_runtime_observation_snapshot_endpoint(
    run_kind: str,
    run_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    return get_runtime_observation_snapshot(db, principal, run_kind=run_kind, run_id=run_id)


@router.get("/{run_kind}/{run_id}/stream")
async def stream_runtime_observations_endpoint(
    run_kind: str,
    run_id: str,
):
    async def event_stream():
        subscription = await open_runtime_observation_subscription(run_kind, run_id)
        try:
            while True:
                event = await subscription.next_event(timeout=30)
                yield _sse(event.get("event", "observation"), event.get("data"))
        finally:
            await subscription.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
