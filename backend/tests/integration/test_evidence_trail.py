"""T058: no score persists without resolvable evidence, and its contributions
reconcile to the model's own output -- constitution Principle V ("nothing
unexplained reaches a human")."""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import text

from pulse.api.main import app
from pulse.db.session import owner_session, tenant_session
from pulse.ml.explain import expected_value
from pulse.ml.panel import PanelRow
from pulse.ml.train import time_based_split, train
from pulse.scoring.service import score_and_persist
from tests.auth_helpers import auth_headers


def _toy_model():
    base = datetime(2024, 1, 1, tzinfo=UTC)
    rng = random.Random(23)
    rows = [
        PanelRow(f"a{i}", base + timedelta(weeks=i % 80),
                 {"support_tickets_28d": rng.uniform(0, 20), "account_age_days": float(300 + i)},
                 rng.random() < 0.15)
        for i in range(400)
    ]
    return train(time_based_split(rows), seed=12)


def _northwind_account_with_history():
    with owner_session() as s:
        tenant_id = s.execute(text("SELECT id FROM tenant WHERE slug = 'northwind'")).scalar()
        account_id = s.execute(
            text(
                "SELECT a.id FROM account a JOIN source_event e ON e.account_id = a.id"
                " WHERE a.tenant_id = :t GROUP BY a.id HAVING count(*) > 100 ORDER BY a.external_ref LIMIT 1"
            ),
            {"t": tenant_id},
        ).scalar()
    return tenant_id, account_id


def test_every_persisted_scores_evidence_is_resolvable_to_real_source_records():
    tenant_id, account_id = _northwind_account_with_history()
    model = _toy_model()
    as_of = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)

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
        scored = score_and_persist(s, tenant_id=tenant_id, account_id=account_id, model=model,
                                    model_version="test-model-v1", tenant_config=tenant_config, as_of=as_of)

    client = TestClient(app)
    detail = client.get(
        f"/accounts/{account_id}", params={"as_of": as_of.isoformat()},
        headers=auth_headers(tenant_id),
    ).json()

    assert detail["confidence"] == scored.confidence
    all_evidence_ids = [i for ids in detail["evidence"].values() for i in ids]
    assert len(all_evidence_ids) > 0

    evidence_resp = client.get(
        f"/accounts/{account_id}/evidence", params={"event_ids": all_evidence_ids[:5]},
        headers=auth_headers(tenant_id),
    )
    assert evidence_resp.status_code == 200
    events = evidence_resp.json()["events"]
    assert len(events) == len(set(all_evidence_ids[:5]))
    for e in events:
        assert e["payload"] is not None
        assert e["source"] in ("product", "zendesk", "gmail", "stripe", "salesforce")


def test_contributions_reconcile_to_the_models_own_output():
    tenant_id, account_id = _northwind_account_with_history()
    model = _toy_model()
    as_of = datetime(2026, 8, 8, 9, 0, tzinfo=UTC)

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

        row = s.execute(
            text("SELECT probability_raw, contributions FROM score WHERE account_id = :a AND as_of = :ao"),
            {"a": account_id, "ao": as_of},
        ).mappings().one()

    raw_prob = float(row["probability_raw"])
    reconstructed_logit = sum(row["contributions"].values()) + expected_value(model)
    actual_logit = math.log(raw_prob / (1 - raw_prob))
    # The attribution is exact in memory (tests/unit/test_explain_reconciles_exactly.py); what is compared here is the
    # *stored* probability, which has 5 decimals (Numeric(6,5)). A half-unit of rounding, 5e-6, moves the log-odds by
    # up to 5e-6 / (p(1-p)) -- about 3e-4 at p = 0.016 -- so the bound must follow p instead of being a constant that
    # only holds for probabilities near 0.5 (which is how this test once passed on one account and failed on another).
    rounding_bound = 0.5e-5 / (raw_prob * (1 - raw_prob))
    assert abs(reconstructed_logit - actual_logit) <= rounding_bound * 1.01 + 1e-9, (
        f"off by {abs(reconstructed_logit - actual_logit):.2e}, more than storage rounding explains ({rounding_bound:.2e})")
