"""agent/cycle.py (T071): suppression and the per-tenant send rate limit are
both respected, and every suppression is recorded with its reason.

Uses a small, fully-controlled synthetic tenant rather than the real ingested
estate -- the scenario needs deterministic eligibility (a known dominant
driver, a known tier, a known number of equally-eligible accounts) that
heterogeneous real data and a toy model can't reliably guarantee run to run.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from pulse.agent.cycle import run_cycle
from pulse.agent.transport import RecordingTransport
from pulse.db.session import owner_session, tenant_session
from pulse.ml.panel import PanelRow
from pulse.ml.train import time_based_split, train

AS_OF = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)


def _toy_model():
    """Trained to key heavily on ticket volume, same shape as the other
    agent integration tests -- see test_scoring_service.py."""
    base = datetime(2024, 1, 1, tzinfo=UTC)
    rng = random.Random(21)
    rows = []
    for i in range(300):
        risky = rng.random() < 0.3
        tickets = rng.uniform(8, 20) if risky else rng.uniform(0, 3)
        label = rng.random() < (0.8 if risky else 0.05)
        rows.append(PanelRow(
            f"a{i}", base + timedelta(weeks=i % 80),
            {"support_tickets_28d": tickets, "account_age_days": float(300 + i)}, label,
        ))
    return train(time_based_split(rows), seed=21)


def _seed_account(s, tenant_id, slug: str, *, n_tickets: int) -> uuid.UUID:
    account_id = uuid.uuid4()
    s.execute(
        text(
            "INSERT INTO account (id, tenant_id, external_ref, name, segment, signup_date,"
            " lifecycle_state, created_at) VALUES (:i,:t,:r,:n,'mid',:sd,'active', now())"
        ),
        {"i": account_id, "t": tenant_id, "r": slug, "n": slug.title(),
         "sd": (AS_OF - timedelta(days=400)).date()},
    )
    s.execute(
        text(
            "INSERT INTO identity_link (id, tenant_id, source, source_account_ref, account_id,"
            " method, confidence, first_seen_at) VALUES (:i,:t,'zendesk',:r,:a,'direct',1.0, now())"
        ),
        {"i": uuid.uuid4(), "t": tenant_id, "r": slug, "a": account_id},
    )
    # Second connected source, purely for cov_sources_with_data >= 2.
    s.execute(
        text(
            "INSERT INTO source_event (tenant_id, source, source_event_id, event_type, account_id,"
            " source_account_ref, occurred_at, received_at, payload)"
            " VALUES (:t,'stripe',:se,'billing.invoice_paid',:a,:r,:o,:rc, CAST(:p AS jsonb))"
        ),
        {"t": tenant_id, "se": f"{slug}-inv-1", "a": account_id, "r": slug,
         "o": AS_OF - timedelta(days=40), "rc": AS_OF - timedelta(days=40),
         "p": '{"invoice_ref": "inv1", "amount_cents": 100000}'},
    )
    for i in range(n_tickets):
        when = AS_OF - timedelta(days=20 - (i % 15))
        s.execute(
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


def _seed_tenant():
    tenant_id = uuid.uuid4()
    slug = f"ratelimit-{uuid.uuid4().hex[:8]}"
    with owner_session() as s:
        s.execute(
            text("INSERT INTO tenant (id, slug, name, created_at) VALUES (:i,:s,:n, now())"),
            {"i": tenant_id, "s": slug, "n": slug},
        )
        s.execute(
            text(
                "INSERT INTO tenant_config (id, tenant_id, connected_sources, min_days_history,"
                " min_sources_with_data, suppression_days, max_sends_per_cycle)"
                " VALUES (:i,:t, ARRAY['zendesk','stripe'], 30, 2, 14, 1)"
            ),
            {"i": uuid.uuid4(), "t": tenant_id},
        )
        suppressed_id = _seed_account(s, tenant_id, "suppressed-acct", n_tickets=15)
        send_a = _seed_account(s, tenant_id, "send-a", n_tickets=15)
        send_b = _seed_account(s, tenant_id, "send-b", n_tickets=15)
        s.execute(
            text(
                "INSERT INTO suppression (id, tenant_id, account_id, reason, created_at, expires_at)"
                " VALUES (:i,:t,:a,'customer asked to be left alone', now(), :x)"
            ),
            {"i": uuid.uuid4(), "t": tenant_id, "a": suppressed_id, "x": AS_OF + timedelta(days=365)},
        )
        # Deliverable tenant: verified sender, demo mode with a test inbox, a contact per account. The rate limit
        # is the thing under test, so nothing else may block these sends.
        s.execute(text("UPDATE tenant_config SET outbound_enabled = true, sender_address = 'csm@example.test',"
                       " sender_verified = true, demo_mode = true, test_inbox = 'demo@example.test'"
                       " WHERE tenant_id = :t"), {"t": tenant_id})
        s.execute(text("UPDATE account SET contact_email = external_ref || '@acme.example.test' WHERE tenant_id = :t"),
                  {"t": tenant_id})
        s.execute(
            text(
                "INSERT INTO play_allowlist (id, tenant_id, play_key, auto_send, enabled_at)"
                " VALUES (:i,:t,'support_recovery', true, now())"
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
    return tenant_id, tenant_config, suppressed_id, send_a, send_b


def test_suppressed_account_is_declined_with_reason_and_rate_limit_caps_sends():
    tenant_id, tenant_config, suppressed_id, send_a, send_b = _seed_tenant()
    model = _toy_model()
    transport = RecordingTransport()

    with tenant_session(tenant_id) as s:
        result = run_cycle(
            s, tenant_id=tenant_id, model=model, model_version="test-suppression",
            tenant_config=tenant_config, as_of=AS_OF, transport=transport,
        )

    declined_reasons = {d["account_id"]: d["reason"] for d in result.decisions_declined}
    assert declined_reasons.get(str(suppressed_id)) == "suppressed"

    with owner_session() as s:
        rows = {
            row["account_id"]: row for row in s.execute(
                text(
                    "SELECT account_id, state, state_reason FROM action"
                    " WHERE agent_run_id = :r AND account_id IN (:a, :b)"
                ),
                {"r": result.run_id, "a": send_a, "b": send_b},
            ).mappings().all()
        }

    assert len(rows) == 2, "both candidate accounts must have produced an action"
    states = {r["state"] for r in rows.values()}
    assert states == {"sent", "drafted"}, "exactly one sent, one capped by the rate limit"
    capped = next(r for r in rows.values() if r["state"] == "drafted")
    assert capped["state_reason"] == "rate_limit_reached"
    assert len(transport.sent) == 1
    assert result.stage_counts["sent"] == 1
