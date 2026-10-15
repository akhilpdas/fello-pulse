"""Outbound dispatch interface (T064). Production would plug in a real email
provider behind the same ``Transport`` protocol; this deliverable's tests --
and its demo -- use ``RecordingTransport``, which never makes a network call
and keeps every attempt in memory for assertions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class SendResult:
    ok: bool
    error: str | None = None


class Transport(Protocol):
    def send(self, *, to: str, subject: str, body: str) -> SendResult: ...


def send_with_retry(
    transport: Transport, *, to: str, subject: str, body: str, max_attempts: int = 3,
) -> tuple[SendResult, int]:
    """Bounded retry for a human-triggered send (T076): try up to
    ``max_attempts`` times, stop on the first success, and return the final
    result plus how many attempts it took -- the caller surfaces a final
    failure rather than swallowing it."""
    attempts = 0
    result = SendResult(False, "never attempted")
    for _ in range(max_attempts):
        attempts += 1
        result = transport.send(to=to, subject=subject, body=body)
        if result.ok:
            break
    return result, attempts


@dataclass
class RecordingTransport:
    sent: list[dict] = field(default_factory=list)
    # Test hook: the next N calls fail before sends succeed again --
    # exercises T076's bounded retry without a real flaky network.
    fail_next: int = 0

    def send(self, *, to: str, subject: str, body: str) -> SendResult:
        if self.fail_next > 0:
            self.fail_next -= 1
            return SendResult(False, "simulated_transport_failure")
        self.sent.append({"to": to, "subject": subject, "body": body})
        return SendResult(True, None)
