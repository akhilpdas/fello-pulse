"""T081: a tenant with no Gmail connected scores with email features *absent*
(None), never zero -- and the same account shape in a tenant that does have Gmail
connected gets a real 0.0. Absence is a fact about coverage, not about the customer.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import text

from pulse.db.session import owner_session, tenant_session
from pulse.scoring.service import score_and_persist
from tests.integration._agent_fixtures import seed_account, seed_tenant, toy_support_model

AS_OF = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def _score(connected: list[str]) -> dict:
    tenant_id, cfg = seed_tenant(AS_OF)
    with owner_session() as s:
        s.execute(text("UPDATE tenant_config SET connected_sources = CAST(:c AS text[])"
                       " WHERE tenant_id = :t"), {"c": connected, "t": tenant_id})
        account_id = seed_account(s, tenant_id, AS_OF, "ms-a", n_tickets=2)
    cfg = {**cfg, "connected_sources": frozenset(connected)}
    with tenant_session(tenant_id) as s:
        score_and_persist(s, tenant_id=tenant_id, account_id=account_id,
                          model=toy_support_model(3), model_version="test", tenant_config=cfg,
                          as_of=AS_OF)
        raw = s.execute(text("SELECT values FROM feature_snapshot WHERE account_id = :a"),
                        {"a": account_id}).scalar()
    return raw if isinstance(raw, dict) else json.loads(raw)


def test_no_gmail_tenant_persists_email_features_as_absent_not_zero():
    values = _score(["zendesk", "stripe"])
    assert values["email_inbound_28d"] is None
    assert values["support_tickets_28d"] == 2.0


def test_gmail_tenant_with_no_email_persists_zero():
    values = _score(["zendesk", "stripe", "gmail"])
    assert values["email_inbound_28d"] == 0.0
