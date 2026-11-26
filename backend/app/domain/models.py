"""Strict Pydantic v2 domain models, API DTOs, FDE config, audit entries, and event envelopes."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AppointmentStatus(StrEnum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class CallLifecycleState(StrEnum):
    CREATED = "created"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ENDED = "ended"
    ERROR = "error"


class ClinicConfigDTO(BaseModel):
    """Live client-deployable clinic and receptionist configuration (FDE runtime settings)."""

    model_config = ConfigDict(frozen=True)

    clinic_name: str = "Aurelia Health"
    agent_name: str = "Maya"
    greeting_tone: Literal["warm", "formal"] = "warm"
    tts_speed: float = Field(default=1.02, ge=0.8, le=1.2)
    strict_phone_readback: bool = True
    updated_at: str = ""


class UpdateClinicConfigCommand(BaseModel):
    clinic_name: str | None = Field(default=None, min_length=2, max_length=60)
    agent_name: str | None = Field(default=None, min_length=2, max_length=32)
    greeting_tone: Literal["warm", "formal"] | None = None
    tts_speed: float | None = Field(default=None, ge=0.8, le=1.2)
    strict_phone_readback: bool | None = None


class SlotDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    doctor_id: str
    date: str
    time: str
    time_display: str
    is_booked: bool


class DoctorDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    specialty: str
    room: str
    experience_years: int
    initials: str
    available_count: int
    slots: list[SlotDTO]


class AppointmentDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    reference_code: str
    doctor_id: str
    doctor_name: str
    doctor_specialty: str
    doctor_room: str
    slot_id: str
    date: str
    time: str
    time_display: str
    caller_phone: str
    caller_phone_display: str
    patient_name: str
    reason: str
    status: AppointmentStatus
    booked_via_call_id: str | None = None
    created_at: str
    cancelled_at: str | None = None


class AuditLogEntryDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    appointment_id: str
    reference_code: str
    action: str
    caller_phone: str
    call_id: str | None = None
    created_at: str


class TranscriptEntryDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    call_id: str
    role: Literal["caller", "agent", "tool", "booking", "cancellation"]
    text: str
    latency_ms: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class AvailableSlotItem(BaseModel):
    slot_id: str
    date: str
    day_label: str
    time: str
    time_display: str


class DoctorAvailabilityMatch(BaseModel):
    doctor_id: str
    doctor_name: str
    specialty: str
    room: str
    available_slots: list[AvailableSlotItem]


class AvailabilityResult(BaseModel):
    today: str
    tomorrow: str
    matches: list[DoctorAvailabilityMatch]
    total_open_slots: int


class BookAppointmentCommand(BaseModel):
    caller_phone: str = Field(..., min_length=1)
    doctor_name: str = Field(..., min_length=1)
    slot_date: str = Field(..., min_length=1)
    slot_time: str = Field(..., min_length=1)
    patient_name: str | None = None
    reason: str | None = None
    phone_confirmed_by_caller: bool = True


class CancelAppointmentCommand(BaseModel):
    caller_phone: str = Field(..., min_length=1)
    doctor_name: str | None = None
    reference_code: str | None = None
    phone_confirmed_by_caller: bool = True


class CallSessionSummary(BaseModel):
    call_id: str
    state: CallLifecycleState
    created_at: str
    connected_at: str | None = None
    ended_at: str | None = None
    caller_phone: str | None = None
    phone_confirmed: bool = False
    turns_count: int = 0
    tool_calls_count: int = 0
    avg_llm_ttft_ms: int | None = None
    outcome: str | None = None


class ClinicSnapshotDTO(BaseModel):
    version: int
    today: str
    tomorrow: str
    config: ClinicConfigDTO
    doctors: list[DoctorDTO]
    appointments: list[AppointmentDTO]
    active_calls: int


class HealthDTO(BaseModel):
    status: str
    version: str
    voice_ready: bool
    missing_keys: list[str]
    llm_model: str
    active_calls: int
    state_version: int


class EventEnvelope(BaseModel):
    """Unified envelope for clinic-wide domain events and call-scoped voice telemetry."""

    id: int
    scope: str  # "clinic" or "call"
    type: str
    version: int
    call_id: str | None = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    data: dict[str, Any] = Field(default_factory=dict)
