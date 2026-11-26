"""Pipecat real-time voice pipeline factory driven dynamically by live FDE clinic configuration."""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from datetime import date, timedelta
from typing import Any

import aiohttp
from fastapi import WebSocket
from google import genai

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.services.elevenlabs.stt import (
    CommitStrategy,
    ElevenLabsRealtimeSTTService,
    ElevenLabsSTTService,
)
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.google.llm import GoogleLLMService
from pipecat.transcriptions.language import Language
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)
from pipecat.workers.runner import WorkerRunner

from ..config import Settings
from ..domain.models import CallLifecycleState, ClinicConfigDTO, DoctorDTO
from ..infrastructure.event_bus import EventBus
from ..logging_config import call_id_ctx
from ..services.appointment_service import AppointmentService
from .observers import AssistantSpeechObserver, UserSpeechObserver
from .serializer import RawPCMFrameSerializer
from .session import CallSession, CallSessionManager
from .tools import ClinicToolDispatcher, build_tools_schema

logger = logging.getLogger("aurelia.pipeline")


class GeminiExpressAwareLLMService(GoogleLLMService):
    """Supports both Google AI Studio (AIza...) and Vertex AI Express Mode (AQ....) keys."""

    def create_client(self) -> None:
        if self._api_key and self._api_key.startswith("AQ."):
            self._client = genai.Client(vertexai=True, api_key=self._api_key)
        else:
            super().create_client()


def _build_stt_keyterms(doctors: list[DoctorDTO], config: ClinicConfigDTO) -> list[str]:
    terms: list[str] = [config.clinic_name, config.agent_name]
    seen: set[str] = set(terms)
    for d in doctors:
        for candidate in (d.name.replace("Dr. ", ""), d.specialty):
            if candidate not in seen:
                seen.add(candidate)
                terms.append(candidate)
    return terms


def _build_system_prompt(doctors: list[DoctorDTO], config: ClinicConfigDTO) -> str:
    today = date.today()
    today_iso = today.isoformat()
    tomorrow_iso = (today + timedelta(days=1)).isoformat()
    doctor_lines = "\n".join(
        f"- {d.name} ({d.specialty}, {d.room})" for d in doctors
    )
    tone_guidance = (
        "Speak warmly, empathetically, and conversationally — like a friendly neighborhood clinic receptionist."
        if config.greeting_tone == "warm"
        else "Speak politely, crisply, and formally — like an executive hospital concierge."
    )

    return f"""You are {config.agent_name}, the front-desk voice receptionist for {config.clinic_name}.
Today is {today_iso}. Tomorrow is {tomorrow_iso}.

Physicians on duty at {config.clinic_name}:
{doctor_lines}

You help callers over a live phone call to:
1. Check doctor availability (`check_doctor_availability`)
2. Book an appointment (`book_appointment`)
3. Cancel an existing appointment (`cancel_appointment`)

STRICT CONVERSATION RULES:
- {tone_guidance} Keep replies to 1 to 3 short spoken sentences. Never output markdown, lists, asterisks, or emojis.
- If a caller describes a symptom (e.g. skin rash, heart checkup, fever, knee pain, child checkup), recommend the matching specialist automatically and check their open slots.
- Callers are identified ONLY by the phone number they say out loud. No login, no OTP, no caller ID.
- MANDATORY PHONE CONFIRMATION RULE: Before calling `book_appointment` or `cancel_appointment`, you MUST read the caller's phone number back clearly in short groups (e.g., "9-8-7, 6-5-4, 3-2-1-0") and wait for them to explicitly confirm it is right. Only set `phone_confirmed_by_caller=true` AFTER they confirm.
- When offering slots, share 2 to 4 convenient times in natural 12-hour format (e.g., "9:30 AM, 2:00 PM, or 4:30 PM").
- Support multiple requests (checking, booking, cancelling) seamlessly within one phone call.
- After booking, state the doctor's name, day, time, and reference code clearly. After cancelling, confirm the slot has been released.
"""


