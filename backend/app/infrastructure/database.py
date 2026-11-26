"""SQLite WAL database manager with versioned schema migrations, constraints, and rolling schedule seeding."""

from __future__ import annotations

import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

SEED_DOCTORS = [
    {
        "id": "doc-mehta",
        "name": "Dr. Aarav Mehta",
        "specialty": "Cardiology",
        "room": "Suite 204",
        "experience_years": 14,
        "initials": "AM",
        "slots": {
            0: ["09:30", "11:00", "14:00", "16:30"],
            1: ["10:00", "11:30", "15:00"],
        },
    },
    {
        "id": "doc-nair",
        "name": "Dr. Meera Nair",
        "specialty": "Dermatology",
        "room": "Suite 112",
        "experience_years": 9,
        "initials": "MN",
        "slots": {
            0: ["10:00", "12:30", "15:00", "17:00"],
            1: ["09:30", "13:00", "16:00"],
        },
    },
    {
        "id": "doc-kapoor",
        "name": "Dr. Rohan Kapoor",
        "specialty": "General Medicine",
        "room": "Suite 101",
        "experience_years": 11,
        "initials": "RK",
        "slots": {
            0: ["09:00", "10:30", "13:30", "15:30", "17:30"],
            1: ["09:00", "11:00", "14:30"],
        },
    },
    {
        "id": "doc-iyer",
        "name": "Dr. Priya Iyer",
        "specialty": "Pediatrics",
        "room": "Suite 305",
        "experience_years": 12,
        "initials": "PI",
        "slots": {
            0: ["10:30", "12:00", "14:30", "16:00"],
            1: ["10:00", "12:00", "15:30"],
        },
    },
    {
        "id": "doc-verma",
        "name": "Dr. Kabir Verma",
        "specialty": "Orthopedics",
        "room": "Suite 218",
        "experience_years": 16,
        "initials": "KV",
        "slots": {
            0: ["11:00", "13:00", "15:00"],
            1: ["09:30", "11:30", "14:00", "16:30"],
        },
    },
]

_MIGRATIONS: list[tuple[int, str, list[str]]] = [
    (
        1,
        "001_core_clinic_schema",
        [
            """
            CREATE TABLE IF NOT EXISTS doctors (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                specialty TEXT NOT NULL,
                room TEXT NOT NULL,
                experience_years INTEGER NOT NULL CHECK (experience_years >= 0),
                initials TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS slots (
                id TEXT PRIMARY KEY,
                doctor_id TEXT NOT NULL REFERENCES doctors(id) ON DELETE CASCADE,
                slot_date TEXT NOT NULL,
                slot_time TEXT NOT NULL,
                is_booked INTEGER NOT NULL DEFAULT 0 CHECK (is_booked IN (0, 1)),
                UNIQUE(doctor_id, slot_date, slot_time)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS call_sessions (
                call_id TEXT PRIMARY KEY,
                state TEXT NOT NULL CHECK (state IN ('created', 'connecting', 'connected', 'ended', 'error')),
                caller_phone TEXT,
                phone_confirmed INTEGER NOT NULL DEFAULT 0 CHECK (phone_confirmed IN (0, 1)),
                turns_count INTEGER NOT NULL DEFAULT 0,
                tool_calls_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                connected_at TEXT,
                ended_at TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS appointments (
                id TEXT PRIMARY KEY,
                reference_code TEXT NOT NULL UNIQUE,
                doctor_id TEXT NOT NULL REFERENCES doctors(id),
                slot_id TEXT NOT NULL REFERENCES slots(id),
                caller_phone TEXT NOT NULL,
                patient_name TEXT NOT NULL DEFAULT 'Phone Caller',
                reason TEXT NOT NULL DEFAULT 'General Consultation',
                status TEXT NOT NULL DEFAULT 'confirmed' CHECK (status IN ('confirmed', 'cancelled')),
                booked_via_call_id TEXT REFERENCES call_sessions(call_id) ON DELETE SET NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                cancelled_at TEXT,
                CHECK (
                    (status = 'confirmed' AND cancelled_at IS NULL)
                    OR (status = 'cancelled' AND cancelled_at IS NOT NULL)
                )
            )
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_active_appointment_per_slot
                ON appointments (slot_id)
                WHERE status = 'confirmed'
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_slots_availability
                ON slots (doctor_id, slot_date, is_booked)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_appointments_caller_status
                ON appointments (caller_phone, status, created_at DESC)
            """,
        ],
    ),
    (
        2,
        "002_appointment_audit_log",
        [
            """
            CREATE TABLE IF NOT EXISTS appointment_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                appointment_id TEXT NOT NULL REFERENCES appointments(id) ON DELETE CASCADE,
                reference_code TEXT NOT NULL,
                action TEXT NOT NULL CHECK (action IN ('booked', 'cancelled')),
                caller_phone TEXT NOT NULL,
                call_id TEXT,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_audit_created
                ON appointment_audit_log (created_at DESC)
            """,
        ],
    ),
    (
        3,
        "003_fde_transcripts_and_config",
        [
            """
            CREATE TABLE IF NOT EXISTS clinic_config (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                clinic_name TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                greeting_tone TEXT NOT NULL CHECK (greeting_tone IN ('warm', 'formal')),
                tts_speed REAL NOT NULL CHECK (tts_speed >= 0.8 AND tts_speed <= 1.2),
                strict_phone_readback INTEGER NOT NULL DEFAULT 1 CHECK (strict_phone_readback IN (0, 1)),
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS call_transcripts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                call_id TEXT NOT NULL REFERENCES call_sessions(call_id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK (role IN ('caller', 'agent', 'tool', 'booking', 'cancellation')),
                text TEXT NOT NULL,
                latency_ms INTEGER,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_transcripts_call_id
                ON call_transcripts (call_id, id ASC)
            """,
            "ALTER TABLE call_sessions ADD COLUMN avg_llm_ttft_ms INTEGER",
            "ALTER TABLE call_sessions ADD COLUMN outcome TEXT",
        ],
    ),
]


