"""Pipecat FrameProcessor observers for transcripts, read-back state, real latency metrics, and persistence."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from ..domain.ports import EventPublisherPort
from .session import CallSession

if TYPE_CHECKING:
    from ..services.appointment_service import AppointmentService


class UserSpeechObserver(FrameProcessor):
    """Publishes caller STT transcripts, tracks turn latency anchors, and updates read-back state."""

    def __init__(
        self,
        *,
        session: CallSession,
        event_bus: EventPublisherPort,
        service: AppointmentService | None = None,
    ) -> None:
        super().__init__()
        self._session = session
        self._bus = event_bus
        self._service = service
        self._user_speaking = False

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, (UserStartedSpeakingFrame, VADUserStartedSpeakingFrame)):
            if not self._user_speaking:
                self._user_speaking = True
                await self._bus.publish_call_event(
                    self._session.call_id,
                    "call.vad",
                    {"speaker": "user", "speaking": True},
                )
                await self._bus.publish_call_event(
                    self._session.call_id,
                    "call.stage",
                    {"stage": "vad", "detail": "Speech detected"},
                )
                await self._bus.publish_call_event(
                    self._session.call_id,
                    "call.barge_in",
                    {},
                )
        elif isinstance(frame, (UserStoppedSpeakingFrame, VADUserStoppedSpeakingFrame)):
            if self._user_speaking:
                self._user_speaking = False
                await self._bus.publish_call_event(
                    self._session.call_id,
                    "call.vad",
                    {"speaker": "user", "speaking": False},
                )
                await self._bus.publish_call_event(
                    self._session.call_id,
                    "call.stage",
                    {"stage": "stt", "detail": "Transcribing utterance"},
                )
        elif isinstance(frame, TranscriptionFrame):
            text = frame.text.strip()
            if text:
                self._session.turns_count += 1
                self._session.last_user_turn_perf = time.perf_counter()
                self._session.readback_tracker.observe_caller_turn()
                if self._service is not None:
                    await self._service.record_transcript_entry(
                        call_id=self._session.call_id,
                        role="caller",
                        text=text,
                    )
                await self._bus.publish_call_event(
                    self._session.call_id,
                    "call.transcript",
                    {
                        "role": "caller",
                        "text": text,
                        "turn": self._session.turns_count,
                    },
                )
                await self._bus.publish_call_event(
                    self._session.call_id,
                    "call.stage",
                    {"stage": "llm", "detail": "Reasoning with Gemini"},
                )

        await self.push_frame(frame, direction)


class AssistantSpeechObserver(FrameProcessor):
    """Buffers streamed LLM text, measures real TTFT latency, records read-backs, and flushes on barge-in."""

    def __init__(
        self,
        *,
        session: CallSession,
        event_bus: EventPublisherPort,
        service: AppointmentService | None = None,
    ) -> None:
        super().__init__()
        self._session = session
        self._bus = event_bus
        self._service = service
        self._chunks: list[str] = []
        self._current_turn_ttft_ms: int | None = None

    async def _flush_turn(self, *, interrupted: bool = False) -> None:
        text = "".join(self._chunks).strip()
        self._chunks.clear()
        ttft_ms = self._current_turn_ttft_ms
        self._current_turn_ttft_ms = None
        if not text:
            return
        self._session.turns_count += 1
        self._session.readback_tracker.observe_assistant_speech(text)
        final_text = f"{text}…" if interrupted else text
        if self._service is not None:
            await self._service.record_transcript_entry(
                call_id=self._session.call_id,
                role="agent",
                text=final_text,
                latency_ms=ttft_ms,
                metadata={"interrupted": interrupted},
            )
        await self._bus.publish_call_event(
            self._session.call_id,
            "call.transcript",
            {
                "role": "agent",
                "text": final_text,
                "interrupted": interrupted,
                "latency_ms": ttft_ms,
                "turn": self._session.turns_count,
            },
        )

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, InterruptionFrame):
            await self._flush_turn(interrupted=True)
            await self._bus.publish_call_event(
                self._session.call_id,
                "call.barge_in",
                {},
            )
        elif isinstance(frame, LLMFullResponseStartFrame):
            self._current_turn_ttft_ms = None
            await self._bus.publish_call_event(
                self._session.call_id,
                "call.stage",
                {"stage": "llm", "detail": "Generating reply"},
            )
        elif isinstance(frame, LLMTextFrame):
            if not self._chunks and self._session.last_user_turn_perf is not None:
                ttft = round((time.perf_counter() - self._session.last_user_turn_perf) * 1000)
                self._session.last_user_turn_perf = None
                self._current_turn_ttft_ms = ttft
                self._session.record_llm_ttft(ttft)
                await self._bus.publish_call_event(
                    self._session.call_id,
                    "call.metrics",
                    {
                        "llm_ttft_ms": ttft,
                        "avg_llm_ttft_ms": self._session.avg_llm_ttft_ms,
                    },
                )
            self._chunks.append(frame.text)
        elif isinstance(frame, LLMFullResponseEndFrame):
            await self._flush_turn(interrupted=False)
        elif isinstance(frame, BotStartedSpeakingFrame):
            await self._bus.publish_call_event(
                self._session.call_id,
                "call.vad",
                {"speaker": "agent", "speaking": True},
            )
            await self._bus.publish_call_event(
                self._session.call_id,
                "call.stage",
                {"stage": "tts", "detail": "Streaming ElevenLabs audio"},
            )
        elif isinstance(frame, BotStoppedSpeakingFrame):
            await self._bus.publish_call_event(
                self._session.call_id,
                "call.vad",
                {"speaker": "agent", "speaking": False},
            )
            await self._bus.publish_call_event(
                self._session.call_id,
                "call.stage",
                {"stage": "idle", "detail": "Listening"},
            )

        await self.push_frame(frame, direction)
