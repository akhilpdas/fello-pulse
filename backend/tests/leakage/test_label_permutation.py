"""SC-010: if the labels are randomly permuted, the model's skill must collapse
to chance. If it doesn't, the training pipeline is leaking information about
the label through some channel other than the (permuted) label itself."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from pulse.ml.evaluate import roc_auc
from pulse.ml.panel import PanelRow
from pulse.ml.train import predict_proba, time_based_split, train


def _synthetic_rows(seed: int) -> list[PanelRow]:
    base = datetime(2024, 1, 1, tzinfo=UTC)
    rng = random.Random(seed)
    rows = []
    for i in range(600):
        risky = rng.random() < 0.3
        tickets = rng.uniform(8, 20) if risky else rng.uniform(0, 3)
        failed_payments = rng.uniform(2, 6) if risky else rng.uniform(0, 1)
        label = rng.random() < (0.85 if risky else 0.04)
        rows.append(PanelRow(
            f"a{i}", base + timedelta(weeks=i % 120),
            {"support_tickets_28d": tickets, "billing_failed_payments_90d": failed_payments,
             "account_age_days": float(300 + i)},
            label,
        ))
    return rows


def test_real_labels_give_a_model_real_skill():
    split = time_based_split(_synthetic_rows(seed=11))
    model = train(split, seed=1)
    proba = predict_proba(model, [r.feature_values for r in split.test])
    y_test = [bool(r.label) for r in split.test]
    assert roc_auc(y_test, proba) > 0.7


def test_permuted_labels_collapse_skill_to_chance():
    rows = _synthetic_rows(seed=11)
    permuted_labels = [r.label for r in rows]
    random.Random(99).shuffle(permuted_labels)
    shuffled_rows = [
        PanelRow(r.account_id, r.as_of, r.feature_values, label)
        for r, label in zip(rows, permuted_labels, strict=True)
    ]
    split = time_based_split(shuffled_rows)
    model = train(split, seed=1)
    proba = predict_proba(model, [r.feature_values for r in split.test])
    y_test = [bool(r.label) for r in split.test]
    auc = roc_auc(y_test, proba)
    assert abs(auc - 0.5) < 0.12, f"permuted-label AUC {auc} is not close to chance"
