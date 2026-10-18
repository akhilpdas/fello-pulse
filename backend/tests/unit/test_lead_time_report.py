"""Lead time across every loss event (SC-005; clarifications B-21 and B-33).

Lead time is the warning a CSM got: days between the first week an account was flagged and the loss itself. It is
measured over *all* loss events, never over hand-picked accounts, and it counts the events that were never flagged
(recall) because a median over only the caught ones flatters the model.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pulse.ml.evaluate import lead_time_report
from pulse.ml.panel import PanelRow

T0 = datetime(2026, 1, 5, 9, tzinfo=UTC)


def _row(account, week, outcome_in_days=None):
    as_of = T0 + timedelta(weeks=week)
    outcome = as_of + timedelta(days=outcome_in_days) if outcome_in_days is not None else None
    return PanelRow(account, as_of, {}, outcome is not None, outcome)


def test_lead_time_is_measured_from_the_first_flagged_week():
    # one loss on day 70; rows from week 0 (70 days before) to week 9 (7 days before); flagged from week 4 on
    loss = T0 + timedelta(days=70)
    rows = [PanelRow("a", T0 + timedelta(weeks=w), {}, True, loss) for w in range(10)]
    scores = [0.01 if w < 4 else 0.5 for w in range(10)]
    r = lead_time_report(rows, scores, threshold=0.1)
    assert (r["n_events"], r["n_flagged"], r["recall"]) == (1, 1, 1.0)
    assert r["median_days"] == 70 - 4 * 7


def test_an_event_that_was_never_flagged_lowers_recall_and_is_not_in_the_median():
    loss_a, loss_b = T0 + timedelta(days=60), T0 + timedelta(days=60)
    rows = [PanelRow("a", T0, {}, True, loss_a), PanelRow("b", T0, {}, True, loss_b)]
    r = lead_time_report(rows, [0.9, 0.01], threshold=0.1)
    assert (r["n_events"], r["n_flagged"], r["recall"]) == (2, 1, 0.5)
    assert r["median_days"] == 60


def test_the_median_is_over_the_flagged_events():
    rows = [PanelRow(i, T0, {}, True, T0 + timedelta(days=d)) for i, d in enumerate((10, 40, 80))]
    r = lead_time_report(rows, [0.9, 0.9, 0.9], threshold=0.1)
    assert r["median_days"] == 40


def test_share_flagged_at_least_four_weeks_ahead():
    rows = [PanelRow(i, T0, {}, True, T0 + timedelta(days=d)) for i, d in enumerate((10, 40, 80, 90))]
    r = lead_time_report(rows, [0.9] * 4, threshold=0.1)
    assert r["share_flagged_28d_or_more_ahead"] == 0.75   # 40, 80, 90 of the four events


def test_two_losses_by_one_account_are_two_events():
    rows = [PanelRow("a", T0, {}, True, T0 + timedelta(days=20)),
            PanelRow("a", T0 + timedelta(weeks=20), {}, True, T0 + timedelta(weeks=20, days=30))]
    assert lead_time_report(rows, [0.9, 0.9], threshold=0.1)["n_events"] == 2


def test_rows_with_no_loss_only_count_towards_the_alert_rate():
    rows = [_row("a", 0), _row("b", 0), _row("c", 0), _row("d", 0)]
    r = lead_time_report(rows, [0.5, 0.5, 0.01, 0.01], threshold=0.1)
    assert r["n_events"] == 0 and r["recall"] is None and r["median_days"] is None
    assert r["alert_rate"] == 0.5


def test_a_score_exactly_at_the_threshold_is_flagged():
    rows = [PanelRow("a", T0, {}, True, T0 + timedelta(days=30))]
    assert lead_time_report(rows, [0.098], threshold=0.098)["n_flagged"] == 1
