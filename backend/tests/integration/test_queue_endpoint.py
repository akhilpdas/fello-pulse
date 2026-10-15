"""T053: GET /queue returns a bounded, ordered queue with the fields a CSM
needs on each row: reason (dominant driver), value at risk, renewal distance,
and the delta from the previous score."""

from __future__ import annotations

import random
import uuid
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
    rng = random.Random(21)
    rows = [
        PanelRow(f"a{i}", base + timedelta(weeks=i % 80),
                 {"support_tickets_28d": rng.uniform(0, 20), "account_age_days": float(300 + i)},
                 rng.random() < 0.15)
        for i in range(400)
    ]
    return train(time_based_split(rows), seed=6)


def _setup_scored_queue():
    with owner_session() as s:
        tenant_id = s.execute(text("SELECT id FROM tenant WHERE slug = 'northwind'")).scalar()
        account_ids = [r[0] for r in s.execute(
            text("SELECT id FROM account WHERE tenant_id = :t LIMIT 6"), {"t": tenant_id}
        ).all()]

    model = _toy_model()
    as_of = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
    with tenant_session(tenant_id) as s:
        cfg = s.execute(
            text(
                "SELECT connected_sources, min_days_history, min_sources_with_data,"
                " tier_red_at, tier_amber_at, weekly_capacity FROM tenant_config WHERE tenant_id = :t"
            ),
            {"t": tenant_id},
        ).one()
        tenant_config = {
            "connected_sources": frozenset(cfg[0]), "min_days_history": cfg[1],
            "min_sources_with_data": cfg[2], "tier_red_at": float(cfg[3]), "tier_amber_at": float(cfg[4]),
        }
        for account_id in account_ids:
            score_and_persist(s, tenant_id=tenant_id, account_id=account_id, model=model,
                               model_version="test-model-v1", tenant_config=tenant_config, as_of=as_of)
    return tenant_id, as_of, cfg[5]


def test_queue_endpoint_returns_a_bounded_ordered_queue_with_required_fields():
    tenant_id, as_of, capacity = _setup_scored_queue()
    client = TestClient(app)
    resp = client.get(
        "/queue", params={"as_of": as_of.isoformat()},
        headers={"X-Tenant-Id": str(tenant_id)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "rows" in body and "below_cut" in body
    assert len(body["rows"]) <= capacity
    priorities = [r["priority"] for r in body["rows"]]
    assert priorities == sorted(priorities, reverse=True)
    for row in body["rows"]:
        for field in ("account_id", "tier", "health_score", "probability", "value_at_risk_cents",
                      "dominant_driver", "days_to_renewal", "priority", "confidence", "delta"):
            assert field in row


def test_queue_endpoint_rejects_an_unknown_tenant_cleanly():
    client = TestClient(app)
    resp = client.get(
        "/queue", params={"as_of": "2026-01-01T00:00:00Z"},
        headers={"X-Tenant-Id": str(uuid.uuid4())},
    )
    assert resp.status_code == 200
    assert resp.json()["rows"] == []
