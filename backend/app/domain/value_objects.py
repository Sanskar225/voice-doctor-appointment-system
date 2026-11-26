"""Pure domain value objects for phone numbers and clinic schedule parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .exceptions import InvalidDateTimeError, InvalidPhoneError

_WORD_DIGITS: dict[str, str] = {
    "zero": "0",
    "oh": "0",
    "o": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
}


_DIGIT_CONNECTORS: frozenset[str] = frozenset({"dash", "hyphen", "space"})


def _extract_spoken_digit_runs(text: str) -> list[str]:
    """Extract contiguous digit runs from text containing numeric digits or English digit words."""
    tokens = re.findall(r"[a-zA-Z]+|\d+", (text or "").lower())
    runs: list[str] = []
    current: list[str] = []
    multiplier = 1

    for tok in tokens:
        if tok == "double":
            multiplier = 2
            continue
        if tok == "triple":
            multiplier = 3
            continue
        if tok in _DIGIT_CONNECTORS and current:
            continue
        if tok.isdigit():
            current.append(tok * multiplier)
            multiplier = 1
        elif tok in _WORD_DIGITS:
            current.append(_WORD_DIGITS[tok] * multiplier)
            multiplier = 1
        else:
            multiplier = 1
            if current:
                runs.append("".join(current))
                current = []

    if current:
        runs.append("".join(current))
    return runs


def strip_country_prefix(digits: str) -> str:
    if len(digits) == 12 and digits.startswith("91"):
        return digits[2:]
    if len(digits) == 11 and digits.startswith("1"):
        return digits[1:]
    return digits


def extract_phone_candidates_from_speech(utterance: str) -> set[str]:
    """Find normalized candidate phone numbers spoken in a transcript sentence (e.g. agent read-back)."""
    text = utterance or ""
    candidates: set[str] = set()

    # Strategy 1: contiguous runs of digits / spoken digit words (with dash/hyphen connectors)
    for run in _extract_spoken_digit_runs(text):
        normalized = strip_country_prefix(run)
        if 7 <= len(normalized) <= 15:
            candidates.add(normalized)

    # Strategy 2: formatted numeric phone spans (safe even when sentence also contains a time like "2:00 PM")
    for match in re.finditer(r"\+?\d[\d\s\-.,/()]{6,20}\d", text):
        span_digits = strip_country_prefix(re.sub(r"\D", "", match.group(0)))
        if 7 <= len(span_digits) <= 15:
            candidates.add(span_digits)

    # Strategy 3: fallback when the whole sentence contains only one phone number's worth of digits
    only_digits = strip_country_prefix(re.sub(r"\D", "", text))
    if 7 <= len(only_digits) <= 15:
        candidates.add(only_digits)

    return candidates


@dataclass(frozen=True)
class PhoneNumber:
    """Validated canonical caller phone number (digits only)."""

    digits: str

    @classmethod
    def parse(cls, raw: str) -> "PhoneNumber":
        text = (raw or "").strip()
        digits = re.sub(r"\D", "", text)
        if len(digits) < 7 and re.search(r"[a-zA-Z]", text):
            runs = _extract_spoken_digit_runs(text)
            digits = "".join(runs)
        digits = strip_country_prefix(digits)
        if len(digits) < 7 or len(digits) > 15:
            raise InvalidPhoneError(
                "Phone number must contain between 7 and 15 digits. Please ask the caller to repeat it."
            )
        return cls(digits=digits)

    @property
    def display(self) -> str:
        if len(self.digits) == 10:
            return f"{self.digits[:3]}-{self.digits[3:6]}-{self.digits[6:]}"
        return self.digits

    def __str__(self) -> str:
        return self.digits


def format_phone_display(digits: str) -> str:
    clean = strip_country_prefix(re.sub(r"\D", "", digits or ""))
    if len(clean) == 10:
        return f"{clean[:3]}-{clean[3:6]}-{clean[6:]}"
    return clean or digits


def parse_schedule_date(raw_date: str | None, *, reference_today: date | None = None) -> str | None:
    if not raw_date:
        return None
    cleaned = raw_date.strip().lower()
    today = reference_today or date.today()
    if cleaned in ("today", "now"):
        return today.isoformat()
    if cleaned == "tomorrow":
        return (today + timedelta(days=1)).isoformat()
    try:
        return date.fromisoformat(cleaned).isoformat()
    except ValueError as exc:
        raise InvalidDateTimeError(
            f"Could not parse date '{raw_date}'. Use 'today', 'tomorrow', or YYYY-MM-DD."
        ) from exc


def parse_schedule_time(raw_time: str) -> str:
    cleaned = (raw_time or "").strip().upper().replace(".", "")
    for fmt in ("%H:%M", "%I:%M %p", "%I:%M%p", "%I %p", "%I%p"):
        try:
            return datetime.strptime(cleaned, fmt).strftime("%H:%M")
        except ValueError:
            continue
    raise InvalidDateTimeError(
        f"Could not parse time '{raw_time}'. Use a format like '2:00 PM' or '14:00'."
    )


def format_time_12h(slot_time: str) -> str:
    try:
        return datetime.strptime(slot_time, "%H:%M").strftime("%I:%M %p").lstrip("0")
    except ValueError:
        return slot_time