async def run_voice_session(
    *,
    websocket: WebSocket,
    session: CallSession,
    settings: Settings,
    service: AppointmentService,
    event_bus: EventBus,
    session_manager: CallSessionManager,
) -> None:
    """Attach an accepted WebSocket connection to an isolated, dynamically configured Pipecat pipeline."""
    token = call_id_ctx.set(session.call_id)
    try:
        if not settings.voice_ready:
            err_msg = f"Missing required environment variables: {', '.join(settings.missing_voice_keys)}"
            logger.error(err_msg)
            await session_manager.transition(
                session,
                CallLifecycleState.ERROR,
                error_message=err_msg,
            )
            await websocket.close(code=1011, reason=err_msg)
            return

        await session_manager.transition(session, CallLifecycleState.CONNECTING)
        config = await service.get_config()
        doctors = await service.get_doctors()
        sample_rate = settings.audio_sample_rate
        keyterms = _build_stt_keyterms(doctors, config)

        async with AsyncExitStack() as stack:
            serializer = RawPCMFrameSerializer(sample_rate=sample_rate)
            transport = FastAPIWebsocketTransport(
                websocket=websocket,
                params=FastAPIWebsocketParams(
                    audio_in_enabled=True,
                    audio_out_enabled=True,
                    audio_in_sample_rate=sample_rate,
                    audio_out_sample_rate=sample_rate,
                    add_wav_header=False,
                    session_timeout=settings.call_session_timeout_secs,
                    serializer=serializer,
                ),
            )

            if settings.elevenlabs_stt_mode == "segmented":
                http_session = await stack.enter_async_context(aiohttp.ClientSession())
                stt: Any = ElevenLabsSTTService(
                    api_key=settings.elevenlabs_api_key,
                    aiohttp_session=http_session,
                    sample_rate=sample_rate,
                    settings=ElevenLabsSTTService.Settings(
                        model="scribe_v2",
                        language=Language.EN,
                        keyterms=keyterms,
                        no_verbatim=True,
                    ),
                )
            else:
                stt = ElevenLabsRealtimeSTTService(
                    api_key=settings.elevenlabs_api_key,
                    commit_strategy=CommitStrategy.MANUAL,
                    sample_rate=sample_rate,
                    settings=ElevenLabsRealtimeSTTService.Settings(
                        model="scribe_v2_realtime",
                        language=Language.EN,
                        keyterms=keyterms,
                        no_verbatim=True,
                        filter_background_audio=True,
                    ),
                )

            llm = GeminiExpressAwareLLMService(
                api_key=settings.gemini_api_key,
                settings=GoogleLLMService.Settings(
                    model=settings.gemini_model,
                    system_instruction=_build_system_prompt(doctors, config),
                    temperature=0.35,
                    thinking=GoogleLLMService.ThinkingConfig(thinking_budget=0),
                ),
            )

            tts = ElevenLabsTTSService(
                api_key=settings.elevenlabs_api_key,
                sample_rate=sample_rate,
                settings=ElevenLabsTTSService.Settings(
                    voice=settings.elevenlabs_voice_id,
                    model=settings.elevenlabs_tts_model,
                    stability=0.55,
                    similarity_boost=0.78,
                    speed=config.tts_speed,
                    apply_text_normalization="on",
                ),
            )

            dispatcher = ClinicToolDispatcher(
                service=service,
                event_bus=event_bus,
                session=session,
                strict_phone_readback=config.strict_phone_readback,
                timeout_secs=settings.tool_timeout_secs,
            )
            dispatcher.register_on(llm)

            context = LLMContext(
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"The caller just connected. Greet them briefly as {config.agent_name} "
                            f"from {config.clinic_name} and ask how you can help."
                        ),
                    },
                ],
                tools=build_tools_schema(),
            )
            context_aggregator = LLMContextAggregatorPair(
                context,
                user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
            )

            user_observer = UserSpeechObserver(
                session=session, event_bus=event_bus, service=service
            )
            assistant_observer = AssistantSpeechObserver(
                session=session, event_bus=event_bus, service=service
            )

            pipeline = Pipeline(
                [
                    transport.input(),
                    stt,
                    user_observer,
                    context_aggregator.user(),
                    llm,
                    assistant_observer,
                    tts,
                    transport.output(),
                    context_aggregator.assistant(),
                ]
            )

            worker = PipelineWorker(
                pipeline,
                conversation_id=session.call_id,
                params=PipelineParams(
                    audio_in_sample_rate=sample_rate,
                    audio_out_sample_rate=sample_rate,
                    allow_interruptions=True,
                    enable_metrics=True,
                ),
            )

            @transport.event_handler("on_client_connected")
            async def on_client_connected(_transport: Any, _ws: Any) -> None:
                logger.info(
                    "Voice pipeline connected (clinic=%s, agent=%s, stt=%s, llm=%s, tts=%s)",
                    config.clinic_name,
                    config.agent_name,
                    settings.elevenlabs_stt_mode,
                    settings.gemini_model,
                    settings.elevenlabs_tts_model,
                )
                await session_manager.transition(session, CallLifecycleState.CONNECTED)
                await worker.queue_frames([LLMRunFrame()])

            @transport.event_handler("on_client_disconnected")
            async def on_client_disconnected(_transport: Any, _ws: Any) -> None:
                logger.info("Voice client disconnected")
                await worker.cancel()

            @transport.event_handler("on_session_timeout")
            async def on_session_timeout(_transport: Any, _ws: Any) -> None:
                logger.warning("Voice session timed out due to inactivity")
                await worker.cancel()

            runner = WorkerRunner(handle_sigint=False)
            await runner.add_workers(worker)
            await runner.run()
    except Exception as exc:
        logger.exception("Voice pipeline failed")
        await session_manager.transition(
            session,
            CallLifecycleState.ERROR,
            error_message=str(exc),
        )
    finally:
        if session.state != CallLifecycleState.ERROR:
            await session_manager.transition(session, CallLifecycleState.ENDED)
        call_id_ctx.reset(token)
