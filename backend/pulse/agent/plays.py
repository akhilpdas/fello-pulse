"""Play registry: the candidate outreach plays, and the eligibility rule
deciding whether a scored account qualifies for one (T061).

Plays are named for the driver they respond to, not "red account" generically
-- the brief's VP ask was to auto-email every red account, which is
indefensible for an account that is red because *our* support failed it
(disagreement D2, clarifications.md). The agent responds to the specific
reason an account is at risk, never to the colour alone.
"""

from __future__ import annotations

from dataclasses import dataclass

_TIER_RANK = {"green": 0, "amber": 1, "red": 2}


@dataclass(frozen=True, slots=True)
class Play:
    key: str
    driver: str
    channel: str = "email"
    # None means the play has no renewal-proximity requirement. Set for plays
    # that only make sense against an approaching renewal, e.g. a commercial
    # review nobody should open a year out.
    max_days_to_renewal: float | None = None


PLAYS: dict[str, Play] = {
    "support_recovery": Play("support_recovery", "support_experience"),
    "adoption_nudge": Play("adoption_nudge", "usage_decline"),
    "billing_resolution": Play("billing_resolution", "payment_friction"),
    "relationship_rebuild": Play("relationship_rebuild", "relationship_engagement"),
    "commercial_review": Play("commercial_review", "commercial_signals", max_days_to_renewal=90),
}

_PLAY_BY_DRIVER = {p.driver: p for p in PLAYS.values()}


def eligible_plays(
    *, dominant_driver: str | None, tier: str, confidence: str, days_to_renewal: float | None,
) -> list[Play]:
    """At most one play today -- the dominant driver names exactly one. A
    future play that responds to a *secondary* driver would extend this to
    return more than one; nothing here assumes a single result forever."""
    if confidence != "high":
        return []
    if _TIER_RANK.get(tier, 0) < _TIER_RANK["amber"]:
        return []
    if dominant_driver is None:
        return []
    play = _PLAY_BY_DRIVER.get(dominant_driver)
    if play is None:
        return []
    if play.max_days_to_renewal is not None:
        if days_to_renewal is None or days_to_renewal > play.max_days_to_renewal:
            return []
    return [play]
