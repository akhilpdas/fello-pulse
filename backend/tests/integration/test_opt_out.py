"""T266 (FR-016): a recipient who asked us to stop is never emailed again -- on a human approval or an
unattended send -- and every message tells them how to ask. Opt-outs are operator-managed and matched
without regard to case.

Names the production change that makes it fail: ``/admin/opt-outs`` and the footer added in delivery.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import pulse.api.deps as deps
from pulse.agent.transport import SmtpTransport
from pulse.api.main import app
from pulse.db.session import owner_session
from pulse.tools.smtp_sink import SmtpSink
from tests.auth_helpers import auth_headers
from tests.integration._agent_fixtures import seed_account, seed_tenant

AS_OF = datetime(2026, 10, 1, tzinfo=UTC)
CONTACT = "sofia.reyes@acme.example.com"


@pytest.fixture(autouse=True)
def _reset():
    yield
    app.dependency_overrides.pop(deps.get_transport, None)


def _tenant_with_action():
    tenant_id, _ = seed_tenant(AS_OF)
    action_id = uuid.uuid4()
    with owner_session() as s:
        acct = seed_account(s, tenant_id, AS_OF, "optout-a", n_tickets=1)
        s.execute(text("UPDATE account SET contact_email = :c WHERE id = :a"), {"c": CONTACT, "a": acct})
        s.execute(text("UPDATE tenant_config SET outbound_enabled = true, sender_address='csm@northwind.example.com',"
                       " sender_verified = true, demo_mode = false WHERE tenant_id = :t"), {"t": tenant_id})
        s.execute(text("INSERT INTO action (id, tenant_id, account_id, play_key, subject, body)"
                       " VALUES (:i,:t,:a,'support_recovery','Checking in','Hello Sofia')"),
                  {"i": action_id, "t": tenant_id, "a": acct})
    return tenant_id, action_id


def test_opt_outs_can_be_added_listed_and_removed_by_an_operator_only():
    tenant_id, _ = seed_tenant(AS_OF)
    c, op = TestClient(app), auth_headers(tenant_id)
    assert c.post("/admin/opt-outs", json={"email": CONTACT}, headers=auth_headers(tenant_id, role="csm")).status_code == 403
    r = c.post("/admin/opt-outs", json={"email": "Sofia.Reyes@Acme.example.com", "reason": "replied STOP"}, headers=op)
    assert r.status_code == 201
    assert [x["email"] for x in c.get("/admin/opt-outs", headers=op).json()] == [CONTACT]  # stored lower-case
    assert c.post("/admin/opt-outs", json={"email": CONTACT}, headers=op).status_code in (200, 201)  # idempotent
    assert len(c.get("/admin/opt-outs", headers=op).json()) == 1
    assert c.delete(f"/admin/opt-outs/{r.json()['id']}", headers=op).status_code == 200
    assert c.get("/admin/opt-outs", headers=op).json() == []
    assert c.post("/admin/opt-outs", json={"email": "not-an-email"}, headers=op).status_code == 422


def test_an_opt_out_in_another_tenant_does_not_block_this_tenants_sends():
    mine, action_id = _tenant_with_action()
    other, _ = seed_tenant(AS_OF)
    TestClient(app).post("/admin/opt-outs", json={"email": CONTACT}, headers=auth_headers(other))
    with SmtpSink() as sink:
        app.dependency_overrides[deps.get_transport] = lambda: SmtpTransport(host="127.0.0.1", port=sink.port, starttls=False)
        r = TestClient(app).post(f"/actions/{action_id}/approve", json={}, headers=auth_headers(mine))
        assert r.json()["state"] == "sent" and len(sink.messages) == 1


def test_every_delivered_message_tells_the_recipient_how_to_opt_out():
    tenant_id, action_id = _tenant_with_action()
    with SmtpSink() as sink:
        app.dependency_overrides[deps.get_transport] = lambda: SmtpTransport(host="127.0.0.1", port=sink.port, starttls=False)
        TestClient(app).post(f"/actions/{action_id}/approve", json={}, headers=auth_headers(tenant_id))
        data = sink.messages[0]["data"]
        assert "Hello Sofia" in data and "reply to this email" in data and "stop" in data.lower()
    with owner_session() as s:  # the stored draft is the human-approved text, without the footer
        assert s.execute(text("SELECT body FROM action WHERE id = :i"), {"i": action_id}).scalar() == "Hello Sofia"
