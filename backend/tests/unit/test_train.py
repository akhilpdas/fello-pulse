"""ml/train.py: HistGradientBoostingClassifier with a time-based split and
isotonic calibration on a held-out block (clarifications B-3, B-4)."""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime, timedelta

from pulse.ml.panel import PanelRow
from pulse.ml.train import FEATURE_NAMES, feature_matrix, time_based_split, train


def test_feature_matrix_converts_none_to_nan_and_bool_to_float():
    rows = [{"acv_cents": None, "billing_dunning_active": True, "seats": 10.0}]
    m = feature_matrix(rows)
    acv_idx = FEATURE_NAMES.index("acv_cents")
    dunning_idx = FEATURE_NAMES.index("billing_dunning_active")
    seats_idx = FEATURE_NAMES.index("seats")
    assert math.isnan(m[0][acv_idx])
    assert m[0][dunning_idx] == 1.0
    assert m[0][seats_idx] == 10.0


def test_time_based_split_is_chronological_and_non_overlapping():
    base = datetime(2026, 1, 1, tzinfo=UTC)
    rows = [PanelRow("a", base + timedelta(weeks=i), {}, False) for i in range(100)]
    random.Random(0).shuffle(rows)
    split = time_based_split(rows)
    assert max(r.as_of for r in split.train) <= min(r.as_of for r in split.val)
    assert max(r.as_of for r in split.val) <= min(r.as_of for r in split.calib)
    assert max(r.as_of for r in split.calib) <= min(r.as_of for r in split.test)
    total = len(split.train) + len(split.val) + len(split.calib) + len(split.test)
    assert total == 100


def test_train_produces_calibrated_probabilities_in_unit_interval():
    base = datetime(2024, 1, 1, tzinfo=UTC)
    rng = random.Random(42)
    rows = []
    for i in range(400):
        risky = rng.random() < 0.3
        tickets = rng.uniform(8, 20) if risky else rng.uniform(0, 3)
        label = rng.random() < (0.8 if risky else 0.05)
        rows.append(PanelRow(
            f"acct-{i}", base + timedelta(weeks=i % 90),
            # A real panel never has a column that is 100% missing (e.g.
            # account_age_days is schema-mandatory); the second feature here
            # keeps the matrix realistic for HistGradientBoostingClassifier,
            # which cannot bin a column with zero observed values.
            {"support_tickets_28d": tickets, "account_age_days": float(200 + i)},
            label,
        ))
    split = time_based_split(rows)
    model = train(split, seed=7)
    assert model.seed == 7
    from pulse.ml.train import predict_proba
    proba = predict_proba(model, [r.feature_values for r in split.test])
    assert all(0.0 <= p <= 1.0 for p in proba)


def test_same_seed_gives_identical_predictions():
    base = datetime(2024, 1, 1, tzinfo=UTC)
    rng = random.Random(1)
    rows = [
        PanelRow(f"a{i}", base + timedelta(weeks=i % 80),
                 {"support_tickets_28d": rng.uniform(0, 20), "account_age_days": float(100 + i)},
                 rng.random() < 0.2)
        for i in range(300)
    ]
    split = time_based_split(rows)
    from pulse.ml.train import predict_proba
    m1 = train(split, seed=5)
    m2 = train(split, seed=5)
    p1 = predict_proba(m1, [r.feature_values for r in split.test])
    p2 = predict_proba(m2, [r.feature_values for r in split.test])
    assert list(p1) == list(p2)
