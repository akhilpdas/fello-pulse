"""ml/explain.py: TreeSHAP per-feature contributions, summed into the six
driver groups User Story 2 needs for an explainable queue row."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from pulse.ml.explain import contributions, dominant_driver, driver_contributions, expected_value
from pulse.ml.panel import PanelRow
from pulse.ml.train import time_based_split, train


def _trained_model():
    base = datetime(2024, 1, 1, tzinfo=UTC)
    rng = random.Random(3)
    rows = []
    for i in range(300):
        risky = rng.random() < 0.3
        tickets = rng.uniform(8, 20) if risky else rng.uniform(0, 3)
        label = rng.random() < (0.8 if risky else 0.05)
        rows.append(PanelRow(
            f"a{i}", base + timedelta(weeks=i % 80),
            {"support_tickets_28d": tickets, "account_age_days": float(300 + i)}, label,
        ))
    split = time_based_split(rows)
    return train(split, seed=1), rows[0].feature_values


def test_contributions_returns_one_value_per_fitted_feature():
    model, values = _trained_model()
    contrib = contributions(model, values)
    assert set(contrib) == set(model.feature_names)
    assert all(isinstance(v, float) for v in contrib.values())


def test_driver_contributions_sums_by_registered_driver_group():
    model, values = _trained_model()
    contrib = contributions(model, values)
    totals = driver_contributions(contrib)
    # support_tickets_28d -> support_experience, account_age_days -> commercial_signals
    assert "support_experience" in totals
    assert "commercial_signals" in totals
    assert abs(sum(totals.values()) - sum(contrib.values())) < 1e-9


def test_dominant_driver_is_the_largest_magnitude_total():
    totals = {"support_experience": 0.5, "commercial_signals": -0.1, "usage_decline": 0.05}
    assert dominant_driver(totals) == "support_experience"


def test_contributions_reconcile_to_the_base_models_raw_output():
    """SHAP additivity holds in log-odds space for a tree ensemble: summed
    contributions plus the explainer's base value equals the base model's own
    logit(probability) -- this is what proves a persisted score's evidence
    actually accounts for its own number, not a plausible-looking fiction."""
    import math

    from pulse.ml.train import predict_proba_raw

    model, values = _trained_model()
    contrib = contributions(model, values)
    base = expected_value(model)
    reconstructed_logit = sum(contrib.values()) + base

    raw_prob = float(predict_proba_raw(model, [values])[0])
    actual_logit = math.log(raw_prob / (1 - raw_prob))
    assert abs(reconstructed_logit - actual_logit) < 1e-6
