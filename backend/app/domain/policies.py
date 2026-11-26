"""Deterministic domain policies enforcing voice-call business rules beyond prompt hints."""

from __future__ import annotations

from dataclasses import dataclass, field

from .exceptions import PhoneConfirmationRequiredError
from .value_objects import PhoneNumber, extract_phone_candidates_from_speech


@dataclass
class PhoneReadbackTracker:
    """State-machine guard proving the assistant read a phone number back and heard a reply.

    Prevents an eager LLM from hallucinating `phone_confirmed_by_caller=true` on the same
    turn the caller first gave their number without reading it back aloud first.
    """

    readback_turn_by_phone: dict[str, int] = field(default_factory=dict)
    confirmed_phones: set[str] = field(default_factory=set)
    caller_turn_seq: int = 0

    def observe_assistant_speech(self, text: str) -> set[str]:
        """Extract any phone numbers Maya read aloud and record the current caller turn."""
        found = extract_phone_candidates_from_speech(text)
        for digits in found:
            self.readback_turn_by_phone[digits] = self.caller_turn_seq
        return found

    def observe_caller_turn(self) -> None:
        """Advance caller turn counter; any phone read back before this reply is now confirmable."""
        self.caller_turn_seq += 1
        for digits, readback_at in list(self.readback_turn_by_phone.items()):
            if self.caller_turn_seq > readback_at:
                self.confirmed_phones.add(digits)

    def assert_verified_for_mutation(
        self,
        phone: PhoneNumber,
        *,
        llm_claimed_confirmed: bool,
        action_label: str,
    ) -> None:
        if not llm_claimed_confirmed:
            raise PhoneConfirmationRequiredError(
                f"Read the caller's phone number ({phone.display}) back aloud and wait for their confirmation before {action_label}."
            )
        if phone.digits not in self.confirmed_phones:
            raise PhoneConfirmationRequiredError(
                f"Blocked {action_label}: you have not read {phone.display} back to the caller and received their confirmation yet. "
                f"Speak {phone.display} back clearly first, wait for them to confirm, then call the tool again."
            )
