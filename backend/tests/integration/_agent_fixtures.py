"""Shared seeding helper for the agent-cycle integration tests (T067-T074).

Each test that needs a scored-and-eligible account uses its own freshly
created tenant, never the real ``northwind`` estate -- a cycle-level test
depends on ``material_change``'s "is there a previous score" gate, and a
shared tenant accumulates ``score`` rows across every test that has ever run
a cycle against it in this process, making "this account drafts" an
execution-order-dependent assumption rather than a fact the test controls.
A fresh tenant per test is the fix, not a workaround.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from pulse.db.session import owner_session
from pulse.ml.panel import PanelRow
from pulse.ml.train import TrainedModel, time_based_split, train


def toy_support_model(seed: int) -> TrainedModel:
    """Trained to key heavily on ticket volume -- high support_tickets_28d
    predicts high risk, which is what every scenario here needs to be able
    to force deterministically via how many tickets a seeded account gets."""
    base = datetime(2024, 1, 1, tzinfo=UTC)
    rng = random.Random(seed)
    rows = []
    for i in range(300):
        risky = rng.random() < 0.3
        tickets = rng.uniform(8, 20) if risky else rng.uniform(0, 3)
        label = rng.random() < (0.8 if risky else 0.05)
        rows.append(PanelRow(
            f"a{i}", base + timedelta(weeks=i % 80),
            {"support_tickets_28d": tickets, "account_age_days": float(300 + i)}, label,
        ))
    return train(time_based_split(rows), seed=seed)


def seed_account(session, tenant_id: uuid.UUID, as_of: datetime, slug: str, *, n_tickets: int) -> uuid.UUID:
    account_id = uuid.uuid4()
    session.execute(
        text(
            "INSERT INTO account (id, tenant_id, external_ref, name, segment, signup_date,"
            " lifecycle_state, created_at) VALUES (:i,:t,:r,:n,'mid',:sd,'active', now())"
        ),
        {"i": account_id, "t": tenant_id, "r": slug, "n": slug.title(),
         "sd": (as_of - timedelta(days=400)).date()},
    )
    session.execute(
        text(
            "INSERT INTO identity_link (id, tenant_id, source, source_account_ref, account_id,"
            " method, confidence, first_seen_at) VALUES (:i,:t,'zendesk',:r,:a,'direct',1.0, now())"
        ),
        {"i": uuid.uuid4(), "t": tenant_id, "r": slug, "a": account_id},
    )
    session.execute(
        text(
            "INSERT INTO source_event (tenant_id, source, source_event_id, event_type, account_id,"
            " source_account_ref, occurred_at, received_at, payload)"
            " VALUES (:t,'stripe',:se,'billing.invoice_paid',:a,:r,:o,:rc, CAST(:p AS jsonb))"
        ),
        {"t": tenant_id, "se": f"{slug}-inv-1", "a": account_id, "r": slug,
         "o": as_of - timedelta(days=40), "rc": as_of - timedelta(days=40),
         "p": '{"invoice_ref": "inv1", "amount_cents": 100000}'},
    )
    for i in range(n_tickets):
        when = as_of - timedelta(days=20 - (i % 15))
        session.execute(
            text(
                "INSERT INTO source_event (tenant_id, source, source_event_id, event_type,"
                " account_id, source_account_ref, occurred_at, received_at, payload)"
                " VALUES (:t,'zendesk',:se,'support.ticket_created',:a,:r,:o,:rc, CAST(:p AS jsonb))"
            ),
            {"t": tenant_id, "se": f"{slug}-tkt-{i}", "a": account_id, "r": slug,
             "o": when, "rc": when,
             "p": f'{{"priority": "high", "ticket_ref": "{slug}-tkt-{i}"}}'},
        )
    return account_id


def seed_tenant(as_of: datetime) -> tuple[uuid.UUID, dict]:
    """A fresh tenant with sane tenant_config defaults and no accounts yet --
    callers add accounts with ``seed_account``."""
    tenant_id = uuid.uuid4()
    slug = f"agent-test-{uuid.uuid4().hex[:8]}"
    with owner_session() as s:
        s.execute(
            text("INSERT INTO tenant (id, slug, name, created_at) VALUES (:i,:s,:n, now())"),
            {"i": tenant_id, "s": slug, "n": slug},
        )
        s.execute(
            text(
                "INSERT INTO tenant_config (id, tenant_id, connected_sources, min_days_history,"
                " min_sources_with_data) VALUES (:i,:t, ARRAY['zendesk','stripe'], 30, 2)"
            ),
            {"i": uuid.uuid4(), "t": tenant_id},
        )
        row = s.execute(
            text(
                "SELECT connected_sources, min_days_history, min_sources_with_data,"
                " tier_red_at, tier_amber_at, material_delta, suppression_days,"
                " max_sends_per_cycle FROM tenant_config WHERE tenant_id = :t"
            ),
            {"t": tenant_id},
        ).one()
    tenant_config = {
        "connected_sources": frozenset(row[0]), "min_days_history": row[1],
        "min_sources_with_data": row[2], "tier_red_at": float(row[3]),
        "tier_amber_at": float(row[4]), "material_delta": float(row[5]),
        "suppression_days": row[6], "max_sends_per_cycle": row[7],
    }
    return tenant_id, tenant_config
