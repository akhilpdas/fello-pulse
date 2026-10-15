"""Autonomy's reviewed boundary (constitution Principle III). Given an
eligible play for a scored account, decide whether the agent may draft at
all, and whether it may *send* unattended. Every declined decision returns a
machine-readable reason -- an autonomous system nobody can audit is one
nobody will leave switched on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allow_draft: bool
    allow_auto_send: bool
    # Explains whichever of the two flags above is False. None only when
    # both are True -- every withholding is audit-visible on the Action row
    # this decision produces (T070), not just inferred from a flag.
    reason: str | None


def decide(
    *,
    human_suppressed: bool,
    last_action_at: datetime | None,
    now: datetime,
    suppression_days: int,
    auto_send_allowlisted: bool,
    sends_this_cycle: int,
    max_sends_per_cycle: int,
) -> PolicyDecision:
    if human_suppressed:
        return PolicyDecision(False, False, "suppressed")
    if last_action_at is not None and (now - last_action_at).days < suppression_days:
        return PolicyDecision(False, False, "suppression_window_active")
    # Draft-for-a-human is always the default once the account isn't
    # suppressed or cooling down -- it is never gated on the allowlist.
    if not auto_send_allowlisted:
        return PolicyDecision(True, False, "not_allowlisted_for_auto_send")
    if sends_this_cycle >= max_sends_per_cycle:
        return PolicyDecision(True, False, "rate_limit_reached")
    return PolicyDecision(True, True, None)
