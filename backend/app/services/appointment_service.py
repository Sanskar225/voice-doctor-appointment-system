"""Async application service orchestrating domain policies, FDE runtime config, off-loop persistence, and events."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any

from ..domain.exceptions import InvalidDateTimeError, PhoneConfirmationRequiredError
from ..domain.models import (
    AppointmentDTO,
    AuditLogEntryDTO,
    AvailabilityResult,
    BookAppointmentCommand,
    CancelAppointmentCommand,
    ClinicConfigDTO,
    ClinicSnapshotDTO,
    DoctorDTO,
    SlotDTO,
    TranscriptEntryDTO,
    UpdateClinicConfigCommand,
)
from ..domain.policies import PhoneReadbackTracker
from ..domain.ports import ClinicRepositoryPort, EventPublisherPort
from ..domain.value_objects import PhoneNumber, parse_schedule_date, parse_schedule_time
from ..infrastructure.database import DatabaseManager


class AppointmentService:
    """Application service decoupled from storage & transport through domain ports."""

    def __init__(
        self,
        *,
        db: DatabaseManager,
        repository: ClinicRepositoryPort,
        event_bus: EventPublisherPort,
    ) -> None:
        self._db = db
        self._repo = repository
        self._bus = event_bus

    async def get_config(self) -> ClinicConfigDTO:
        return await asyncio.to_thread(self._repo.get_config)

    async def update_config(self, cmd: UpdateClinicConfigCommand) -> ClinicConfigDTO:
        updated = await asyncio.to_thread(self._repo.update_config, cmd)
        await self._bus.publish_clinic_event(
            "config.updated",
            {"config": updated.model_dump(mode="json")},
        )
        return updated

    async def get_doctors(self) -> list[DoctorDTO]:
        return await asyncio.to_thread(self._repo.list_doctors)

    async def get_appointments(self) -> list[AppointmentDTO]:
        return await asyncio.to_thread(self._repo.list_appointments)

    async def get_audit_log(self, *, limit: int = 50) -> list[AuditLogEntryDTO]:
        return await asyncio.to_thread(self._repo.list_audit_log, limit=limit)

    async def record_transcript_entry(
        self,
        *,
        call_id: str,
        role: str,
        text: str,
        latency_ms: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TranscriptEntryDTO:
        return await asyncio.to_thread(
            self._repo.append_transcript_entry,
            call_id=call_id,
            role=role,
            text=text,
            latency_ms=latency_ms,
            metadata=metadata,
        )

    async def get_call_transcript(self, call_id: str) -> list[TranscriptEntryDTO]:
        return await asyncio.to_thread(self._repo.list_call_transcript, call_id)

    async def get_snapshot(self, *, active_calls: int = 0) -> ClinicSnapshotDTO:
        config, doctors, appointments = await asyncio.gather(
            self.get_config(),
            self.get_doctors(),
            self.get_appointments(),
        )
        today = date.today()
        return ClinicSnapshotDTO(
            version=self._bus.state_version,
            today=today.isoformat(),
            tomorrow=(today + timedelta(days=1)).isoformat(),
            config=config,
            doctors=doctors,
            appointments=appointments,
            active_calls=active_calls,
        )

    async def check_availability(
        self,
        *,
        doctor_name: str | None = None,
        specialty: str | None = None,
        slot_date: str | None = None,
    ) -> AvailabilityResult:
        parsed_date = parse_schedule_date(slot_date)
        return await asyncio.to_thread(
            self._repo.query_availability,
            doctor_name=doctor_name,
            specialty=specialty,
            slot_date=parsed_date,
        )

    async def book_appointment(
        self,
        cmd: BookAppointmentCommand,
        *,
        call_id: str | None = None,
        readback_tracker: PhoneReadbackTracker | None = None,
        enforce_readback_tracker: bool = True,
    ) -> tuple[AppointmentDTO, SlotDTO]:
        phone = PhoneNumber.parse(cmd.caller_phone)

        if readback_tracker is not None and enforce_readback_tracker:
            readback_tracker.assert_verified_for_mutation(
                phone,
                llm_claimed_confirmed=cmd.phone_confirmed_by_caller,
                action_label="booking",
            )
        elif not cmd.phone_confirmed_by_caller:
            raise PhoneConfirmationRequiredError(
                f"Read the caller's phone number ({phone.display}) back and confirm before booking."
            )

        parsed_date = parse_schedule_date(cmd.slot_date)
        if not parsed_date:
            raise InvalidDateTimeError("An appointment date is required.")
        parsed_time = parse_schedule_time(cmd.slot_time)
        clean_name = (cmd.patient_name or "").strip() or "Phone Caller"
        clean_reason = (cmd.reason or "").strip() or "General Consultation"

        appointment, updated_slot = await asyncio.to_thread(
            self._repo.book_slot_atomic,
            caller_phone=phone.digits,
            doctor_name=cmd.doctor_name,
            slot_date=parsed_date,
            slot_time=parsed_time,
            patient_name=clean_name,
            reason=clean_reason,
            call_id=call_id,
        )

        payload = {
            "appointment": appointment.model_dump(mode="json"),
            "slot": updated_slot.model_dump(mode="json"),
        }
        await self._bus.publish_clinic_event(
            "appointment.booked",
            payload,
            call_id=call_id,
        )
        if call_id:
            await self.record_transcript_entry(
                call_id=call_id,
                role="booking",
                text=f"Booked {appointment.doctor_name} ({appointment.date} {appointment.time_display})",
                metadata={"appointment": appointment.model_dump(mode="json")},
            )
            await self._bus.publish_call_event(
                call_id,
                "call.booking_confirmed",
                payload,
            )
        return appointment, updated_slot

    async def cancel_appointment(
        self,
        cmd: CancelAppointmentCommand,
        *,
        call_id: str | None = None,
        readback_tracker: PhoneReadbackTracker | None = None,
        enforce_readback_tracker: bool = True,
    ) -> tuple[AppointmentDTO, SlotDTO]:
        phone = PhoneNumber.parse(cmd.caller_phone)

        if readback_tracker is not None and enforce_readback_tracker:
            readback_tracker.assert_verified_for_mutation(
                phone,
                llm_claimed_confirmed=cmd.phone_confirmed_by_caller,
                action_label="cancelling",
            )
        elif not cmd.phone_confirmed_by_caller:
            raise PhoneConfirmationRequiredError(
                f"Read the caller's phone number ({phone.display}) back and confirm before cancelling."
            )

        cancelled, freed_slot = await asyncio.to_thread(
            self._repo.cancel_appointment_atomic,
            caller_phone=phone.digits,
            doctor_name=cmd.doctor_name,
            reference_code=cmd.reference_code,
            call_id=call_id,
        )

        payload = {
            "appointment": cancelled.model_dump(mode="json"),
            "slot": freed_slot.model_dump(mode="json"),
        }
        await self._bus.publish_clinic_event(
            "appointment.cancelled",
            payload,
            call_id=call_id,
        )
        if call_id:
            await self.record_transcript_entry(
                call_id=call_id,
                role="cancellation",
                text=f"Cancelled {cancelled.doctor_name} ({cancelled.date} {cancelled.time_display})",
                metadata={"appointment": cancelled.model_dump(mode="json")},
            )
            await self._bus.publish_call_event(
                call_id,
                "call.booking_cancelled",
                payload,
            )
        return cancelled, freed_slot

    async def reset_demo_data(self, *, active_calls: int = 0) -> ClinicSnapshotDTO:
        await asyncio.to_thread(self._db.initialize, force_reset=True)
        snapshot = await self.get_snapshot(active_calls=active_calls)
        envelope = await self._bus.publish_clinic_event(
            "clinic.reset",
            snapshot.model_dump(mode="json"),
        )
        return snapshot.model_copy(update={"version": envelope.version})
