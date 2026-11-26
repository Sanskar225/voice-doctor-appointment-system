"""Application dependency injection container attached to FastAPI app.state."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request, WebSocket

from ..config import Settings
from ..infrastructure.database import DatabaseManager
from ..infrastructure.event_bus import EventBus
from ..infrastructure.repositories import ClinicRepository
from ..services.appointment_service import AppointmentService
from ..voice.session import CallSessionManager


@dataclass(frozen=True)
class AppContainer:
    settings: Settings
    db: DatabaseManager
    repository: ClinicRepository
    event_bus: EventBus
    appointment_service: AppointmentService
    session_manager: CallSessionManager

    @classmethod
    def build(cls, settings: Settings) -> "AppContainer":
        db = DatabaseManager(
            db_path=settings.db_path,
            busy_timeout_ms=settings.sqlite_busy_timeout_ms,
        )
        repository = ClinicRepository(db)
        event_bus = EventBus()
        appointment_service = AppointmentService(
            db=db,
            repository=repository,
            event_bus=event_bus,
        )
        session_manager = CallSessionManager(
            event_bus=event_bus,
            repository=repository,
            max_concurrent_calls=settings.max_concurrent_calls,
        )
        return cls(
            settings=settings,
            db=db,
            repository=repository,
            event_bus=event_bus,
            appointment_service=appointment_service,
            session_manager=session_manager,
        )


def get_container(request: Request) -> AppContainer:
    return request.app.state.container


def get_ws_container(websocket: WebSocket) -> AppContainer:
    return websocket.app.state.container
