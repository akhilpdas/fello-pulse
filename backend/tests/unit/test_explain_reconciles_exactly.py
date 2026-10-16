"""GUARD: the per-feature attributions account for the model's own output *exactly* (to floating-point noise), before
anything is stored. The persisted check (``test_evidence_trail``) can only be as precise as the stored probability --
5 decimals -- which near p = 0.02 is worth up to ~3e-4 in log-odds; this is where exactness is actually proven.
Passes on first run (measured: error ~1e-15 over 400 vectors); it protects a property, it is not test-first.
"""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime, timedelta

from pulse.ml.explain import contributions, expected_value
from pulse.ml.panel import PanelRow
from pulse.ml.train import predict_proba_raw, time_based_split, train


def _model():
    base, rng, rows = datetime(2024, 1, 1, tzinfo=UTC), random.Random(9), []
    for i in range(300):
        risky = rng.random() < 0.3
        t = rng.uniform(8, 20) if risky else rng.uniform(0, 3)
        rows.append(PanelRow(f"a{i}", base + timedelta(weeks=i % 80),
                             {"support_tickets_28d": t, "account_age_days": float(300 + i)}, rng.random() < (0.8 if risky else 0.05)))
    return train(time_based_split(rows), seed=11)


def test_contributions_plus_the_base_value_equal_the_models_logit_to_floating_point_noise():
    model, ev, rng = _model(), None, random.Random(1)
    ev = expected_value(model)
    for _ in range(60):
        fv = {"support_tickets_28d": rng.uniform(0, 22), "account_age_days": rng.uniform(100, 900)}
        p = min(max(float(predict_proba_raw(model, [fv])[0]), 1e-12), 1 - 1e-12)
        assert abs(sum(contributions(model, fv).values()) + ev - math.log(p / (1 - p))) < 1e-9
