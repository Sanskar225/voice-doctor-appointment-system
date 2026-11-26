"""Versioned REST routes for clinic health, snapshot, FDE config, doctors, appointments, audit log, and reset."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..domain.models import (
    AppointmentDTO,
    AuditLogEntryDTO,
    BookAppointmentCommand,
    CancelAppointmentCommand,
    ClinicConfigDTO,
    ClinicSnapshotDTO,
    DoctorDTO,
    HealthDTO,
    UpdateClinicConfigCommand,
)
from .container import AppContainer, get_container

router = APIRouter(prefix="/api/v1", tags=["clinic"])


@router.get("/health", response_model=HealthDTO)
async def get_health(container: AppContainer = Depends(get_container)) -> HealthDTO:
    s = container.settings
    return HealthDTO(
        status="ok",
        version=s.app_version,
        voice_ready=s.voice_ready,
        missing_keys=s.missing_voice_keys,
        llm_model=s.gemini_model,
        active_calls=container.session_manager.active_count,
        state_version=container.event_bus.state_version,
    )


@router.get("/config", response_model=ClinicConfigDTO)
async def get_config(container: AppContainer = Depends(get_container)) -> ClinicConfigDTO:
    return await container.appointment_service.get_config()


@router.patch("/config", response_model=ClinicConfigDTO)
async def update_config(
    cmd: UpdateClinicConfigCommand,
    container: AppContainer = Depends(get_container),
) -> ClinicConfigDTO:
    return await container.appointment_service.update_config(cmd)


@router.get("/clinic/snapshot", response_model=ClinicSnapshotDTO)
async def get_clinic_snapshot(
    container: AppContainer = Depends(get_container),
) -> ClinicSnapshotDTO:
    return await container.appointment_service.get_snapshot(
        active_calls=container.session_manager.active_count
    )


@router.get("/doctors", response_model=list[DoctorDTO])
async def list_doctors(
    container: AppContainer = Depends(get_container),
) -> list[DoctorDTO]:
    return await container.appointment_service.get_doctors()


@router.get("/appointments", response_model=list[AppointmentDTO])
async def list_appointments(
    container: AppContainer = Depends(get_container),
) -> list[AppointmentDTO]:
    return await container.appointment_service.get_appointments()


@router.get("/audit", response_model=list[AuditLogEntryDTO])
async def list_audit_log(
    limit: int = Query(default=50, ge=1, le=200),
    container: AppContainer = Depends(get_container),
) -> list[AuditLogEntryDTO]:
    return await container.appointment_service.get_audit_log(limit=limit)


@router.post("/appointments", response_model=AppointmentDTO, status_code=201)
async def create_appointment(
    cmd: BookAppointmentCommand,
    container: AppContainer = Depends(get_container),
) -> AppointmentDTO:
    appointment, _slot = await container.appointment_service.book_appointment(cmd)
    return appointment


@router.post("/appointments/cancel", response_model=AppointmentDTO)
async def cancel_appointment(
    cmd: CancelAppointmentCommand,
    container: AppContainer = Depends(get_container),
) -> AppointmentDTO:
    cancelled, _slot = await container.appointment_service.cancel_appointment(cmd)
    return cancelled


@router.post("/clinic/reset", response_model=ClinicSnapshotDTO)
async def reset_clinic(
    container: AppContainer = Depends(get_container),
) -> ClinicSnapshotDTO:
    return await container.appointment_service.reset_demo_data(
        active_calls=container.session_manager.active_count
    )
