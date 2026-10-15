"""domain/tiers.py: probability -> red/amber/green from tenant thresholds, plus
the 0-100 "health score" a CSM reads on the queue row."""

from __future__ import annotations

from pulse.domain.tiers import health_score, tier_for


def test_probability_at_or_above_red_threshold_is_red():
    assert tier_for(0.40, tier_red_at=0.35, tier_amber_at=0.15) == "red"
    assert tier_for(0.35, tier_red_at=0.35, tier_amber_at=0.15) == "red"


def test_probability_between_thresholds_is_amber():
    assert tier_for(0.20, tier_red_at=0.35, tier_amber_at=0.15) == "amber"


def test_probability_below_amber_threshold_is_green():
    assert tier_for(0.05, tier_red_at=0.35, tier_amber_at=0.15) == "green"


def test_health_score_is_the_complement_of_probability_on_a_0_to_100_scale():
    assert health_score(0.0) == 100
    assert health_score(1.0) == 0
    assert health_score(0.42) == 58


def test_health_score_clips_to_the_valid_range():
    assert health_score(-0.1) == 100
    assert health_score(1.1) == 0
