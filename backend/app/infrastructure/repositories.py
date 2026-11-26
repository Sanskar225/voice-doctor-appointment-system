"""SQLite repository implementing ClinicRepositoryPort with atomic business-rule enforcement."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from ..domain.exceptions import (
    AmbiguousCancellationError,
    AmbiguousDoctorError,
    AppointmentNotFoundError,
    DoctorNotFoundError,
    OverlappingAppointmentError,
    SlotAlreadyBookedError,
    SlotNotFoundError,
)
from ..domain.models import (
    AppointmentDTO,
    AppointmentStatus,
    AuditLogEntryDTO,
    AvailabilityResult,
    AvailableSlotItem,
    CallLifecycleState,
    CallSessionSummary,
    ClinicConfigDTO,
    DoctorAvailabilityMatch,
    DoctorDTO,
    SlotDTO,
    TranscriptEntryDTO,
    UpdateClinicConfigCommand,
)
from ..domain.value_objects import format_phone_display, format_time_12h
from .database import DatabaseManager


class ClinicRepository:
    """Data-access adapter enforcing transactional invariants and returning immutable DTOs."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def get_config(self) -> ClinicConfigDTO:
        with self._db.read_connection() as conn:
            row = conn.execute(
                """
                SELECT clinic_name, agent_name, greeting_tone, tts_speed, strict_phone_readback, updated_at
                FROM clinic_config
                WHERE id = 1
                """
            ).fetchone()
        if row is None:
            return ClinicConfigDTO()
        return ClinicConfigDTO(
            clinic_name=row["clinic_name"],
            agent_name=row["agent_name"],
            greeting_tone=row["greeting_tone"],
            tts_speed=float(row["tts_speed"]),
            strict_phone_readback=bool(row["strict_phone_readback"]),
            updated_at=row["updated_at"],
        )

    def update_config(self, cmd: UpdateClinicConfigCommand) -> ClinicConfigDTO:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._db.write_transaction() as conn:
            current = conn.execute(
                """
                SELECT clinic_name, agent_name, greeting_tone, tts_speed, strict_phone_readback
                FROM clinic_config
                WHERE id = 1
                """
            ).fetchone()
            clinic_name = (
                cmd.clinic_name.strip()
                if cmd.clinic_name is not None
                else (current["clinic_name"] if current else "Aurelia Health")
            )
            agent_name = (
                cmd.agent_name.strip()
                if cmd.agent_name is not None
                else (current["agent_name"] if current else "Maya")
            )
            greeting_tone = (
                cmd.greeting_tone
                if cmd.greeting_tone is not None
                else (current["greeting_tone"] if current else "warm")
            )
            tts_speed = (
                round(float(cmd.tts_speed), 2)
                if cmd.tts_speed is not None
                else (float(current["tts_speed"]) if current else 1.02)
            )
            strict_phone = (
                cmd.strict_phone_readback
                if cmd.strict_phone_readback is not None
                else (bool(current["strict_phone_readback"]) if current else True)
            )
            conn.execute(
                """
                INSERT INTO clinic_config
                    (id, clinic_name, agent_name, greeting_tone, tts_speed, strict_phone_readback, updated_at)
                VALUES (1, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    clinic_name = excluded.clinic_name,
                    agent_name = excluded.agent_name,
                    greeting_tone = excluded.greeting_tone,
                    tts_speed = excluded.tts_speed,
                    strict_phone_readback = excluded.strict_phone_readback,
                    updated_at = excluded.updated_at
                """,
                (
                    clinic_name,
                    agent_name,
                    greeting_tone,
                    tts_speed,
                    1 if strict_phone else 0,
                    now_iso,
                ),
            )
        return ClinicConfigDTO(
            clinic_name=clinic_name,
            agent_name=agent_name,
            greeting_tone=greeting_tone,
            tts_speed=tts_speed,
            strict_phone_readback=strict_phone,
            updated_at=now_iso,
        )

    def list_doctors(self) -> list[DoctorDTO]:
        today_iso = date.today().isoformat()
        with self._db.read_connection() as conn:
            doc_rows = conn.execute(
                "SELECT id, name, specialty, room, experience_years, initials FROM doctors ORDER BY name"
            ).fetchall()
            slot_rows = conn.execute(
                """
                SELECT id, doctor_id, slot_date, slot_time, is_booked
                FROM slots
                WHERE slot_date >= ?
                ORDER BY slot_date, slot_time
                """,
                (today_iso,),
            ).fetchall()

        slots_by_doc: dict[str, list[SlotDTO]] = {}
        for row in slot_rows:
            slots_by_doc.setdefault(row["doctor_id"], []).append(
                SlotDTO(
                    id=row["id"],
                    doctor_id=row["doctor_id"],
                    date=row["slot_date"],
                    time=row["slot_time"],
                    time_display=format_time_12h(row["slot_time"]),
                    is_booked=bool(row["is_booked"]),
                )
            )

        return [
            DoctorDTO(
                id=row["id"],
                name=row["name"],
                specialty=row["specialty"],
                room=row["room"],
                experience_years=row["experience_years"],
                initials=row["initials"],
                available_count=sum(1 for s in slots_by_doc.get(row["id"], []) if not s.is_booked),
                slots=slots_by_doc.get(row["id"], []),
            )
            for row in doc_rows
        ]

    def list_appointments(self) -> list[AppointmentDTO]:
        with self._db.read_connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    a.id,
                    a.reference_code,
                    a.doctor_id,
                    d.name AS doctor_name,
                    d.specialty AS doctor_specialty,
                    d.room AS doctor_room,
                    a.slot_id,
                    s.slot_date,
                    s.slot_time,
                    a.caller_phone,
                    a.patient_name,
                    a.reason,
                    a.status,
                    a.booked_via_call_id,
                    a.created_at,
                    a.cancelled_at
                FROM appointments a
                JOIN doctors d ON d.id = a.doctor_id
                JOIN slots s ON s.id = a.slot_id
                ORDER BY a.created_at DESC
                """
            ).fetchall()

        return [
            AppointmentDTO(
                id=r["id"],
                reference_code=r["reference_code"],
                doctor_id=r["doctor_id"],
                doctor_name=r["doctor_name"],
                doctor_specialty=r["doctor_specialty"],
                doctor_room=r["doctor_room"],
                slot_id=r["slot_id"],
                date=r["slot_date"],
                time=r["slot_time"],
                time_display=format_time_12h(r["slot_time"]),
                caller_phone=r["caller_phone"],
                caller_phone_display=format_phone_display(r["caller_phone"]),
                patient_name=r["patient_name"],
                reason=r["reason"],
                status=AppointmentStatus(r["status"]),
                booked_via_call_id=r["booked_via_call_id"],
                created_at=r["created_at"],
                cancelled_at=r["cancelled_at"],
            )
            for r in rows
        ]

    def list_audit_log(self, *, limit: int = 50) -> list[AuditLogEntryDTO]:
        with self._db.read_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, appointment_id, reference_code, action, caller_phone, call_id, created_at
                FROM appointment_audit_log
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [
            AuditLogEntryDTO(
                id=r["id"],
                appointment_id=r["appointment_id"],
                reference_code=r["reference_code"],
                action=r["action"],
                caller_phone=r["caller_phone"],
                call_id=r["call_id"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def query_availability(
        self,
        *,
        doctor_name: str | None = None,
        specialty: str | None = None,
        slot_date: str | None = None,
    ) -> AvailabilityResult:
        today = date.today()
        today_str = today.isoformat()
        tomorrow_str = (today + timedelta(days=1)).isoformat()

        sql = """
            SELECT
                d.id AS doctor_id,
                d.name AS doctor_name,
                d.specialty,
                d.room,
                s.id AS slot_id,
                s.slot_date,
                s.slot_time
            FROM doctors d
            JOIN slots s ON s.doctor_id = d.id
            WHERE s.is_booked = 0 AND s.slot_date >= ?
        """
        params: list[Any] = [today_str]
        if doctor_name:
            sql += " AND LOWER(d.name) LIKE ?"
            params.append(f"%{doctor_name.strip().lower()}%")
        if specialty:
            sql += " AND LOWER(d.specialty) LIKE ?"
            params.append(f"%{specialty.strip().lower()}%")
        if slot_date:
            sql += " AND s.slot_date = ?"
            params.append(slot_date)

        sql += " ORDER BY d.name, s.slot_date, s.slot_time"

        with self._db.read_connection() as conn:
            rows = conn.execute(sql, params).fetchall()

        grouped: dict[str, DoctorAvailabilityMatch] = {}
        for r in rows:
            match = grouped.get(r["doctor_id"])
            if match is None:
                match = DoctorAvailabilityMatch(
                    doctor_id=r["doctor_id"],
                    doctor_name=r["doctor_name"],
                    specialty=r["specialty"],
                    room=r["room"],
                    available_slots=[],
                )
                grouped[r["doctor_id"]] = match

            day_label = (
                "Today"
                if r["slot_date"] == today_str
                else ("Tomorrow" if r["slot_date"] == tomorrow_str else r["slot_date"])
            )
            match.available_slots.append(
                AvailableSlotItem(
                    slot_id=r["slot_id"],
                    date=r["slot_date"],
                    day_label=day_label,
                    time=r["slot_time"],
                    time_display=format_time_12h(r["slot_time"]),
                )
            )

        return AvailabilityResult(
            today=today_str,
            tomorrow=tomorrow_str,
            matches=list(grouped.values()),
            total_open_slots=len(rows),
        )

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
    ) -> tuple[AppointmentDTO, SlotDTO]:
        """Atomically enforce doctor match, caller overlap check, slot reservation, and audit log."""
        with self._db.write_transaction() as conn:
            clean_query = doctor_name.strip().lower()
            matches = conn.execute(
                """
                SELECT id, name, specialty, room
                FROM doctors
                WHERE LOWER(name) LIKE ? OR LOWER(specialty) LIKE ?
                ORDER BY name
                """,
                (f"%{clean_query}%", f"%{clean_query}%"),
            ).fetchall()

            if len(matches) == 0:
                raise DoctorNotFoundError(f"No physician matching '{doctor_name}' was found.")
            if len(matches) > 1:
                names = ", ".join(m["name"] for m in matches)
                raise AmbiguousDoctorError(
                    f"Multiple physicians match '{doctor_name}': {names}. Please specify which doctor.",
                    details={"matches": [m["name"] for m in matches]},
                )
            doctor = matches[0]

            slot = conn.execute(
                """
                SELECT id, doctor_id, slot_date, slot_time, is_booked
                FROM slots
                WHERE doctor_id = ? AND slot_date = ? AND slot_time = ?
                """,
                (doctor["id"], slot_date, slot_time),
            ).fetchone()
            if slot is None:
                raise SlotNotFoundError(
                    f"{doctor['name']} does not have a slot on {slot_date} at {format_time_12h(slot_time)}."
                )

            overlap = conn.execute(
                """
                SELECT a.reference_code, d.name AS doctor_name
                FROM appointments a
                JOIN slots s ON s.id = a.slot_id
                JOIN doctors d ON d.id = a.doctor_id
                WHERE a.caller_phone = ?
                  AND a.status = 'confirmed'
                  AND s.slot_date = ?
                  AND s.slot_time = ?
                LIMIT 1
                """,
                (caller_phone, slot_date, slot_time),
            ).fetchone()
            if overlap is not None:
                raise OverlappingAppointmentError(
                    f"Caller {format_phone_display(caller_phone)} already has a confirmed appointment "
                    f"with {overlap['doctor_name']} at {format_time_12h(slot_time)} on {slot_date} "
                    f"(Ref {overlap['reference_code']})."
                )

            cursor = conn.execute(
                "UPDATE slots SET is_booked = 1 WHERE id = ? AND is_booked = 0",
                (slot["id"],),
            )
            if cursor.rowcount != 1:
                raise SlotAlreadyBookedError(
                    f"The {format_time_12h(slot_time)} slot with {doctor['name']} on {slot_date} is already booked."
                )

            appt_id = str(uuid.uuid4())
            ref_code = f"AH-{uuid.uuid4().hex[:5].upper()}"
            now_iso = datetime.now(timezone.utc).isoformat()

            fk_call_id: str | None = None
            if call_id:
                exists = conn.execute(
                    "SELECT 1 FROM call_sessions WHERE call_id = ?", (call_id,)
                ).fetchone()
                if exists:
                    fk_call_id = call_id

            conn.execute(
                """
                INSERT INTO appointments
                    (id, reference_code, doctor_id, slot_id, caller_phone, patient_name, reason, status, booked_via_call_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'confirmed', ?, ?, ?)
                """,
                (
                    appt_id,
                    ref_code,
                    doctor["id"],
                    slot["id"],
                    caller_phone,
                    patient_name,
                    reason,
                    fk_call_id,
                    now_iso,
                    now_iso,
                ),
            )
            conn.execute(
                """
                INSERT INTO appointment_audit_log (appointment_id, reference_code, action, caller_phone, call_id, created_at)
                VALUES (?, ?, 'booked', ?, ?, ?)
                """,
                (appt_id, ref_code, caller_phone, call_id, now_iso),
            )

        updated_slot = SlotDTO(
            id=slot["id"],
            doctor_id=doctor["id"],
            date=slot["slot_date"],
            time=slot["slot_time"],
            time_display=format_time_12h(slot["slot_time"]),
            is_booked=True,
        )
        appointment = AppointmentDTO(
            id=appt_id,
            reference_code=ref_code,
            doctor_id=doctor["id"],
            doctor_name=doctor["name"],
            doctor_specialty=doctor["specialty"],
            doctor_room=doctor["room"],
            slot_id=slot["id"],
            date=slot["slot_date"],
            time=slot["slot_time"],
            time_display=format_time_12h(slot["slot_time"]),
            caller_phone=caller_phone,
            caller_phone_display=format_phone_display(caller_phone),
            patient_name=patient_name,
            reason=reason,
            status=AppointmentStatus.CONFIRMED,
            booked_via_call_id=fk_call_id,
            created_at=now_iso,
            cancelled_at=None,
        )
        return appointment, updated_slot

    def cancel_appointment_atomic(
        self,
        *,
        caller_phone: str,
        doctor_name: str | None = None,
        reference_code: str | None = None,
        call_id: str | None = None,
    ) -> tuple[AppointmentDTO, SlotDTO]:
        """Atomically cancel an active appointment, disambiguating when a caller holds multiple."""
        with self._db.write_transaction() as conn:
            sql = """
                SELECT
                    a.id,
                    a.reference_code,
                    a.doctor_id,
                    d.name AS doctor_name,
                    d.specialty AS doctor_specialty,
                    d.room AS doctor_room,
                    a.slot_id,
                    s.slot_date,
                    s.slot_time,
                    a.caller_phone,
                    a.patient_name,
                    a.reason,
                    a.booked_via_call_id,
                    a.created_at
                FROM appointments a
                JOIN doctors d ON d.id = a.doctor_id
                JOIN slots s ON s.id = a.slot_id
                WHERE a.caller_phone = ? AND a.status = 'confirmed'
            """
            params: list[Any] = [caller_phone]
            if reference_code:
                sql += " AND UPPER(a.reference_code) = UPPER(?)"
                params.append(reference_code.strip())
            if doctor_name:
                sql += " AND LOWER(d.name) LIKE ?"
                params.append(f"%{doctor_name.strip().lower()}%")
            sql += " ORDER BY s.slot_date ASC, s.slot_time ASC"

            rows = conn.execute(sql, params).fetchall()
            if len(rows) == 0:
                raise AppointmentNotFoundError(
                    f"No active appointment was found for phone number {format_phone_display(caller_phone)}."
                )

            if len(rows) > 1 and not reference_code:
                choices = [
                    f"{r['doctor_name']} on {r['slot_date']} at {format_time_12h(r['slot_time'])} (Ref {r['reference_code']})"
                    for r in rows
                ]
                raise AmbiguousCancellationError(
                    f"Multiple active appointments found for {format_phone_display(caller_phone)}: "
                    f"{'; '.join(choices)}. Please ask the caller which doctor or time they want to cancel.",
                    details={"appointments": choices},
                )

            row = rows[0]
            now_iso = datetime.now(timezone.utc).isoformat()
            cursor = conn.execute(
                """
                UPDATE appointments
                SET status = 'cancelled', cancelled_at = ?, updated_at = ?
                WHERE id = ? AND status = 'confirmed'
                """,
                (now_iso, now_iso, row["id"]),
            )
            if cursor.rowcount != 1:
                raise AppointmentNotFoundError("That appointment has already been cancelled.")

            conn.execute("UPDATE slots SET is_booked = 0 WHERE id = ?", (row["slot_id"],))
            conn.execute(
                """
                INSERT INTO appointment_audit_log (appointment_id, reference_code, action, caller_phone, call_id, created_at)
                VALUES (?, ?, 'cancelled', ?, ?, ?)
                """,
                (row["id"], row["reference_code"], row["caller_phone"], call_id, now_iso),
            )

        freed_slot = SlotDTO(
            id=row["slot_id"],
            doctor_id=row["doctor_id"],
            date=row["slot_date"],
            time=row["slot_time"],
            time_display=format_time_12h(row["slot_time"]),
            is_booked=False,
        )
        cancelled = AppointmentDTO(
            id=row["id"],
            reference_code=row["reference_code"],
            doctor_id=row["doctor_id"],
            doctor_name=row["doctor_name"],
            doctor_specialty=row["doctor_specialty"],
            doctor_room=row["doctor_room"],
            slot_id=row["slot_id"],
            date=row["slot_date"],
            time=row["slot_time"],
            time_display=format_time_12h(row["slot_time"]),
            caller_phone=row["caller_phone"],
            caller_phone_display=format_phone_display(row["caller_phone"]),
            patient_name=row["patient_name"],
            reason=row["reason"],
            status=AppointmentStatus.CANCELLED,
            booked_via_call_id=row["booked_via_call_id"],
            created_at=row["created_at"],
            cancelled_at=now_iso,
        )
        return cancelled, freed_slot

    def upsert_call_session(self, summary: CallSessionSummary) -> None:
        with self._db.write_transaction() as conn:
            conn.execute(
                """
                INSERT INTO call_sessions
                    (call_id, state, caller_phone, phone_confirmed, turns_count, tool_calls_count, avg_llm_ttft_ms, outcome, created_at, connected_at, ended_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(call_id) DO UPDATE SET
                    state = excluded.state,
                    caller_phone = excluded.caller_phone,
                    phone_confirmed = excluded.phone_confirmed,
                    turns_count = excluded.turns_count,
                    tool_calls_count = excluded.tool_calls_count,
                    avg_llm_ttft_ms = excluded.avg_llm_ttft_ms,
                    outcome = excluded.outcome,
                    connected_at = excluded.connected_at,
                    ended_at = excluded.ended_at
                """,
                (
                    summary.call_id,
                    summary.state.value,
                    summary.caller_phone,
                    1 if summary.phone_confirmed else 0,
                    summary.turns_count,
                    summary.tool_calls_count,
                    summary.avg_llm_ttft_ms,
                    summary.outcome,
                    summary.created_at,
                    summary.connected_at,
                    summary.ended_at,
                ),
            )

    def list_call_sessions(self, *, limit: int = 50) -> list[CallSessionSummary]:
        with self._db.read_connection() as conn:
            rows = conn.execute(
                """
                SELECT call_id, state, caller_phone, phone_confirmed, turns_count, tool_calls_count, avg_llm_ttft_ms, outcome, created_at, connected_at, ended_at
                FROM call_sessions
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [
            CallSessionSummary(
                call_id=r["call_id"],
                state=CallLifecycleState(r["state"]),
                caller_phone=r["caller_phone"],
                phone_confirmed=bool(r["phone_confirmed"]),
                turns_count=r["turns_count"],
                tool_calls_count=r["tool_calls_count"],
                avg_llm_ttft_ms=r["avg_llm_ttft_ms"],
                outcome=r["outcome"],
                created_at=r["created_at"],
                connected_at=r["connected_at"],
                ended_at=r["ended_at"],
            )
            for r in rows
        ]

    def append_transcript_entry(
        self,
        *,
        call_id: str,
        role: str,
        text: str,
        latency_ms: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TranscriptEntryDTO:
        now_iso = datetime.now(timezone.utc).isoformat()
        meta = metadata or {}
        with self._db.write_transaction() as conn:
            # Ensure call_session row exists for FK integrity
            conn.execute(
                """
                INSERT OR IGNORE INTO call_sessions (call_id, state, created_at)
                VALUES (?, 'connected', ?)
                """,
                (call_id, now_iso),
            )
            cur = conn.execute(
                """
                INSERT INTO call_transcripts (call_id, role, text, latency_ms, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (call_id, role, text, latency_ms, json.dumps(meta), now_iso),
            )
            entry_id = int(cur.lastrowid or 0)

        return TranscriptEntryDTO(
            id=entry_id,
            call_id=call_id,
            role=role,  # type: ignore[arg-type]
            text=text,
            latency_ms=latency_ms,
            metadata=meta,
            created_at=now_iso,
        )

    def list_call_transcript(self, call_id: str) -> list[TranscriptEntryDTO]:
        with self._db.read_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, call_id, role, text, latency_ms, metadata_json, created_at
                FROM call_transcripts
                WHERE call_id = ?
                ORDER BY id ASC
                """,
                (call_id,),
            ).fetchall()

        return [
            TranscriptEntryDTO(
                id=r["id"],
                call_id=r["call_id"],
                role=r["role"],
                text=r["text"],
                latency_ms=r["latency_ms"],
                metadata=json.loads(r["metadata_json"] or "{}"),
                created_at=r["created_at"],
            )
            for r in rows
        ]
