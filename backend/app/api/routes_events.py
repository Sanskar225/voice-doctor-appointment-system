"""Server-Sent Events endpoint with clean clinic-wide vs call-scoped stream isolation."""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from .container import AppContainer, get_container

router = APIRouter(prefix="/api/v1", tags=["events"])


@router.get("/events")
async def stream_events(
    request: Request,
    call_id: str | None = Query(
        default=None,
        description="Omit for clinic-wide domain updates; pass call_id for isolated call telemetry.",
    ),
    container: AppContainer = Depends(get_container),
) -> StreamingResponse:
    bus = container.event_bus

    async def event_generator() -> AsyncIterator[str]:
        sub = bus.subscribe(call_id=call_id)
        try:
            handshake = json.dumps(
                {
                    "id": 0,
                    "scope": "call" if call_id else "clinic",
                    "type": "stream.connected",
                    "version": bus.state_version,
                    "call_id": call_id,
                    "data": {},
                }
            )
            yield f"id: 0\ndata: {handshake}\n\n"

            while not await request.is_disconnected():
                try:
                    envelope = await asyncio.wait_for(sub.queue.get(), timeout=20.0)
                    yield f"id: {envelope.id}\ndata: {envelope.model_dump_json()}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            bus.unsubscribe(sub)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
