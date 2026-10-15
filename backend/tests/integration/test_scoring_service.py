"""scoring/service.py: compute features, predict, calibrate, attribute, tier,
gate confidence, rank, persist with full lineage (T050). Exercised against a
real account from the ingested dataset so the whole pipeline -- DB round trip
included -- is proven, not just its pieces in isolation.
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
    rng = random.Random(4)
    rows = []
    for i in range(300):
        risky = rng.random() < 0.3
        tickets = rng.uniform(8, 20) if risky else rng.uniform(0, 3)
        label = rng.random() < (0.8 if risky else 0.05)
        rows.append(PanelRow(
            f"a{i}", base + timedelta(weeks=i % 80),
            {"support_tickets_28d": tickets, "account_age_days": float(300 + i)}, label,
        ))
    return train(time_based_split(rows), seed=2)


def _northwind_account_with_history():
    with owner_session() as s:
        tenant_id = s.execute(text("SELECT id FROM tenant WHERE slug = 'northwind'")).scalar()
        account_id = s.execute(
            text(
                "SELECT a.id FROM account a JOIN source_event e ON e.account_id = a.id"
                " WHERE a.tenant_id = :t GROUP BY a.id HAVING count(*) > 100 LIMIT 1"
            ),
            {"t": tenant_id},
        ).scalar()
    return tenant_id, account_id


def test_score_and_persist_writes_a_feature_snapshot_and_a_score_with_resolvable_lineage():
    tenant_id, account_id = _northwind_account_with_history()
    model = _toy_model()
    as_of = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)

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

        snapshot_row = s.execute(
            text("SELECT id, values, evidence FROM feature_snapshot WHERE id = :i"),
            {"i": scored.feature_snapshot_id},
        ).mappings().one()
        score_row = s.execute(
            text(
                "SELECT probability, tier, feature_snapshot_id, contributions, ranking_math"
                " FROM score WHERE account_id = :a AND as_of = :ao"
            ),
            {"a": account_id, "ao": as_of},
        ).mappings().one()

    assert score_row["feature_snapshot_id"] == snapshot_row["id"]
    assert score_row["tier"] in ("red", "amber", "green", "abstain")
    assert 0.0 <= float(score_row["probability"]) <= 1.0
    assert isinstance(score_row["contributions"], dict)
    assert isinstance(score_row["ranking_math"], dict)
    assert isinstance(snapshot_row["values"], dict)
    assert isinstance(snapshot_row["evidence"], dict)


def test_score_and_persist_is_idempotent_per_account_and_as_of():
    """Re-running the same as_of must not create a second Score row -- the
    unique constraint on (tenant_id, account_id, as_of) is the control."""
    tenant_id, account_id = _northwind_account_with_history()
    model = _toy_model()
    as_of = datetime(2026, 5, 1, 9, 0, tzinfo=UTC)

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
                           model_version="test-model-v1", tenant_config=tenant_config, as_of=as_of)

    with tenant_session(tenant_id) as s:
        score_and_persist(s, tenant_id=tenant_id, account_id=account_id, model=model,
                           model_version="test-model-v1", tenant_config=tenant_config, as_of=as_of)
        count = s.execute(
            text("SELECT count(*) FROM score WHERE account_id = :a AND as_of = :ao"),
            {"a": account_id, "ao": as_of},
        ).scalar()
    assert count == 1
