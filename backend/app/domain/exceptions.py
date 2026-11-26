"""Typed domain exceptions mapped to deterministic HTTP status codes and LLM tool feedback."""

from __future__ import annotations


class DomainError(Exception):
    """Base error for business invariant violations."""

    code: str = "DOMAIN_ERROR"
    http_status: int = 400

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        http_status: int | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
        if code is not None:
            self.code = code
        if http_status is not None:
            self.http_status = http_status


class InvalidPhoneError(DomainError):
    code = "INVALID_PHONE"
    http_status = 422


class PhoneConfirmationRequiredError(DomainError):
    code = "PHONE_CONFIRMATION_REQUIRED"
    http_status = 422


class InvalidDateTimeError(DomainError):
    code = "INVALID_DATETIME"
    http_status = 422


class DoctorNotFoundError(DomainError):
    code = "DOCTOR_NOT_FOUND"
    http_status = 404


class AmbiguousDoctorError(DomainError):
    code = "AMBIGUOUS_DOCTOR"
    http_status = 409


class SlotNotFoundError(DomainError):
    code = "SLOT_NOT_FOUND"
    http_status = 404


class SlotAlreadyBookedError(DomainError):
    code = "SLOT_ALREADY_BOOKED"
    http_status = 409


class OverlappingAppointmentError(DomainError):
    code = "OVERLAPPING_APPOINTMENT"
    http_status = 409


class AppointmentNotFoundError(DomainError):
    code = "APPOINTMENT_NOT_FOUND"
    http_status = 404


class AmbiguousCancellationError(DomainError):
    code = "AMBIGUOUS_CANCELLATION"
    http_status = 409


class CallSessionError(DomainError):
    code = "CALL_SESSION_ERROR"
    http_status = 400
