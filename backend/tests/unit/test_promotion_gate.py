"""T044: a model that loses to the heuristic baseline must not be promoted
(FR-020). Promotion is gated on beating the baseline at the operating point by
at least settings.promotion_min_lift."""

from __future__ import annotations

from pulse.ml.registry import decide_promotion


def test_model_beating_baseline_by_enough_is_promoted():
    promoted, note = decide_promotion(
        candidate_precision_at_capacity=0.55, baseline_precision_at_capacity=0.40, min_lift=0.02,
    )
    assert promoted is True
    assert "0.40" in note or "beat" in note.lower()


def test_model_losing_to_baseline_is_not_promoted():
    promoted, note = decide_promotion(
        candidate_precision_at_capacity=0.30, baseline_precision_at_capacity=0.40, min_lift=0.02,
    )
    assert promoted is False


def test_model_tying_the_baseline_without_the_required_lift_is_not_promoted():
    promoted, note = decide_promotion(
        candidate_precision_at_capacity=0.405, baseline_precision_at_capacity=0.40, min_lift=0.02,
    )
    assert promoted is False
