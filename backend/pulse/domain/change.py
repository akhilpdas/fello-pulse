"""Material change, not level (clarifications B-9). Acting on level re-floods
the queue with the same chronically-amber accounts every cycle and trains
users to ignore it. The agent (Phase 9) only acts when this returns True.
"""

from __future__ import annotations


def material_change(
    *, previous: dict | None, probability: float, tier: str, dominant_driver: str | None,
    material_delta: float,
) -> tuple[bool, str | None]:
    if previous is None:
        return True, "first_score"
    if previous["tier"] != tier:
        return True, "tier_crossing"
    if abs(probability - previous["probability"]) >= material_delta:
        return True, "probability_delta"
    if previous.get("dominant_driver") != dominant_driver:
        return True, "dominant_driver_switch"
    return False, None
