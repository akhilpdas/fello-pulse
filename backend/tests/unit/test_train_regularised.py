"""The fitted model must not chase noise (clarifications B-33).

Churn is rare (~4% of rows) and most of the 38 features are weak, noisy views of an account's health. With the default
gradient-boosting settings the model memorises the training weeks and ranks *later* weeks worse than a much simpler
one: on the real rolling backtest the mean out-of-sample ROC-AUC was 0.62 against 0.67 for shallow, slow, heavily
constrained trees (which equals what an oracle that knows each account's hidden health achieves). This reproduces that
shape on synthetic data: a few faint signals among many noise features, rare positives.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

from pulse.ml.panel import PanelRow
from pulse.ml.train import FEATURE_NAMES, feature_matrix, predict_proba, time_based_split, train

T0 = datetime(2025, 1, 6, 9, tzinfo=UTC)


def _panel(n=24000, seed=3):
    rng = np.random.default_rng(seed)
    signal = FEATURE_NAMES[:3]
    rows = []
    for i in range(n):
        v = {name: float(rng.normal()) for name in FEATURE_NAMES}
        logit = -3.5 + 0.55 * v[signal[0]] + 0.4 * v[signal[1]] + 0.3 * v[signal[2]]
        label = bool(rng.random() < 1 / (1 + np.exp(-logit)))
        rows.append(PanelRow(f"a{i}", T0 + timedelta(weeks=i * 100 // n), v, label))
    return rows


def _gain(seed: int) -> float:
    split = time_based_split(_panel(seed=seed))
    y_test = [bool(r.label) for r in split.test]
    x_test = [r.feature_values for r in split.test]
    default = HistGradientBoostingClassifier(random_state=7).fit(
        feature_matrix([r.feature_values for r in split.train]), [bool(r.label) for r in split.train])
    auc_default = roc_auc_score(y_test, default.predict_proba(feature_matrix(x_test))[:, 1])
    return roc_auc_score(y_test, predict_proba(train(split, seed=7), x_test)) - auc_default


def test_the_trained_model_ranks_unseen_weeks_better_than_default_boosting():
    # One draw is noise (rare positives); across six the gain was positive every time (min +0.012, mean +0.032).
    gains = [_gain(seed) for seed in range(3, 9)]
    assert min(gains) > 0, gains
    assert sum(gains) / len(gains) >= 0.02, gains


def test_the_validation_block_is_learned_from_not_wasted():
    # The validation block was never used for anything, so a quarter of the history was thrown away (B-33). Here the
    # earliest block is pure noise and only the validation block carries the signal: a model that ignores it is blind.
    from pulse.ml.train import Split
    rng = np.random.default_rng(11)
    name = FEATURE_NAMES[0]

    def block(n, informative, start_week):
        rows = []
        for i in range(n):
            x = float(rng.normal())
            p = 1 / (1 + np.exp(-(-2.0 + 2.5 * x))) if informative else 0.2
            rows.append(PanelRow(f"a{start_week}-{i}", T0 + timedelta(weeks=start_week), {name: x}, bool(rng.random() < p)))
        return rows

    split = Split(train=block(3000, False, 0), val=block(3000, True, 1), calib=block(3000, True, 2), test=block(3000, True, 3))
    y = [bool(r.label) for r in split.test]
    auc = roc_auc_score(y, predict_proba(train(split, seed=7), [r.feature_values for r in split.test]))
    assert auc > 0.7, auc


def test_no_account_is_ever_shown_as_certain_and_scores_are_not_a_handful_of_plateaus():
    # Isotonic calibration, fitted on a few thousand rows with ~4% positives, turned tiny groups at the top into
    # "100% likely to churn" and left only ~20-30 distinct scores -- a probability of 1.0 destroys trust in the product,
    # and a cut-off placed inside a plateau splits near-identical accounts (clarifications B-32/B-33).
    for seed in (3, 4):
        split = time_based_split(_panel(seed=seed))
        p = predict_proba(train(split, seed=7), [r.feature_values for r in split.test])
        assert p.max() < 0.95, (seed, p.max())
        assert len(set(np.round(p, 6))) > 500, (seed, len(set(np.round(p, 6))))
