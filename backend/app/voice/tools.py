"""Pipecat tool schemas and Pydantic-validated dispatcher with latency metrics and domain guardrails."""

from __future__ import annotations

import logging
import time
from typing import Any

from pydantic import ValidationError

from pipecat.adapters.llm.schemas.function_schema import FunctionSchema
from pipecat.adapters.llm.schemas.tools_schema import ToolsSchema
from pipecat.services.google.llm import GoogleLLMService
from pipecat.services.llm_service import FunctionCallParams

from ..domain.exceptions import DomainError
from ..domain.models import BookAppointmentCommand, CancelAppointmentCommand
from ..domain.ports import EventPublisherPort
from ..services.appointment_service import AppointmentService
from .session import CallSession

logger = logging.getLogger("aurelia.tools")


def build_tools_schema() -> ToolsSchema:
    check_availability = FunctionSchema(
        name="check_doctor_availability",
        description=(
            "Check open appointment slots at the clinic. "
            "Optionally filter by doctor name, medical specialty, and/or date."
        ),
        properties={
            "doctor_name": {
                "type": "string",
                "description": "Optional doctor name or last name, e.g. 'Dr. Aarav Mehta' or 'Mehta'.",
            },
            "specialty": {
                "type": "string",
                "description": "Optional specialty: Cardiology, Dermatology, General Medicine, Pediatrics, or Orthopedics.",
            },
            "slot_date": {
                "type": "string",
                "description": "Optional date: 'today', 'tomorrow', or YYYY-MM-DD.",
            },
        },
        required=[],
    )

    book_appointment = FunctionSchema(
        name="book_appointment",
        description=(
            "Book an open appointment slot for the caller using their spoken phone number. "
            "You MUST read the phone number back aloud and hear the caller confirm it first "
            "(set phone_confirmed_by_caller=true only after confirmation)."
        ),
        properties={
            "caller_phone": {
                "type": "string",
                "description": "Caller's spoken phone number (digits).",
            },
            "doctor_name": {
                "type": "string",
                "description": "Doctor's name, e.g. 'Dr. Aarav Mehta'.",
            },
            "slot_date": {
                "type": "string",
                "description": "Date: 'today', 'tomorrow', or YYYY-MM-DD.",
            },
            "slot_time": {
                "type": "string",
                "description": "Time slot, e.g. '2:00 PM' or '14:00'.",
            },
            "phone_confirmed_by_caller": {
                "type": "boolean",
                "description": "True ONLY after you read the caller's phone number back and they confirmed it.",
            },
            "patient_name": {
                "type": "string",
                "description": "Optional patient name if mentioned.",
            },
            "reason": {
                "type": "string",
                "description": "Optional brief reason for the appointment.",
            },
        },
        required=[
            "caller_phone",
            "doctor_name",
            "slot_date",
            "slot_time",
            "phone_confirmed_by_caller",
        ],
    )

    cancel_appointment = FunctionSchema(
        name="cancel_appointment",
        description=(
            "Cancel an existing confirmed appointment found by the caller's spoken phone number. "
            "You MUST read the phone number back aloud and hear the caller confirm it first "
            "(set phone_confirmed_by_caller=true only after confirmation)."
        ),
        properties={
            "caller_phone": {
                "type": "string",
                "description": "Caller's confirmed spoken phone number.",
            },
            "phone_confirmed_by_caller": {
                "type": "boolean",
                "description": "True ONLY after you read the caller's phone number back and they confirmed it.",
            },
            "doctor_name": {
                "type": "string",
                "description": "Optional doctor name to disambiguate when the caller has multiple appointments.",
            },
            "reference_code": {
                "type": "string",
                "description": "Optional booking reference code, e.g. 'AH-4F8C1'.",
            },
        },
        required=["caller_phone", "phone_confirmed_by_caller"],
    )

    return ToolsSchema(
        standard_tools=[
            check_availability,
            book_appointment,
            cancel_appointment,
        ]
    )


