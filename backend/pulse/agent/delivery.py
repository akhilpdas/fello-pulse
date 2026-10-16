"""Deliver one approved draft -- the single code path for a human approving and for the unattended
cycle auto-sending, so the safety rules cannot differ between them.

Order of decisions: the send gate (FR-014..016), then demo mode (FR-020), then a bounded send whose
outcome is classified (FR-017/018). The caller persists the returned ``Outcome`` onto the action row.
Nothing here ever invents a recipient.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from pulse.agent.transport import RecordingTransport, Transport, send_with_retry
from pulse.domain.send_gate import decide_send

MAX_SEND_ATTEMPTS = 3
# A blocked or failed action may be approved again once the cause is fixed. These states mean the
# message definitely did not leave, so another attempt cannot duplicate it. ``send_unconfirmed`` and
# ``sent`` are deliberately absent: they may already have reached the customer.
OPT_OUT_FOOTER = (
    "\n\n--\nYou are receiving this because of your account with us. If you would rather not hear from us, "
    "reply to this email and say stop -- we will not email you again."
)
RETRYABLE_STATES = ("drafted", "outbound_disabled", "not_configured", "no_recipient", "opted_out", "send_failed")


@dataclass(frozen=True, slots=True)
class Outcome:
    state: str
    state_reason: str | None = None
    attempts: int = 0
    provider_message_id: str | None = None
    redirected_to: str | None = None
    delivery_error: str | None = None

    @property
    def sent(self) -> bool:
        return self.state == "sent"


def _context(session: Session, account_id: uuid.UUID) -> dict:
    cfg = session.execute(
        text("SELECT outbound_enabled, sender_address, sender_verified, demo_mode, test_inbox"
             " FROM tenant_config LIMIT 1")
    ).mappings().one()
    contact = session.execute(text("SELECT contact_email FROM account WHERE id = :a"), {"a": account_id}).scalar()
    opted_out = bool(contact) and session.execute(
        text("SELECT 1 FROM contact_opt_out WHERE lower(email) = lower(:e)"), {"e": contact}
    ).scalar() is not None
    return {**cfg, "contact": contact, "opted_out": opted_out}


def deliver(
    session: Session, *, action_id: uuid.UUID, account_id: uuid.UUID, subject: str, body: str, transport: Transport,
) -> Outcome:
    ctx = _context(session, account_id)
    decision = decide_send(
        outbound_enabled=ctx["outbound_enabled"], sender_address=ctx["sender_address"],
        sender_verified=ctx["sender_verified"], smtp_configured=not isinstance(transport, RecordingTransport),
        demo_mode=ctx["demo_mode"], contact_email=ctx["contact"], opted_out=ctx["opted_out"],
    )
    if not decision.allowed:
        return Outcome(decision.state, decision.reason)

    to, redirected_to, subject_out = ctx["contact"], None, subject
    if ctx["demo_mode"]:
        if not ctx["test_inbox"]:
            return Outcome("sent", "demo mode: captured, nothing was delivered",
                           redirected_to="captured (no test inbox configured)")
        to, redirected_to = ctx["test_inbox"], ctx["test_inbox"]
        subject_out = f"[DEMO → {ctx['contact']}] {subject}"

    sender = ctx["sender_address"]
    domain = sender.rsplit("@", 1)[-1] if "@" in sender else "pulse.local"
    result, attempts = send_with_retry(
        transport, to=to, subject=subject_out, body=body + OPT_OUT_FOOTER, sender=sender,
        message_id=f"<{action_id}@{domain}>", max_attempts=MAX_SEND_ATTEMPTS,
    )
    if result.ok:
        return Outcome("sent", None, attempts, result.provider_message_id, redirected_to)
    if result.kind == "ambiguous":
        return Outcome(
            "send_unconfirmed",
            "delivery could not be confirmed -- check the mail provider before sending again: " + (result.error or ""),
            attempts, None, redirected_to, result.error,
        )
    return Outcome("send_failed", result.error, attempts, None, redirected_to, result.error)


def apply_outcome(session: Session, action_id: uuid.UUID, o: Outcome) -> None:
    session.execute(
        text(
            "UPDATE action SET state = :st, state_reason = :sr, attempts = :att,"
            " sent_at = CASE WHEN :sent THEN now() END, provider_message_id = :pm,"
            " redirected_to = :rt, delivery_error = :de WHERE id = :i"
        ),
        {"st": o.state, "sr": o.state_reason, "att": o.attempts, "sent": o.sent, "pm": o.provider_message_id,
         "rt": o.redirected_to, "de": o.delivery_error, "i": action_id},
    )
