"""May this approved draft leave the building? (FR-014, FR-015, FR-016). Pure and IO-free.

Safe by default: a message is only sent when outbound email is switched on for the tenant, a verified
sender exists, the provider is configured, the account has a known contact, and that contact has not asked
us to stop. Every other case is its own named state, never a silent drop, and the order below is the order an
operator would fix things in.

Demo mode (FR-020) relaxes only the *provider* requirement -- nothing real is sent, so the message is captured
instead -- and never a missing recipient or an opt-out: a demo that skips safety checks teaches the wrong habits.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GateDecision:
    allowed: bool
    state: str  # ok | outbound_disabled | not_configured | no_recipient | opted_out
    reason: str | None = None


def decide_send(
    *, outbound_enabled: bool, sender_address: str | None, sender_verified: bool, smtp_configured: bool,
    demo_mode: bool, contact_email: str | None, opted_out: bool,
) -> GateDecision:
    if not outbound_enabled:
        return GateDecision(False, "outbound_disabled", "outbound email is switched off for this tenant")
    if not (sender_address and sender_address.strip()):
        return GateDecision(False, "not_configured", "no sender address is configured for this tenant")
    if not sender_verified:
        return GateDecision(False, "not_configured", "the sender address has not been verified by an operator")
    if not smtp_configured and not demo_mode:
        return GateDecision(False, "not_configured", "no mail provider is configured for this deployment")
    if not (contact_email and contact_email.strip()):
        return GateDecision(False, "no_recipient", "this account has no known customer contact")
    if opted_out:
        return GateDecision(False, "opted_out", "this contact has asked not to be emailed")
    return GateDecision(True, "ok")
