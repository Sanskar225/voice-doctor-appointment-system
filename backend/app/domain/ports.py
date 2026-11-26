"""Hexagonal port interfaces decoupling application services from persistence and messaging."""

from __future__ import annotations

from typing import Any, Protocol

from .models import (
    AppointmentDTO,
    AuditLogEntryDTO,
    AvailabilityResult,
    CallSessionSummary,
    ClinicConfigDTO,
    DoctorDTO,
    EventEnvelope,
    SlotDTO,
    TranscriptEntryDTO,
    UpdateClinicConfigCommand,
)


class ClinicRepositoryPort(Protocol):
    def get_config(self) -> ClinicConfigDTO: ...
    def update_config(self, cmd: UpdateClinicConfigCommand) -> ClinicConfigDTO: ...
    def list_doctors(self) -> list[DoctorDTO]: ...
    def list_appointments(self) -> list[AppointmentDTO]: ...
    def list_audit_log(self, *, limit: int = 50) -> list[AuditLogEntryDTO]: ...
    def query_availability(
        self,
        *,
        doctor_name: str | None = None,
        specialty: str | None = None,
        slot_date: str | None = None,
    ) -> AvailabilityResult: ...
    def book_slot_atomic(
        self,
        *,
        caller_phone: str,
        doctor_name: str,
        slot_date: str,
        slot_time: str,
        patient_name: str,
        reason: str,
        call_id: str | None = None,
    ) -> tuple[AppointmentDTO, SlotDTO]: ...
    def cancel_appointment_atomic(
        self,
        *,
        caller_phone: str,
        doctor_name: str | None = None,
        reference_code: str | None = None,
        call_id: str | None = None,
    ) -> tuple[AppointmentDTO, SlotDTO]: ...
    def upsert_call_session(self, summary: CallSessionSummary) -> None: ...
    def list_call_sessions(self, *, limit: int = 50) -> list[CallSessionSummary]: ...
    def append_transcript_entry(
        self,
        *,
        call_id: str,
        role: str,
        text: str,
        latency_ms: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TranscriptEntryDTO: ...
    def list_call_transcript(self, call_id: str) -> list[TranscriptEntryDTO]: ...


class EventPublisherPort(Protocol):
    @property
    def state_version(self) -> int: ...

    async def publish_clinic_event(
        self,
        event_type: str,
        data: dict[str, Any],
        *,
        bump_version: bool = True,
        call_id: str | None = None,
    ) -> EventEnvelope: ...

    async def publish_call_event(
        self,
        call_id: str,
        event_type: str,
        data: dict[str, Any],
    ) -> EventEnvelope: ...
