"""T060: when the strongest signal behind a score is a data outage -- a
connected source gone stale -- the dominant driver must be reported as
data_quality, not mistaken for customer behaviour. The product's explanation
must say "we have a data problem," not "the customer is disengaging," because
those lead to opposite CSM actions (spec edge case; contracts/features.md)."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from pulse.ml.explain import contributions, dominant_driver, driver_contributions
from pulse.ml.panel import PanelRow
from pulse.ml.train import time_based_split, train


def test_dominant_driver_is_data_quality_when_source_staleness_is_the_strongest_signal():
    base = datetime(2024, 1, 1, tzinfo=UTC)
    rng = random.Random(17)
    rows = []
    for i in range(400):
        # The only real signal in this synthetic panel is source staleness --
        # a stand-in for "zendesk stopped sending us anything," a data
        # problem, not a customer one.
        stale_outage = rng.random() < 0.3
        staleness = rng.uniform(200, 400) if stale_outage else rng.uniform(0, 20)
        label = rng.random() < (0.7 if stale_outage else 0.05)
        rows.append(PanelRow(
            f"a{i}", base + timedelta(weeks=i % 90),
            {"cov_max_source_staleness_days": staleness, "account_age_days": float(300 + i)},
            label,
        ))
    model = train(time_based_split(rows), seed=8)

    severe_outage_values = {"cov_max_source_staleness_days": 380.0, "account_age_days": 500.0}
    contrib = contributions(model, severe_outage_values)
    totals = driver_contributions(contrib)

    assert dominant_driver(totals) == "data_quality"
