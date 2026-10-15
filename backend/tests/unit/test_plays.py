"""agent/plays.py (T061): eligibility by dominant driver, value tier, renewal
proximity, confidence. Pure function, no DB."""

from __future__ import annotations

from pulse.agent.plays import eligible_plays


def test_matches_the_play_registered_for_the_dominant_driver():
    plays = eligible_plays(
        dominant_driver="support_experience", tier="red", confidence="high",
        days_to_renewal=200,
    )
    assert [p.key for p in plays] == ["support_recovery"]


def test_no_play_for_an_unmapped_driver():
    plays = eligible_plays(
        dominant_driver="data_quality", tier="red", confidence="high",
        days_to_renewal=200,
    )
    assert plays == []


def test_green_tier_is_never_eligible():
    plays = eligible_plays(
        dominant_driver="support_experience", tier="green", confidence="high",
        days_to_renewal=200,
    )
    assert plays == []


def test_low_confidence_is_never_eligible():
    """An abstain-grade score must not generate outreach -- drafting from
    evidence the system itself doesn't trust would undermine SC-012 one
    layer up."""
    plays = eligible_plays(
        dominant_driver="support_experience", tier="red", confidence="low",
        days_to_renewal=200,
    )
    assert plays == []


def test_commercial_review_requires_an_approaching_renewal():
    far = eligible_plays(
        dominant_driver="commercial_signals", tier="red", confidence="high",
        days_to_renewal=400,
    )
    near = eligible_plays(
        dominant_driver="commercial_signals", tier="red", confidence="high",
        days_to_renewal=60,
    )
    assert far == []
    assert [p.key for p in near] == ["commercial_review"]


def test_no_renewal_date_does_not_block_a_play_without_a_proximity_rule():
    plays = eligible_plays(
        dominant_driver="support_experience", tier="red", confidence="high",
        days_to_renewal=None,
    )
    assert [p.key for p in plays] == ["support_recovery"]