class ClinicToolDispatcher:
    """Registers and executes Pipecat LLM tool handlers with latency tracking and read-back guardrails."""

    def __init__(
        self,
        *,
        service: AppointmentService,
        event_bus: EventPublisherPort,
        session: CallSession,
        strict_phone_readback: bool = True,
        timeout_secs: float = 10.0,
    ) -> None:
        self._service = service
        self._bus = event_bus
        self._session = session
        self._strict_phone_readback = strict_phone_readback
        self._timeout_secs = timeout_secs

    def register_on(self, llm: GoogleLLMService) -> None:
        llm.register_function(
            "check_doctor_availability",
            self._handle_check_availability,
            cancel_on_interruption=True,
            timeout_secs=self._timeout_secs,
        )
        llm.register_function(
            "book_appointment",
            self._handle_book_appointment,
            cancel_on_interruption=False,
            timeout_secs=self._timeout_secs,
        )
        llm.register_function(
            "cancel_appointment",
            self._handle_cancel_appointment,
            cancel_on_interruption=False,
            timeout_secs=self._timeout_secs,
        )

    async def _emit_tool_status(self, tool_name: str, summary: str) -> float:
        self._session.tool_calls_count += 1
        await self._bus.publish_call_event(
            self._session.call_id,
            "call.stage",
            {"stage": "tool", "detail": tool_name},
        )
        await self._bus.publish_call_event(
            self._session.call_id,
            "call.tool",
            {
                "tool": tool_name,
                "summary": summary,
                "count": self._session.tool_calls_count,
            },
        )
        return time.perf_counter()

    async def _record_tool_completion(
        self, tool_name: str, summary: str, started: float
    ) -> None:
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        await self._service.record_transcript_entry(
            call_id=self._session.call_id,
            role="tool",
            text=summary,
            latency_ms=elapsed_ms,
            metadata={"tool": tool_name},
        )
        await self._bus.publish_call_event(
            self._session.call_id,
            "call.metrics",
            {"last_tool": tool_name, "tool_exec_ms": elapsed_ms},
        )

    async def _handle_check_availability(self, params: FunctionCallParams) -> None:
        args: dict[str, Any] = dict(params.arguments or {})
        target = args.get("doctor_name") or args.get("specialty") or "all physicians"
        summary = f"Checking open slots for {target}…"
        started = await self._emit_tool_status("check_doctor_availability", summary)
        try:
            result = await self._service.check_availability(
                doctor_name=args.get("doctor_name"),
                specialty=args.get("specialty"),
                slot_date=args.get("slot_date"),
            )
            await self._record_tool_completion("check_doctor_availability", summary, started)
            await params.result_callback(
                {"success": True, **result.model_dump(mode="json")}
            )
        except DomainError as exc:
            await params.result_callback(
                {"success": False, "code": exc.code, "error": exc.message, **exc.details}
            )
        except Exception as exc:
            logger.exception("Unexpected error in check_doctor_availability")
            await params.result_callback(
                {"success": False, "code": "INTERNAL_ERROR", "error": str(exc)}
            )

    async def _handle_book_appointment(self, params: FunctionCallParams) -> None:
        args: dict[str, Any] = dict(params.arguments or {})
        summary = f"Booking {args.get('doctor_name', 'physician')} at {args.get('slot_time', '')}…"
        started = await self._emit_tool_status("book_appointment", summary)
        try:
            cmd = BookAppointmentCommand.model_validate(args)
            appointment, _slot = await self._service.book_appointment(
                cmd,
                call_id=self._session.call_id,
                readback_tracker=self._session.readback_tracker,
                enforce_readback_tracker=self._strict_phone_readback,
            )
            self._session.caller_phone = appointment.caller_phone
            self._session.phone_confirmed = True
            self._session.outcome = "booked"
            await self._record_tool_completion("book_appointment", summary, started)
            await self._bus.publish_call_event(
                self._session.call_id,
                "call.phone_verified",
                {
                    "phone": appointment.caller_phone,
                    "phone_display": appointment.caller_phone_display,
                },
            )
            await params.result_callback(
                {
                    "success": True,
                    "appointment": appointment.model_dump(mode="json"),
                }
            )
        except ValidationError as exc:
            await params.result_callback(
                {
                    "success": False,
                    "code": "INVALID_ARGUMENTS",
                    "error": f"Invalid booking parameters: {exc.errors()[0]['msg']}",
                }
            )
        except DomainError as exc:
            await params.result_callback(
                {"success": False, "code": exc.code, "error": exc.message, **exc.details}
            )
        except Exception as exc:
            logger.exception("Unexpected error in book_appointment")
            await params.result_callback(
                {"success": False, "code": "INTERNAL_ERROR", "error": str(exc)}
            )

    async def _handle_cancel_appointment(self, params: FunctionCallParams) -> None:
        args: dict[str, Any] = dict(params.arguments or {})
        summary = "Looking up and cancelling appointment…"
        started = await self._emit_tool_status("cancel_appointment", summary)
        try:
            cmd = CancelAppointmentCommand.model_validate(args)
            cancelled, _slot = await self._service.cancel_appointment(
                cmd,
                call_id=self._session.call_id,
                readback_tracker=self._session.readback_tracker,
                enforce_readback_tracker=self._strict_phone_readback,
            )
            self._session.caller_phone = cancelled.caller_phone
            self._session.phone_confirmed = True
            self._session.outcome = "cancelled"
            await self._record_tool_completion("cancel_appointment", summary, started)
            await self._bus.publish_call_event(
                self._session.call_id,
                "call.phone_verified",
                {
                    "phone": cancelled.caller_phone,
                    "phone_display": cancelled.caller_phone_display,
                },
            )
            await params.result_callback(
                {
                    "success": True,
                    "appointment": cancelled.model_dump(mode="json"),
                }
            )
        except ValidationError as exc:
            await params.result_callback(
                {
                    "success": False,
                    "code": "INVALID_ARGUMENTS",
                    "error": f"Invalid cancellation parameters: {exc.errors()[0]['msg']}",
                }
            )
        except DomainError as exc:
            await params.result_callback(
                {"success": False, "code": exc.code, "error": exc.message, **exc.details}
            )
        except Exception as exc:
            logger.exception("Unexpected error in cancel_appointment")
            await params.result_callback(
                {"success": False, "code": "INTERNAL_ERROR", "error": str(exc)}
            )
