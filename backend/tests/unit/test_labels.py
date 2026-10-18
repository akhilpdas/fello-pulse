"""ml/labels.py: churn-or-material-contraction, per clarifications A1.

Labelling is the one module allowed to look forward from as_of -- it produces
the training target, never a feature. A contraction only counts if it sticks
past one billing cycle; a billing blip that reverts within the cycle is noise,
not a loss event.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pulse.features.compute import EventRecord
from pulse.ml.labels import label_for_window, outcome_events

AS_OF = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)


def _sub(id_, occurred, mrr, prev_mrr):
    return EventRecord(id_, "stripe", "billing.subscription_updated", occurred, occurred,
                        {"subscription_ref": "sub_1", "mrr_cents": mrr, "previous_mrr_cents": prev_mrr})


def _cancel(id_, occurred):
    return EventRecord(id_, "stripe", "billing.subscription_deleted", occurred, occurred,
                        {"subscription_ref": "sub_1", "reason": "x"})


def test_churn_event_is_an_outcome():
    events = [_cancel(1, AS_OF + timedelta(days=30))]
    outcomes = outcome_events(events, contraction_threshold=0.25)
    assert len(outcomes) == 1
    assert outcomes[0].kind == "churn"


def test_sustained_contraction_above_threshold_is_an_outcome():
    events = [_sub(1, AS_OF + timedelta(days=10), mrr=7000, prev_mrr=10000)]  # -30%
    outcomes = outcome_events(events, contraction_threshold=0.25)
    assert len(outcomes) == 1
    assert outcomes[0].kind == "contraction"


def test_contraction_below_threshold_is_not_an_outcome():
    events = [_sub(1, AS_OF + timedelta(days=10), mrr=9000, prev_mrr=10000)]  # -10%
    assert outcome_events(events, contraction_threshold=0.25) == []


def test_contraction_reverted_within_one_billing_cycle_is_not_an_outcome():
    events = [
        _sub(1, AS_OF + timedelta(days=10), mrr=7000, prev_mrr=10000),
        _sub(2, AS_OF + timedelta(days=20), mrr=10000, prev_mrr=7000),  # recovers
    ]
    assert outcome_events(events, contraction_threshold=0.25) == []


def test_contraction_still_down_after_one_cycle_is_an_outcome():
    events = [
        _sub(1, AS_OF + timedelta(days=10), mrr=7000, prev_mrr=10000),
        _sub(2, AS_OF + timedelta(days=60), mrr=7200, prev_mrr=7000),  # still down, later
    ]
    outcomes = outcome_events(events, contraction_threshold=0.25)
    assert len(outcomes) == 1
    assert outcomes[0].kind == "contraction"


def test_label_for_window_true_only_when_event_falls_inside_the_horizon():
    events = [_cancel(1, AS_OF + timedelta(days=95))]  # just past a 90-day horizon
    outcomes = outcome_events(events, contraction_threshold=0.25)
    assert label_for_window(outcomes, AS_OF, horizon_days=90) is False
    assert label_for_window(outcomes, AS_OF, horizon_days=100) is True


def test_label_for_window_false_with_no_outcomes():
    assert label_for_window([], AS_OF, horizon_days=90) is False


def test_next_outcome_at_is_the_first_loss_event_inside_the_horizon():
    from pulse.ml.labels import next_outcome_at
    first, later = AS_OF + timedelta(days=30), AS_OF + timedelta(days=60)
    outcomes = outcome_events([_cancel(1, first), _cancel(2, later)], contraction_threshold=0.25)
    assert next_outcome_at(outcomes, AS_OF, horizon_days=90) == first


def test_next_outcome_at_is_none_when_nothing_happens_inside_the_horizon():
    from pulse.ml.labels import next_outcome_at
    outcomes = outcome_events([_cancel(1, AS_OF + timedelta(days=120))], contraction_threshold=0.25)
    assert next_outcome_at(outcomes, AS_OF, horizon_days=90) is None


def test_next_outcome_at_agrees_with_the_label():
    from pulse.ml.labels import next_outcome_at
    outcomes = outcome_events([_cancel(1, AS_OF + timedelta(days=90))], contraction_threshold=0.25)  # on the boundary
    assert (next_outcome_at(outcomes, AS_OF, 90) is not None) == label_for_window(outcomes, AS_OF, 90)