class DatabaseManager:
    """Thread-safe SQLite manager with WAL journaling, migrations, and atomic write locks."""

    def __init__(self, db_path: Path, busy_timeout_ms: int = 5000) -> None:
        self._db_path = Path(db_path)
        self._busy_timeout_ms = busy_timeout_ms
        self._write_lock = threading.RLock()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            self._db_path,
            timeout=self._busy_timeout_ms / 1000.0,
            isolation_level=None,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
        return conn

    @contextmanager
    def read_connection(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def write_transaction(self) -> Iterator[sqlite3.Connection]:
        """Acquire a serialized BEGIN IMMEDIATE transaction to eliminate write races."""
        with self._write_lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                yield conn
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()

    def initialize(self, *, force_reset: bool = False) -> None:
        with self.write_transaction() as conn:
            if force_reset:
                conn.execute("DROP TABLE IF EXISTS call_transcripts")
                conn.execute("DROP TABLE IF EXISTS appointment_audit_log")
                conn.execute("DROP TABLE IF EXISTS appointments")
                conn.execute("DROP TABLE IF EXISTS call_sessions")
                conn.execute("DROP TABLE IF EXISTS slots")
                conn.execute("DROP TABLE IF EXISTS doctors")
                conn.execute("DROP TABLE IF EXISTS clinic_config")
                conn.execute("DROP TABLE IF EXISTS schema_migrations")

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                )
                """
            )

            applied = {
                row["version"]
                for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
            }
            now_iso = datetime.now(timezone.utc).isoformat()
            for version, name, statements in _MIGRATIONS:
                if version in applied:
                    continue
                for stmt in statements:
                    conn.execute(stmt)
                conn.execute(
                    "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                    (version, name, now_iso),
                )

            conn.execute(
                """
                INSERT OR IGNORE INTO clinic_config
                    (id, clinic_name, agent_name, greeting_tone, tts_speed, strict_phone_readback, updated_at)
                VALUES (1, 'Aurelia Health', 'Maya', 'warm', 1.02, 1, ?)
                """,
                (now_iso,),
            )

            existing_docs = conn.execute("SELECT COUNT(*) FROM doctors").fetchone()[0]
            if existing_docs == 0:
                self._seed_initial_data_locked(conn)
            else:
                self._ensure_rolling_schedule_locked(conn)

    def _ensure_rolling_schedule_locked(self, conn: sqlite3.Connection) -> None:
        today = date.today()
        day_map = {
            0: today.isoformat(),
            1: (today + timedelta(days=1)).isoformat(),
        }
        for doc in SEED_DOCTORS:
            for day_offset, times in doc["slots"].items():
                slot_date = day_map[day_offset]
                for slot_time in times:
                    slot_id = f"{doc['id']}_{slot_date}_{slot_time.replace(':', '')}"
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO slots (id, doctor_id, slot_date, slot_time, is_booked)
                        VALUES (?, ?, ?, ?, 0)
                        """,
                        (slot_id, doc["id"], slot_date, slot_time),
                    )

    def _seed_initial_data_locked(self, conn: sqlite3.Connection) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        today = date.today()
        day_map = {
            0: today.isoformat(),
            1: (today + timedelta(days=1)).isoformat(),
        }

        for doc in SEED_DOCTORS:
            conn.execute(
                """
                INSERT INTO doctors (id, name, specialty, room, experience_years, initials, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc["id"],
                    doc["name"],
                    doc["specialty"],
                    doc["room"],
                    doc["experience_years"],
                    doc["initials"],
                    now_iso,
                ),
            )
            for day_offset, times in doc["slots"].items():
                slot_date = day_map[day_offset]
                for slot_time in times:
                    slot_id = f"{doc['id']}_{slot_date}_{slot_time.replace(':', '')}"
                    conn.execute(
                        """
                        INSERT INTO slots (id, doctor_id, slot_date, slot_time, is_booked)
                        VALUES (?, ?, ?, ?, 0)
                        """,
                        (slot_id, doc["id"], slot_date, slot_time),
                    )

        seed_bookings = [
            (
                "doc-mehta",
                day_map[0],
                "11:00",
                "9876543210",
                "Ananya Sharma",
                "Annual ECG follow-up",
            ),
            (
                "doc-kapoor",
                day_map[0],
                "10:30",
                "9123456789",
                "Vikram Desai",
                "Seasonal fever checkup",
            ),
        ]
        for doc_id, s_date, s_time, phone, patient, reason in seed_bookings:
            slot_id = f"{doc_id}_{s_date}_{s_time.replace(':', '')}"
            appt_id = str(uuid.uuid4())
            ref_code = f"AH-{uuid.uuid4().hex[:5].upper()}"
            conn.execute("UPDATE slots SET is_booked = 1 WHERE id = ?", (slot_id,))
            conn.execute(
                """
                INSERT INTO appointments
                    (id, reference_code, doctor_id, slot_id, caller_phone, patient_name, reason, status, booked_via_call_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'confirmed', NULL, ?, ?)
                """,
                (appt_id, ref_code, doc_id, slot_id, phone, patient, reason, now_iso, now_iso),
            )
            conn.execute(
                """
                INSERT INTO appointment_audit_log (appointment_id, reference_code, action, caller_phone, call_id, created_at)
                VALUES (?, ?, 'booked', ?, NULL, ?)
                """,
                (appt_id, ref_code, phone, now_iso),
            )
