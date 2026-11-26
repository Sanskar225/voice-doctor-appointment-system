"""Scoped async EventBus separating clinic domain events from per-call voice telemetry."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from ..domain.models import EventEnvelope

logger = logging.getLogger("aurelia.events")


@dataclass(eq=False)
class _Subscriber:
    queue: asyncio.Queue[EventEnvelope]
    call_id: str | None


class EventBus:
    """In-memory pub/sub broker with monotonic clinic state versioning and call isolation."""

    def __init__(self, *, max_queue_size: int = 256) -> None:
        self._max_queue_size = max_queue_size
        self._subscribers: set[_Subscriber] = set()
        self._event_seq: int = 0
        self._state_version: int = 1

    @property
    def state_version(self) -> int:
        return self._state_version

    def subscribe(self, *, call_id: str | None = None) -> _Subscriber:
        sub = _Subscriber(
            queue=asyncio.Queue(maxsize=self._max_queue_size),
            call_id=call_id,
        )
        self._subscribers.add(sub)
        return sub

    def unsubscribe(self, sub: _Subscriber) -> None:
        self._subscribers.discard(sub)

    async def publish_clinic_event(
        self,
        event_type: str,
        data: dict[str, Any],
        *,
        bump_version: bool = True,
        call_id: str | None = None,
    ) -> EventEnvelope:
        if bump_version:
            self._state_version += 1
        self._event_seq += 1
        envelope = EventEnvelope(
            id=self._event_seq,
            scope="clinic",
            type=event_type,
            version=self._state_version,
            call_id=call_id,
            data=data,
        )
        self._fan_out(envelope, target_call_id=None)
        return envelope

    async def publish_call_event(
        self,
        call_id: str,
        event_type: str,
        data: dict[str, Any],
    ) -> EventEnvelope:
        self._event_seq += 1
        envelope = EventEnvelope(
            id=self._event_seq,
            scope="call",
            type=event_type,
            version=self._state_version,
            call_id=call_id,
            data=data,
        )
        self._fan_out(envelope, target_call_id=call_id)
        return envelope

    def _fan_out(self, envelope: EventEnvelope, *, target_call_id: str | None) -> None:
        dropped = 0
        for sub in list(self._subscribers):
            if target_call_id is None:
                if sub.call_id is not None:
                    continue
            else:
                if sub.call_id != target_call_id:
                    continue

            if sub.queue.full():
                try:
                    sub.queue.get_nowait()
                    dropped += 1
                except asyncio.QueueEmpty:
                    pass
            try:
                sub.queue.put_nowait(envelope)
            except asyncio.QueueFull:
                dropped += 1

        if dropped:
            logger.warning("Dropped %d event(s) for slow SSE consumer(s)", dropped)
