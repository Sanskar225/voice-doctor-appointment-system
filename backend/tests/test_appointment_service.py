"""Unit, schema-invariant, business-rule, and concurrency tests for AppointmentService & SQLite."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from app.domain.exceptions import (
    AmbiguousCancellationError,
    AppointmentNotFoundError,
    InvalidPhoneError,
    OverlappingAppointmentError,
    PhoneConfirmationRequiredError,
    SlotAlreadyBookedError,
)
from app.domain.models import BookAppointmentCommand, CancelAppointmentCommand
from app.domain.policies import PhoneReadbackTracker
from app.domain.value_objects import PhoneNumber, extract_phone_candidates_from_speech
from app.infrastructure.database import DatabaseManager
from app.infrastructure.event_bus import EventBus
from app.infrastructure.repositories import ClinicRepository
from app.services.appointment_service import AppointmentService


def _make_service(tmp_path: Path) -> tuple[AppointmentService, EventBus, DatabaseManager]:
    db = DatabaseManager(tmp_path / "clinic_test.db")
    db.initialize(force_reset=True)
    repo = ClinicRepository(db)
    bus = EventBus()
    return AppointmentService(db=db, repository=repo, event_bus=bus), bus, db


def test_phone_value_object_and_spoken_words() -> None:
    assert PhoneNumber.parse("+91 98765-43210").digits == "9876543210"
    assert PhoneNumber.parse("1 (415) 555-2671").display == "415-555-2671"
    assert (
        PhoneNumber.parse("nine eight seven double six five four three two one").digits
        == "9876654321"
    )
    assert "9876501234" in extract_phone_candidates_from_speech(
        "Just confirming 9-8-7, 6-5-0, 1-2-3-4 for Dr. Mehta at 2:00 PM today, right?"
    )
    assert "9876501234" in extract_phone_candidates_from_speech(
        "Your number is nine eight seven dash six five zero dash one two three four, correct?"
    )
    with pytest.raises(InvalidPhoneError):
        PhoneNumber.parse("12345")


def test_sqlite_schema_enforces_partial_unique_index_and_state_check(tmp_path: Path) -> None:
    _service, _bus, db = _make_service(tmp_path)
    with db.read_connection() as conn:
        migrations = [r["name"] for r in conn.execute("SELECT name FROM schema_migrations ORDER BY version")]
        assert migrations == [
            "001_core_clinic_schema",
            "002_appointment_audit_log",
            "003_fde_transcripts_and_config",
        ]

        existing = conn.execute(
            "SELECT doctor_id, slot_id FROM appointments WHERE status = 'confirmed' LIMIT 1"
        ).fetchone()

    # Partial unique index must block a second confirmed booking on the same slot_id directly at DB layer
    with pytest.raises(sqlite3.IntegrityError):
        with db.write_transaction() as conn:
            conn.execute(
                """
                INSERT INTO appointments
                    (id, reference_code, doctor_id, slot_id, caller_phone, status, created_at, updated_at)
                VALUES ('dup-id', 'AH-DUP01', ?, ?, '9000099999', 'confirmed', '2026-01-01', '2026-01-01')
                """,
                (existing["doctor_id"], existing["slot_id"]),
            )

    # CHECK constraint must reject status='cancelled' with NULL cancelled_at
    with pytest.raises(sqlite3.IntegrityError):
        with db.write_transaction() as conn:
            conn.execute(
                """
                INSERT INTO appointments
                    (id, reference_code, doctor_id, slot_id, caller_phone, status, created_at, updated_at, cancelled_at)
                VALUES ('bad-state', 'AH-BAD01', ?, ?, '9000088888', 'cancelled', '2026-01-01', '2026-01-01', NULL)
                """,
                (existing["doctor_id"], existing["slot_id"]),
            )


def test_phone_readback_state_machine_blocks_eager_llm_until_confirmed(tmp_path: Path) -> None:
    service, _bus, _db = _make_service(tmp_path)
    tracker = PhoneReadbackTracker()

    async def scenario() -> None:
        # Caller gives number for the first time
        tracker.observe_caller_turn()

        cmd = BookAppointmentCommand(
            caller_phone="9876501234",
            doctor_name="Dr. Aarav Mehta",
            slot_date="today",
            slot_time="2:00 PM",
            phone_confirmed_by_caller=True,  # Even if LLM falsely claims True!
        )

        # Blocked because Maya never read 9876501234 back yet
        with pytest.raises(PhoneConfirmationRequiredError):
            await service.book_appointment(cmd, readback_tracker=tracker)

        # Maya reads the number back aloud
        tracker.observe_assistant_speech("Just to confirm, your number is 9-8-7, 6-5-0, 1-2-3-4 — is that right?")

        # Still blocked until the caller actually responds after the read-back!
        with pytest.raises(PhoneConfirmationRequiredError):
            await service.book_appointment(cmd, readback_tracker=tracker)

        # Caller replies "Yes, that's right"
        tracker.observe_caller_turn()

        # Now booking succeeds cleanly
        appt, slot = await service.book_appointment(cmd, readback_tracker=tracker)
        assert appt.status == "confirmed"
        assert slot.is_booked is True

    asyncio.run(scenario())


def test_overlapping_appointment_for_same_caller_is_blocked(tmp_path: Path) -> None:
    service, _bus, _db = _make_service(tmp_path)

    async def scenario() -> None:
        await service.book_appointment(
            BookAppointmentCommand(
                caller_phone="9888811111",
                doctor_name="Dr. Meera Nair",
                slot_date="today",
                slot_time="3:00 PM",
                phone_confirmed_by_caller=True,
            )
        )
        # Same caller tries booking another doctor at the exact same date & time (3:00 PM today)
        with pytest.raises(OverlappingAppointmentError):
            await service.book_appointment(
                BookAppointmentCommand(
                    caller_phone="9888811111",
                    doctor_name="Dr. Kabir Verma",
                    slot_date="today",
                    slot_time="3:00 PM",
                    phone_confirmed_by_caller=True,
                )
            )

    asyncio.run(scenario())


def test_ambiguous_cancellation_requires_doctor_or_ref_disambiguation(tmp_path: Path) -> None:
    service, _bus, _db = _make_service(tmp_path)

    async def scenario() -> None:
        appt1, _ = await service.book_appointment(
            BookAppointmentCommand(
                caller_phone="9777700001",
                doctor_name="Dr. Aarav Mehta",
                slot_date="today",
                slot_time="2:00 PM",
                phone_confirmed_by_caller=True,
            )
        )
        await service.book_appointment(
            BookAppointmentCommand(
                caller_phone="9777700001",
                doctor_name="Dr. Meera Nair",
                slot_date="today",
                slot_time="5:00 PM",
                phone_confirmed_by_caller=True,
            )
        )

        # Ambiguous cancel without doctor_name or reference_code must raise AmbiguousCancellationError
        with pytest.raises(AmbiguousCancellationError) as exc_info:
            await service.cancel_appointment(
                CancelAppointmentCommand(
                    caller_phone="9777700001",
                    phone_confirmed_by_caller=True,
                )
            )
        assert len(exc_info.value.details["appointments"]) == 2

        # Disambiguating by reference_code cancels the exact booking
        cancelled, freed = await service.cancel_appointment(
            CancelAppointmentCommand(
                caller_phone="9777700001",
                reference_code=appt1.reference_code,
                phone_confirmed_by_caller=True,
            )
        )
        assert cancelled.id == appt1.id
        assert freed.is_booked is False

    asyncio.run(scenario())


def test_concurrent_booking_prevents_double_booking(tmp_path: Path) -> None:
    service, bus, _db = _make_service(tmp_path)

    async def scenario() -> None:
        cmd1 = BookAppointmentCommand(
            caller_phone="9876500001",
            doctor_name="Mehta",
            slot_date="today",
            slot_time="14:00",
            phone_confirmed_by_caller=True,
        )
        cmd2 = BookAppointmentCommand(
            caller_phone="9876500002",
            doctor_name="Mehta",
            slot_date="today",
            slot_time="2:00 PM",
            phone_confirmed_by_caller=True,
        )

        results = await asyncio.gather(
            service.book_appointment(cmd1, call_id="call-a"),
            service.book_appointment(cmd2, call_id="call-b"),
            return_exceptions=True,
        )
        successes = [r for r in results if not isinstance(r, Exception)]
        conflicts = [r for r in results if isinstance(r, SlotAlreadyBookedError)]

        assert len(successes) == 1
        assert len(conflicts) == 1
        assert bus.state_version == 2

    asyncio.run(scenario())


def test_book_cancel_audit_log_and_eventbus_isolation(tmp_path: Path) -> None:
    service, bus, _db = _make_service(tmp_path)

    async def scenario() -> None:
        clinic_sub = bus.subscribe(call_id=None)
        call_a_sub = bus.subscribe(call_id="call-a")
        call_b_sub = bus.subscribe(call_id="call-b")

        appt, booked_slot = await service.book_appointment(
            BookAppointmentCommand(
                caller_phone="9988776655",
                doctor_name="Dr. Aarav Mehta",
                slot_date="today",
                slot_time="2:00 PM",
                phone_confirmed_by_caller=True,
            ),
            call_id="call-a",
        )
        assert booked_slot.is_booked is True

        clinic_ev = clinic_sub.queue.get_nowait()
        assert clinic_ev.type == "appointment.booked"
        assert clinic_ev.data["appointment"]["id"] == appt.id

        call_a_ev = call_a_sub.queue.get_nowait()
        assert call_a_ev.type == "call.booking_confirmed"
        assert call_b_sub.queue.empty()

        cancelled, freed_slot = await service.cancel_appointment(
            CancelAppointmentCommand(
                caller_phone="+91-99887-76655",
                phone_confirmed_by_caller=True,
            ),
            call_id="call-a",
        )
        assert cancelled.status == "cancelled"
        assert freed_slot.is_booked is False

        # Audit log must record both 'booked' and 'cancelled' immutably
        audit = await service.get_audit_log(limit=10)
        actions = [(e.reference_code, e.action) for e in audit]
        assert (appt.reference_code, "booked") in actions
        assert (appt.reference_code, "cancelled") in actions

        with pytest.raises(AppointmentNotFoundError):
            await service.cancel_appointment(
                CancelAppointmentCommand(
                    caller_phone="9988776655",
                    phone_confirmed_by_caller=True,
                )
            )

    asyncio.run(scenario())
