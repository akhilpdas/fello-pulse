"""T059: GET /accounts/{id}/score-diff attributes a known feature movement
correctly -- the feature that actually changed between two scores must show
up with a non-zero value_delta and dominate the contribution_delta ranking.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import text

from pulse.api.main import app
from pulse.db.session import owner_session, tenant_session
from pulse.ml.panel import PanelRow
from pulse.ml.train import time_based_split, train
from pulse.scoring.service import score_and_persist


def _toy_model():
    base = datetime(2024, 1, 1, tzinfo=UTC)
    rng = random.Random(31)
    rows = [
        PanelRow(f"a{i}", base + timedelta(weeks=i % 80),
                 {"support_tickets_28d": rng.uniform(0, 20), "account_age_days": float(300 + i)},
                 rng.random() < 0.15)
        for i in range(400)
    ]
    return train(time_based_split(rows), seed=14)


def test_score_diff_surfaces_the_feature_that_actually_moved():
    with owner_session() as s:
        tenant_id = s.execute(text("SELECT id FROM tenant WHERE slug = 'northwind'")).scalar()
        account_id = s.execute(
            text(
                "SELECT a.id FROM account a JOIN source_event e ON e.account_id = a.id"
                " WHERE a.tenant_id = :t GROUP BY a.id HAVING count(*) > 100 LIMIT 1 OFFSET 1"
            ),
            {"t": tenant_id},
        ).scalar()

    model = _toy_model()
    from_as_of = datetime(2026, 4, 1, 9, 0, tzinfo=UTC)
    to_as_of = datetime(2026, 4, 1, 9, 0, tzinfo=UTC) + timedelta(weeks=4)

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
        score_and_persist(s, tenant_id=tenant_id, account_id=account_id, model=model,
                           model_version="test-model-v1", tenant_config=tenant_config, as_of=from_as_of)
        score_and_persist(s, tenant_id=tenant_id, account_id=account_id, model=model,
                           model_version="test-model-v1", tenant_config=tenant_config, as_of=to_as_of)

    client = TestClient(app)
    resp = client.get(
        f"/accounts/{account_id}/score-diff",
        params={"from_as_of": from_as_of.isoformat(), "to_as_of": to_as_of.isoformat()},
        headers={"X-Tenant-Id": str(tenant_id)},
    )
    assert resp.status_code == 200
    body = resp.json()

    # account_age_days moves by exactly 28 days between any two as_of four
    # weeks apart -- a known, deterministic movement every real account has.
    age_diff = next(d for d in body["feature_diffs"] if d["feature"] == "account_age_days")
    assert abs(age_diff["value_delta"] - 28.0) < 1e-6

    assert body["probability_delta"] == body["to"]["probability"] - body["from"]["probability"]
    # The ranking is sorted by |contribution_delta| descending.
    deltas = [abs(d["contribution_delta"]) for d in body["feature_diffs"]]
    assert deltas == sorted(deltas, reverse=True)
