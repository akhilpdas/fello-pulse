"""T079 (FR-012): per-tenant, per-source coverage -- what is connected, what has
actually landed, and how much of it could not be tied to an account."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import text

from pulse.api.main import app
from pulse.db.session import owner_session
from tests.integration._agent_fixtures import seed_account, seed_tenant

AS_OF = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def test_coverage_reports_connected_flag_event_counts_and_last_received_per_source():
    tenant_id, _ = seed_tenant(AS_OF)  # connected: zendesk, stripe
    with owner_session() as s:
        seed_account(s, tenant_id, AS_OF, "cov-a", n_tickets=3)
        op = uuid.uuid4()
        s.execute(text("INSERT INTO app_user (id, tenant_id, email, name, role)"
                       " VALUES (:i,:t,'o@example.test','O','operator')"), {"i": op, "t": tenant_id})
    r = TestClient(app).get("/admin/coverage",
                            headers={"X-Tenant-Id": str(tenant_id), "X-User-Id": str(op)})
    assert r.status_code == 200
    by = {row["source"]: row for row in r.json()}
    assert set(by) == {"salesforce", "gmail", "zendesk", "product", "stripe"}
    assert by["zendesk"]["connected"] is True and by["zendesk"]["events"] == 3
    assert by["stripe"]["events"] == 1
    assert by["gmail"]["connected"] is False and by["gmail"]["events"] == 0
    assert by["gmail"]["last_received_at"] is None
    assert by["zendesk"]["last_received_at"] is not None
