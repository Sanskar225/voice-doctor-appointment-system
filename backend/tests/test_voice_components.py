"""Unit tests for Pipecat voice pipeline components, tool dispatcher, and barge-in observer."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from pipecat.frames.frames import (
    EndFrame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMTextFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineWorker
from pipecat.services.elevenlabs.stt import CommitStrategy, ElevenLabsRealtimeSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.google.llm import GoogleLLMService
from pipecat.transcriptions.language import Language
from pipecat.workers.runner import WorkerRunner

from app.infrastructure.database import DatabaseManager
from app.infrastructure.event_bus import EventBus
from app.infrastructure.repositories import ClinicRepository
from app.services.appointment_service import AppointmentService
from app.voice.observers import AssistantSpeechObserver
from app.voice.session import CallSession
from app.voice.tools import ClinicToolDispatcher, build_tools_schema


class _FakeFunctionCallParams:
    def __init__(self, arguments: dict[str, Any]) -> None:
        self.arguments = arguments
        self.result: Any = None

    async def result_callback(self, result: Any) -> None:
        self.result = result


def test_pipecat_service_settings_instantiate_cleanly() -> None:
    stt = ElevenLabsRealtimeSTTService(
        api_key="test-key",
        commit_strategy=CommitStrategy.MANUAL,
        sample_rate=16000,
        settings=ElevenLabsRealtimeSTTService.Settings(
            model="scribe_v2_realtime",
            language=Language.EN,
            keyterms=["Aurelia", "Aarav Mehta"],
            no_verbatim=True,
            filter_background_audio=True,
        ),
    )
    llm = GoogleLLMService(
        api_key="test-key",
        settings=GoogleLLMService.Settings(
            model="gemini-2.5-flash",
            temperature=0.35,
            thinking=GoogleLLMService.ThinkingConfig(thinking_budget=0),
        ),
    )
    tts = ElevenLabsTTSService(
        api_key="test-key",
        sample_rate=16000,
        settings=ElevenLabsTTSService.Settings(
            voice="21m00Tcm4TlvDq8ikWAM",
            model="eleven_flash_v2_5",
            stability=0.55,
            similarity_boost=0.78,
            speed=1.02,
            apply_text_normalization="on",
        ),
    )
    tools = build_tools_schema()
    assert stt is not None and llm is not None and tts is not None
    assert len(tools.standard_tools) == 3


def test_tool_dispatcher_enforces_readback_state_machine_and_emits_verified(tmp_path: Path) -> None:
    db = DatabaseManager(tmp_path / "tools.db")
    db.initialize(force_reset=True)
    bus = EventBus()
    service = AppointmentService(db=db, repository=ClinicRepository(db), event_bus=bus)
    session = CallSession(call_id="call-tooltest")
    dispatcher = ClinicToolDispatcher(service=service, event_bus=bus, session=session)

    async def scenario() -> None:
        call_sub = bus.subscribe(call_id="call-tooltest")

        # Turn 1: Caller speaks number, LLM tries booking immediately WITHOUT reading back
        session.readback_tracker.observe_caller_turn()
        eager = _FakeFunctionCallParams(
            {
                "caller_phone": "9876501234",
                "doctor_name": "Dr. Aarav Mehta",
                "slot_date": "today",
                "slot_time": "2:00 PM",
                "phone_confirmed_by_caller": True,
            }
        )
        await dispatcher._handle_book_appointment(eager)
        assert eager.result["success"] is False
        assert eager.result["code"] == "PHONE_CONFIRMATION_REQUIRED"

        # Turn 2: Maya reads back the phone number, then caller confirms
        session.readback_tracker.observe_assistant_speech(
            "Let me confirm your phone number: 987-650-1234. Is that right?"
        )
        session.readback_tracker.observe_caller_turn()

        confirmed = _FakeFunctionCallParams(
            {
                "caller_phone": "9876501234",
                "doctor_name": "Dr. Aarav Mehta",
                "slot_date": "today",
                "slot_time": "2:00 PM",
                "phone_confirmed_by_caller": True,
            }
        )
        await dispatcher._handle_book_appointment(confirmed)
        assert confirmed.result["success"] is True
        assert session.phone_confirmed is True
        assert session.caller_phone == "9876501234"

        seen_types: list[str] = []
        while not call_sub.queue.empty():
            seen_types.append(call_sub.queue.get_nowait().type)
        assert "call.booking_confirmed" in seen_types
        assert "call.phone_verified" in seen_types

    asyncio.run(scenario())


def test_assistant_observer_flushes_cleanly_on_interruption() -> None:
    bus = EventBus()
    session = CallSession(call_id="call-bargein")
    observer = AssistantSpeechObserver(session=session, event_bus=bus)

    async def scenario() -> None:
        sub = bus.subscribe(call_id="call-bargein")
        worker = PipelineWorker(Pipeline([observer]), conversation_id="call-bargein")
        runner = WorkerRunner(handle_sigint=False)
        await runner.add_workers(worker)

        async def feed() -> None:
            await asyncio.sleep(0.05)
            await worker.queue_frames([LLMTextFrame(text="Sure, Dr. Mehta is ")])
            await asyncio.sleep(0.03)
            await worker.queue_frames([InterruptionFrame()])
            await asyncio.sleep(0.03)
            await worker.queue_frames(
                [
                    LLMTextFrame(text="Okay, checking tomorrow instead."),
                    LLMFullResponseEndFrame(),
                    EndFrame(),
                ]
            )

        await asyncio.gather(runner.run(), feed())

        transcripts = []
        while not sub.queue.empty():
            ev = sub.queue.get_nowait()
            if ev.type == "call.transcript":
                transcripts.append(ev.data)

        assert len(transcripts) == 2
        assert transcripts[0]["interrupted"] is True
        assert transcripts[0]["text"].endswith("…")
        assert transcripts[1]["interrupted"] is False
        assert transcripts[1]["text"] == "Okay, checking tomorrow instead."

    asyncio.run(scenario())
