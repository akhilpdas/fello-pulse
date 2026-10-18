"""Out-of-sample scores for lead time (clarifications B-33).

The model is fitted on the early rows and tested on the last few weeks, so only those few weeks have honest scores --
too few to see how early a loss was foreseen. A rolling-origin backtest refits as time moves on: each chunk of the
evaluation window is scored by a model that saw only data whose outcome had already played out when the chunk began.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pulse.ml.backtest import backtest_report, rolling_origin_scores
from pulse.ml.panel import PanelRow

T0 = datetime(2025, 1, 6, 9, tzinfo=UTC)
WEEKS, HORIZON = 40, 90


def _rows():
    return [PanelRow(a, T0 + timedelta(weeks=w), {"w": w}, False) for w in range(WEEKS) for a in ("a", "b")]


class Spy:
    def __init__(self):
        self.trained_on: list[list[PanelRow]] = []

    def train(self, rows):
        self.trained_on.append(rows)
        return len(self.trained_on) - 1

    def predict(self, model, rows):
        return [float(model)] * len(rows)


def test_every_row_in_the_evaluation_window_is_scored_once_and_nothing_earlier_is():
    spy = Spy()
    rows, scores, folds = rolling_origin_scores(_rows(), horizon_days=HORIZON, eval_weeks=20, n_folds=4,
                                         train_fn=spy.train, predict_fn=spy.predict)
    assert len(rows) == len(scores) == len(folds) == 20 * 2
    assert sorted(set(folds)) == [0, 1, 2, 3]
    assert len({(r.account_id, r.as_of) for r in rows}) == len(rows)
    assert min(r.as_of for r in rows) == T0 + timedelta(weeks=WEEKS - 20)
    assert max(r.as_of for r in rows) == T0 + timedelta(weeks=WEEKS - 1)


def test_a_chunk_is_scored_by_a_model_that_never_saw_data_whose_outcome_was_still_unknown():
    spy = Spy()
    rows, scores, folds = rolling_origin_scores(_rows(), horizon_days=HORIZON, eval_weeks=20, n_folds=4,
                                         train_fn=spy.train, predict_fn=spy.predict)
    assert len(spy.trained_on) == 4
    for fold, scored_by in zip(range(4), range(4), strict=True):
        chunk = [r for r, sc in zip(rows, scores, strict=True) if sc == scored_by]
        start = min(r.as_of for r in chunk)
        assert max(r.as_of for r in spy.trained_on[fold]) <= start - timedelta(days=HORIZON)


def test_later_chunks_are_scored_by_models_trained_on_more_history():
    spy = Spy()
    rolling_origin_scores(_rows(), horizon_days=HORIZON, eval_weeks=20, n_folds=4,
                          train_fn=spy.train, predict_fn=spy.predict)
    sizes = [len(t) for t in spy.trained_on]
    assert sizes == sorted(sizes) and len(set(sizes)) == 4


def test_it_refuses_a_window_with_no_history_to_train_on():
    with pytest.raises(ValueError, match="history"):
        rolling_origin_scores(_rows(), horizon_days=HORIZON, eval_weeks=WEEKS, n_folds=4,
                              train_fn=Spy().train, predict_fn=Spy().predict)


def test_the_report_gives_auc_per_fold_and_lead_time_at_each_threshold():
    from datetime import timedelta as td
    rows = []
    for w in range(WEEKS):
        for a in range(40):
            outcome = T0 + td(weeks=w, days=30) if a < 2 and w % 5 == 0 else None
            rows.append(PanelRow(a, T0 + td(weeks=w), {"hi": float(outcome is not None)}, outcome is not None, outcome))
    report = backtest_report(
        rows, horizon_days=HORIZON, eval_weeks=20, n_folds=4, thresholds={"amber": 0.3, "red": 0.8},
        train_fn=lambda r: None, predict_fn=lambda m, r: [0.9 if x.feature_values["hi"] else 0.1 for x in r])
    assert len(report["auc_by_fold"]) == 4 and report["auc_mean"] == 1.0
    assert report["n_scored"] == 20 * 40 and report["eval_weeks"] == 20
    assert report["lead_time"]["amber"]["recall"] == 1.0 and report["lead_time"]["red"]["recall"] == 1.0
    assert report["lead_time"]["amber"]["threshold"] == 0.3


def test_a_fold_with_no_losses_has_no_auc_instead_of_crashing():
    rows = _rows()   # all labels False
    report = backtest_report(rows, horizon_days=HORIZON, eval_weeks=20, n_folds=4, thresholds={"amber": 0.5},
                             train_fn=lambda r: None, predict_fn=lambda m, r: [0.1] * len(r))
    assert report["auc_by_fold"] == [None] * 4 and report["auc_mean"] is None
