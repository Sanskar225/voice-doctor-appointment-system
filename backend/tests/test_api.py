"""FastAPI integration tests covering versioned clinic, audit, call provisioning, and error codes."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def _make_client(tmp_path: Path) -> TestClient:
    app = create_app(Settings(db_path=tmp_path / "api_test.db"))
    return TestClient(app)


def test_snapshot_booking_conflict_audit_calls_and_cancel_flow(tmp_path: Path) -> None:
    with _make_client(tmp_path) as client:
        health = client.get("/api/v1/health")
        assert health.status_code == 200
        assert health.headers.get("X-Request-ID")
        assert health.json()["status"] == "ok"

        snap = client.get("/api/v1/clinic/snapshot")
        assert snap.status_code == 200
        body = snap.json()
        assert len(body["doctors"]) == 5
        assert len(body["appointments"]) == 2
        assert body["version"] == 1
        assert body["today"] and body["tomorrow"]

        # Unconfirmed phone -> 422
        unconfirmed = client.post(
            "/api/v1/appointments",
            json={
                "caller_phone": "9000011111",
                "doctor_name": "Dr. Aarav Mehta",
                "slot_date": "today",
                "slot_time": "2:00 PM",
                "phone_confirmed_by_caller": False,
            },
        )
        assert unconfirmed.status_code == 422
        assert unconfirmed.json()["code"] == "PHONE_CONFIRMATION_REQUIRED"

        # Confirmed booking -> 201
        created = client.post(
            "/api/v1/appointments",
            json={
                "caller_phone": "9000011111",
                "doctor_name": "Dr. Aarav Mehta",
                "slot_date": "today",
                "slot_time": "2:00 PM",
                "patient_name": "Sanskar",
                "phone_confirmed_by_caller": True,
            },
        )
        assert created.status_code == 201
        assert created.json()["status"] == "confirmed"
        assert created.json()["reference_code"].startswith("AH-")

        # Duplicate booking on same slot -> 409 Conflict
        conflict = client.post(
            "/api/v1/appointments",
            json={
                "caller_phone": "9000022222",
                "doctor_name": "Dr. Aarav Mehta",
                "slot_date": "today",
                "slot_time": "2:00 PM",
                "phone_confirmed_by_caller": True,
            },
        )
        assert conflict.status_code == 409
        assert conflict.json()["code"] == "SLOT_ALREADY_BOOKED"

        # Cancel booking -> 200
        cancelled = client.post(
            "/api/v1/appointments/cancel",
            json={
                "caller_phone": "9000011111",
                "phone_confirmed_by_caller": True,
            },
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"

        # Audit log persisted both seeded + booked + cancelled events
        audit = client.get("/api/v1/audit")
        assert audit.status_code == 200
        assert len(audit.json()) >= 4

        # Provision voice call session -> persisted in SQLite call_sessions
        call_res = client.post("/api/v1/calls")
        assert call_res.status_code == 201
        call_data = call_res.json()
        assert call_data["call_id"].startswith("call-")
        assert call_data["ws_path"] == f"/ws/voice/{call_data['call_id']}"
        assert call_data["events_path"] == f"/api/v1/events?call_id={call_data['call_id']}"

        calls_list = client.get("/api/v1/calls")
        assert calls_list.status_code == 200
        assert any(c["call_id"] == call_data["call_id"] for c in calls_list.json())

        # FDE live runtime config update -> persists and reflects in snapshot
        cfg_res = client.patch(
            "/api/v1/config",
            json={
                "clinic_name": "Sunrise Care Clinic",
                "agent_name": "Aria",
                "greeting_tone": "formal",
                "tts_speed": 1.05,
                "strict_phone_readback": True,
            },
        )
        assert cfg_res.status_code == 200
        assert cfg_res.json()["clinic_name"] == "Sunrise Care Clinic"
        assert cfg_res.json()["agent_name"] == "Aria"

        snap2 = client.get("/api/v1/clinic/snapshot").json()
        assert snap2["config"]["clinic_name"] == "Sunrise Care Clinic"

        # Transcript lookup returns persisted entries list (empty for brand-new call)
        tr_res = client.get(f"/api/v1/calls/{call_data['call_id']}/transcript")
        assert tr_res.status_code == 200
        assert tr_res.json() == []


def test_readiness_probe_and_security_headers(tmp_path: Path, monkeypatch) -> None:
    app = create_app(Settings(db_path=tmp_path / "readiness_test.db"))
    with TestClient(app) as client:
        res = client.get("/api/v1/readiness")
        assert res.status_code == 200
        body = res.json()
        assert body["ready"] is True
        assert body["db"] == "ok"
        assert body["version"] == "2.1.0"
        assert res.headers.get("X-Request-ID")
        assert res.headers.get("X-Content-Type-Options") == "nosniff"
        assert res.headers.get("X-Frame-Options") == "DENY"
        assert res.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

        # Simulate DB outage -> readiness probe returns 503 Service Unavailable
        monkeypatch.setattr(app.state.container.db, "ping", lambda: False)
        degraded = client.get("/api/v1/readiness")
        assert degraded.status_code == 503
        assert degraded.json()["ready"] is False
        assert degraded.json()["db"] == "error"
