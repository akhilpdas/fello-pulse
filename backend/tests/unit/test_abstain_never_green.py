"""T054 / SC-012: an account with insufficient evidence must never be
presented as green, regardless of what the model would otherwise say -- it
gets the explicit "abstain" tier, not a silent fallback to the healthiest one.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from pulse.db.session import owner_session, tenant_session
from pulse.ml.panel import PanelRow
from pulse.ml.train import time_based_split, train
from pulse.scoring.service import score_and_persist


def _toy_model():
    base = datetime(2024, 1, 1, tzinfo=UTC)
    rng = random.Random(9)
    rows = [
        PanelRow(f"a{i}", base + timedelta(weeks=i % 80),
                 {"support_tickets_28d": rng.uniform(0, 3), "account_age_days": float(300 + i)},
                 rng.random() < 0.15)
        for i in range(400)
    ]
    return train(time_based_split(rows), seed=3)


def test_an_account_as_of_shortly_after_its_first_event_abstains_rather_than_shows_green():
    with owner_session() as s:
        tenant_id = s.execute(text("SELECT id FROM tenant WHERE slug = 'northwind'")).scalar()
        account_id, first_occurred = s.execute(
            text(
                "SELECT account_id, min(occurred_at) FROM source_event"
                " WHERE tenant_id = :t AND account_id IS NOT NULL"
                " GROUP BY account_id ORDER BY count(*) DESC LIMIT 1"
            ),
            {"t": tenant_id},
        ).one()

    model = _toy_model()
    # Only 5 days of observed history -- far short of min_days_history (30).
    as_of = first_occurred + timedelta(days=5)

    with tenant_session(tenant_id) as s:
        cfg = s.execute(
            text(
                "SELECT connected_sources, min_days_history, min_sources_with_data,"
                " tier_red_at, tier_amber_at FROM tenant_config WHERE tenant_id = :t"
            ),
            {"t": tenant_id},
        ).one()
        tenant_config = {
            "connected_sources": frozenset(cfg[0]), "min_days_history": cfg[1],
            "min_sources_with_data": cfg[2], "tier_red_at": float(cfg[3]), "tier_amber_at": float(cfg[4]),
        }
        scored = score_and_persist(
            s, tenant_id=tenant_id, account_id=account_id, model=model,
            model_version="test-model-v1", tenant_config=tenant_config, as_of=as_of,
        )

    assert scored.tier == "abstain"
    assert scored.tier != "green"
    assert scored.abstain_reason == "insufficient_history"
    assert scored.confidence == "low"
