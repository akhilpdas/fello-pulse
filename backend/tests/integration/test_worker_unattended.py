"""agent/cycle.py + agent/worker.py (T065, T066, T067): one full cycle, zero
human input, advances every stage and writes a run record. Exercised against
a real ingested account so the DB round trip is proven, not just the stage
logic in isolation.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from pulse.agent.transport import RecordingTransport
from pulse.agent.worker import run_once
from pulse.db.session import owner_session
from pulse.ml.panel import PanelRow
from pulse.ml.train import time_based_split, train


def _toy_model():
    base = datetime(2024, 1, 1, tzinfo=UTC)
    rng = random.Random(9)
    rows = []
    for i in range(300):
        risky = rng.random() < 0.3
        tickets = rng.uniform(8, 20) if risky else rng.uniform(0, 3)
        label = rng.random() < (0.8 if risky else 0.05)
        rows.append(PanelRow(
            f"a{i}", base + timedelta(weeks=i % 80),
            {"support_tickets_28d": tickets, "account_age_days": float(300 + i)}, label,
        ))
    return train(time_based_split(rows), seed=11)


def _northwind():
    with owner_session() as s:
        tenant_id = s.execute(text("SELECT id FROM tenant WHERE slug = 'northwind'")).scalar()
    return tenant_id


def _tenant_config(tenant_id):
    with owner_session() as s:
        row = s.execute(
            text(
                "SELECT connected_sources, min_days_history, min_sources_with_data,"
                " tier_red_at, tier_amber_at, material_delta, suppression_days,"
                " max_sends_per_cycle FROM tenant_config WHERE tenant_id = :t"
            ),
            {"t": tenant_id},
        ).one()
    return {
        "connected_sources": frozenset(row[0]), "min_days_history": row[1],
        "min_sources_with_data": row[2], "tier_red_at": float(row[3]),
        "tier_amber_at": float(row[4]), "material_delta": float(row[5]),
        "suppression_days": row[6], "max_sends_per_cycle": row[7],
    }


def test_one_tick_scores_every_active_account_and_writes_a_run_record():
    tenant_id = _northwind()
    model = _toy_model()
    tenant_config = _tenant_config(tenant_id)
    as_of = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)
    transport = RecordingTransport()

    result = run_once(
        tenant_id=tenant_id, model=model, model_version="test-worker-v1",
        tenant_config=tenant_config, as_of=as_of, transport=transport,
        worker_id="test-worker", lease_seconds=300,
    )

    assert result is not None
    with owner_session() as s:
        run_row = s.execute(
            text("SELECT status, stage_counts, decisions_declined FROM agent_run WHERE id = :i"),
            {"i": result.run_id},
        ).mappings().one()
        n_accounts = s.execute(
            text("SELECT count(*) FROM account WHERE tenant_id = :t AND lifecycle_state = 'active'"),
            {"t": tenant_id},
        ).scalar()

    assert run_row["status"] == "succeeded"
    assert run_row["stage_counts"]["scored"] == n_accounts
    # No human triggered anything, and no allowlist exists for 'northwind' --
    # declined decisions are still recorded with a reason, never silently
    # dropped (constitution Principle III).
    assert isinstance(run_row["decisions_declined"], list)
    for d in run_row["decisions_declined"]:
        assert d["reason"]
