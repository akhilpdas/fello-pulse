"""domain/change.py: the agent acts on material change, not on level
(clarifications B-9) -- a tier crossing, a probability move past the
tenant-configured delta, or a dominant-driver switch."""

from __future__ import annotations

from pulse.domain.change import material_change


def test_first_score_is_always_a_material_change():
    changed, reason = material_change(
        previous=None, probability=0.2, tier="amber", dominant_driver="usage_decline",
        material_delta=0.08,
    )
    assert changed is True
    assert reason == "first_score"


def test_tier_crossing_is_a_material_change_even_with_a_small_probability_move():
    changed, reason = material_change(
        previous={"probability": 0.14, "tier": "green", "dominant_driver": "usage_decline"},
        probability=0.16, tier="amber", dominant_driver="usage_decline", material_delta=0.08,
    )
    assert changed is True
    assert reason == "tier_crossing"


def test_probability_move_past_the_delta_without_a_tier_crossing_is_material():
    changed, reason = material_change(
        previous={"probability": 0.20, "tier": "amber", "dominant_driver": "usage_decline"},
        probability=0.30, tier="amber", dominant_driver="usage_decline", material_delta=0.08,
    )
    assert changed is True
    assert reason == "probability_delta"


def test_dominant_driver_switch_is_material_even_at_the_same_probability():
    changed, reason = material_change(
        previous={"probability": 0.55, "tier": "red", "dominant_driver": "usage_decline"},
        probability=0.55, tier="red", dominant_driver="support_experience", material_delta=0.08,
    )
    assert changed is True
    assert reason == "dominant_driver_switch"


def test_a_chronically_amber_account_with_no_real_movement_is_not_material():
    changed, reason = material_change(
        previous={"probability": 0.20, "tier": "amber", "dominant_driver": "usage_decline"},
        probability=0.22, tier="amber", dominant_driver="usage_decline", material_delta=0.08,
    )
    assert changed is False
    assert reason is None
