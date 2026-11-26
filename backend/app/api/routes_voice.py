"""Voice call provisioning, durable transcript lookup, and Pipecat binary PCM WebSocket."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, WebSocket
from pydantic import BaseModel

from ..domain.models import CallSessionSummary, TranscriptEntryDTO
from ..voice.pipeline import run_voice_session
from .container import AppContainer, get_container, get_ws_container

router = APIRouter(tags=["voice"])


class CreateCallResponse(BaseModel):
    call_id: str
    ws_path: str
    events_path: str


@router.post("/api/v1/calls", response_model=CreateCallResponse, status_code=201)
async def create_call_session(
    container: AppContainer = Depends(get_container),
) -> CreateCallResponse:
    session = await container.session_manager.create_session()
    return CreateCallResponse(
        call_id=session.call_id,
        ws_path=f"/ws/voice/{session.call_id}",
        events_path=f"/api/v1/events?call_id={session.call_id}",
    )


@router.get("/api/v1/calls", response_model=list[CallSessionSummary])
async def list_call_sessions(
    limit: int = Query(default=50, ge=1, le=200),
    container: AppContainer = Depends(get_container),
) -> list[CallSessionSummary]:
    return await container.session_manager.list_sessions(limit=limit)


@router.get("/api/v1/calls/{call_id}/transcript", response_model=list[TranscriptEntryDTO])
async def get_call_transcript(
    call_id: str,
    container: AppContainer = Depends(get_container),
) -> list[TranscriptEntryDTO]:
    return await container.appointment_service.get_call_transcript(call_id)


@router.websocket("/ws/voice/{call_id}")
async def voice_websocket(
    websocket: WebSocket,
    call_id: str,
) -> None:
    await websocket.accept()
    container = get_ws_container(websocket)
    session = await container.session_manager.get_or_create_session(call_id)
    await run_voice_session(
        websocket=websocket,
        session=session,
        settings=container.settings,
        service=container.appointment_service,
        event_bus=container.event_bus,
        session_manager=container.session_manager,
    )
