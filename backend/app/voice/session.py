"""Call session state machine with phone read-back tracker, latency metrics, and SQLite persistence."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..domain.exceptions import CallSessionError
from ..domain.models import CallLifecycleState, CallSessionSummary
from ..domain.policies import PhoneReadbackTracker
from ..domain.ports import ClinicRepositoryPort, EventPublisherPort


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class CallSession:
    """Tracks lifecycle, phone verification state machine, and voice latency metrics for one call."""

    call_id: str
    state: CallLifecycleState = CallLifecycleState.CREATED
    created_at: str = field(default_factory=_now_iso)
    connected_at: str | None = None
    ended_at: str | None = None
    caller_phone: str | None = None
    phone_confirmed: bool = False
    turns_count: int = 0
    tool_calls_count: int = 0
    outcome: str | None = None
    last_user_turn_perf: float | None = None
    llm_ttft_samples_ms: list[int] = field(default_factory=list)
    readback_tracker: PhoneReadbackTracker = field(default_factory=PhoneReadbackTracker)

    @property
    def avg_llm_ttft_ms(self) -> int | None:
        if not self.llm_ttft_samples_ms:
            return None
        return round(sum(self.llm_ttft_samples_ms) / len(self.llm_ttft_samples_ms))

    def record_llm_ttft(self, ms: int) -> None:
        if 0 <= ms <= 30000:
            self.llm_ttft_samples_ms.append(ms)

    def to_summary(self) -> CallSessionSummary:
        return CallSessionSummary(
            call_id=self.call_id,
            state=self.state,
            created_at=self.created_at,
            connected_at=self.connected_at,
            ended_at=self.ended_at,
            caller_phone=self.caller_phone,
            phone_confirmed=self.phone_confirmed,
            turns_count=self.turns_count,
            tool_calls_count=self.tool_calls_count,
            avg_llm_ttft_ms=self.avg_llm_ttft_ms,
            outcome=self.outcome,
        )


class CallSessionManager:
    """Manages active call concurrency, lifecycle transitions, and durable call history."""

    def __init__(
        self,
        *,
        event_bus: EventPublisherPort,
        repository: ClinicRepositoryPort | None = None,
        max_concurrent_calls: int = 10,
    ) -> None:
        self._bus = event_bus
        self._repo = repository
        self._max_concurrent = max_concurrent_calls
        self._sessions: dict[str, CallSession] = {}

    @property
    def active_count(self) -> int:
        return sum(
            1
            for s in self._sessions.values()
            if s.state in (CallLifecycleState.CONNECTING, CallLifecycleState.CONNECTED)
        )

    async def persist(self, session: CallSession) -> None:
        if self._repo is not None:
            await asyncio.to_thread(self._repo.upsert_call_session, session.to_summary())

    async def create_session(self) -> CallSession:
        if self.active_count >= self._max_concurrent:
            raise CallSessionError(
                f"Maximum concurrent calls ({self._max_concurrent}) reached. Please try again shortly.",
                code="MAX_CALLS_REACHED",
                http_status=429,
            )
        call_id = f"call-{uuid.uuid4().hex[:8]}"
        session = CallSession(call_id=call_id)
        self._sessions[call_id] = session
        await self.persist(session)

        if len(self._sessions) > 100:
            ended_ids = [
                cid
                for cid, s in self._sessions.items()
                if s.state in (CallLifecycleState.ENDED, CallLifecycleState.ERROR)
            ]
            for cid in ended_ids[:50]:
                self._sessions.pop(cid, None)
        return session

    async def get_or_create_session(self, call_id: str) -> CallSession:
        session = self._sessions.get(call_id)
        if session is not None:
            return session
        if self.active_count >= self._max_concurrent:
            raise CallSessionError(
                "Maximum concurrent calls reached.",
                code="MAX_CALLS_REACHED",
                http_status=429,
            )
        session = CallSession(call_id=call_id)
        self._sessions[call_id] = session
        await self.persist(session)
        return session

    async def list_sessions(self, *, limit: int = 50) -> list[CallSessionSummary]:
        if self._repo is not None:
            return await asyncio.to_thread(self._repo.list_call_sessions, limit=limit)
        return [s.to_summary() for s in reversed(list(self._sessions.values()))][:limit]

    async def transition(
        self,
        session: CallSession,
        new_state: CallLifecycleState,
        *,
        error_message: str | None = None,
    ) -> None:
        if session.state == new_state:
            return
        session.state = new_state
        if new_state == CallLifecycleState.CONNECTED and session.connected_at is None:
            session.connected_at = _now_iso()
        elif new_state in (CallLifecycleState.ENDED, CallLifecycleState.ERROR):
            session.ended_at = _now_iso()
            if session.outcome is None and session.turns_count > 0:
                session.outcome = "inquiry"

        await self.persist(session)

        await self._bus.publish_call_event(
            session.call_id,
            "call.lifecycle",
            {
                "status": new_state.value,
                "error": error_message,
                "session": session.to_summary().model_dump(mode="json"),
            },
        )
        await self._bus.publish_clinic_event(
            "calls.count_changed",
            {"active_calls": self.active_count},
            bump_version=False,
            call_id=session.call_id,
        )
