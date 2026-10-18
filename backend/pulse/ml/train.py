"""Model fitting: HistGradientBoostingClassifier, time-based split, sigmoid
calibration on a held-out block (clarifications B-3, B-4, B-33).

Calibration is sigmoid (Platt), not isotonic: isotonic fitted on a few thousand rare-positive rows produced
"100% likely" accounts and ~20 distinct scores, and was overconfident where it mattered (predicted 0.36 against 0.28
observed among scores >= 0.25; sigmoid: 0.40 against 0.41). Clarifications B-33.

Gradient-boosted trees were chosen specifically because they handle missing
values natively -- a feature's ``None`` is informative absence, not something
to impute, and the constitution forbids fabricating evidence. ``None`` and
``nan`` are used interchangeably here for exactly that reason.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.frozen import FrozenEstimator

from pulse.features.registry import REGISTRY
from pulse.ml.panel import PanelRow

FEATURE_NAMES: list[str] = sorted(REGISTRY)

# Shallow, slow, heavily constrained trees (clarifications B-33). Churn is ~4% of rows and nearly every feature is a
# noisy view of an account's health, so the library defaults memorise the training weeks: on the rolling backtest they
# scored a mean out-of-sample ROC-AUC of 0.62 against 0.67 for these, which is what an oracle holding each account's
# hidden health reaches. Chosen on the first three backtest folds; the latest fold was left untouched as a check.
BASE_PARAMS = dict(max_depth=2, learning_rate=0.05, max_iter=400, l2_regularization=1.0)


def min_leaf(n_rows: int) -> int:
    """Rows required per leaf: 1% of the rows fitted, between the library's 20 and 300. Every fold of the real backtest
    has 30,000+ rows and so gets the full 300; a tiny training set (the toy models in the tests) still gets to split,
    where a fixed 300 would forbid every split and give every account the same score."""
    return int(min(300, max(20, 0.01 * n_rows)))


def _to_num(v) -> float:
    if v is None:
        return float("nan")
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    return float(v)


def feature_matrix(rows: list[dict]) -> np.ndarray:
    return np.array(
        [[_to_num(r.get(name)) for name in FEATURE_NAMES] for r in rows], dtype=float
    )


@dataclass(frozen=True, slots=True)
class Split:
    train: list[PanelRow]
    val: list[PanelRow]
    calib: list[PanelRow]
    test: list[PanelRow]


def time_based_split(
    rows: list[PanelRow], train: float = 0.6, val: float = 0.15, calib: float = 0.15
) -> Split:
    """Earliest block trains, next validates, next calibrates, most recent
    tests -- clarifications B-4. An account legitimately appears in more than
    one block at different dates; that is the deployed situation."""
    ordered = sorted(rows, key=lambda r: r.as_of)
    n = len(ordered)
    i1 = int(n * train)
    i2 = int(n * (train + val))
    i3 = int(n * (train + val + calib))
    return Split(ordered[:i1], ordered[i1:i2], ordered[i2:i3], ordered[i3:])


@dataclass(frozen=True, slots=True)
class TrainedModel:
    base: HistGradientBoostingClassifier
    calibrator: CalibratedClassifierCV
    feature_names: list[str]  # the subset actually fitted on -- see dropped_features
    dropped_features: list[str]
    seed: int


def train(split: Split, seed: int) -> TrainedModel:
    # The validation block is learned from too: nothing here tunes on it, so holding it out only threw away a quarter
    # of the history (clarifications B-33). Calibration and test stay untouched.
    fit_rows = [*split.train, *split.val]
    x_train_full = feature_matrix([r.feature_values for r in fit_rows])
    y_train = [bool(r.label) for r in fit_rows]

    # A feature with zero observed values in this training window carries no
    # signal HistGradientBoostingClassifier can bin on and crashes the fit --
    # drop it for this model, transparently, rather than let an unlucky split
    # take down training. Kept distinct from an absent *value*, which the
    # model still natively handles as missing.
    observed = ~np.all(np.isnan(x_train_full), axis=0)
    used_names = [n for n, keep in zip(FEATURE_NAMES, observed, strict=True) if keep]
    dropped = [n for n, keep in zip(FEATURE_NAMES, observed, strict=True) if not keep]

    x_train = x_train_full[:, observed]
    base = HistGradientBoostingClassifier(
        random_state=seed, min_samples_leaf=min_leaf(len(y_train)), **BASE_PARAMS).fit(x_train, y_train)

    x_calib = feature_matrix([r.feature_values for r in split.calib])[:, observed]
    y_calib = [bool(r.label) for r in split.calib]
    calibrator = CalibratedClassifierCV(FrozenEstimator(base), method="sigmoid").fit(
        x_calib, y_calib
    )
    return TrainedModel(
        base=base, calibrator=calibrator, feature_names=used_names,
        dropped_features=dropped, seed=seed,
    )


def _select(model: TrainedModel, feature_values: list[dict]) -> np.ndarray:
    full = feature_matrix(feature_values)
    idx = [FEATURE_NAMES.index(n) for n in model.feature_names]
    return full[:, idx]


def predict_proba(model: TrainedModel, feature_values: list[dict]) -> np.ndarray:
    return model.calibrator.predict_proba(_select(model, feature_values))[:, 1]


def predict_proba_raw(model: TrainedModel, feature_values: list[dict]) -> np.ndarray:
    """Uncalibrated probability from the base model -- used to report the
    calibration's own effect, never for ranking."""
    return model.base.predict_proba(_select(model, feature_values))[:, 1]
