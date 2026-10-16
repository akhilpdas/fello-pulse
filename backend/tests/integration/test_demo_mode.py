"""T262 (FR-020, SC-008): in demo mode nothing reaches a real customer. A message goes only to the tenant's
test inbox -- or, with no inbox, is captured without any delivery -- and the action says it was redirected.
Demo mode is the default for every tenant, so a database built by the generator cannot email anyone by accident.

Names the production change that makes it fail: the redirect/capture rules in ``pulse.agent.delivery``.
"""

from __future__ import annotations

import email
import email.header
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

AS_OF = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
CONTACT = "real.customer@acme.example.com"
INBOX = "demo-inbox@pulse.example.com"


@pytest.fixture(autouse=True)
def _reset():
    yield
    app.dependency_overrides.pop(deps.get_transport, None)


def _world(*, inbox=INBOX, demo=True, set_demo_explicitly=True):
    tenant_id, _ = seed_tenant(AS_OF)
    action_id = uuid.uuid4()
    with owner_session() as s:
        account_id = seed_account(s, tenant_id, AS_OF, "demo-a", n_tickets=1)
        s.execute(text("UPDATE account SET contact_email = :c WHERE id = :a"), {"c": CONTACT, "a": account_id})
        sets = "outbound_enabled = true, sender_address = 'csm@northwind.example.com', sender_verified = true, test_inbox = :i"
        if set_demo_explicitly:
            sets += ", demo_mode = :d"
        s.execute(text(f"UPDATE tenant_config SET {sets} WHERE tenant_id = :t"), {"i": inbox, "d": demo, "t": tenant_id})
        s.execute(text("INSERT INTO action (id, tenant_id, account_id, play_key, subject, body)"
                       " VALUES (:i,:t,:a,'support_recovery','Checking in','Hello')"),
                  {"i": action_id, "t": tenant_id, "a": account_id})
    return tenant_id, action_id


def _approve(tenant_id, action_id):
    return TestClient(app).post(f"/actions/{action_id}/approve", json={}, headers=auth_headers(tenant_id))


def _real(sink):
    app.dependency_overrides[deps.get_transport] = lambda: SmtpTransport(
        host="127.0.0.1", port=sink.port, starttls=False, timeout=2.0)


def test_demo_mode_is_the_default_for_a_new_tenant():
    tenant_id, _ = seed_tenant(AS_OF)
    with owner_session() as s:
        assert s.execute(text("SELECT demo_mode FROM tenant_config WHERE tenant_id = :t"), {"t": tenant_id}).scalar() is True


def test_with_a_test_inbox_the_message_goes_only_there_and_says_who_it_was_for():
    tenant_id, action_id = _world()
    with SmtpSink() as sink:
        _real(sink)
        r = _approve(tenant_id, action_id).json()
        assert r["state"] == "sent" and r["redirected_to"] == INBOX
        assert [m["rcpt_to"] for m in sink.messages] == [[INBOX]]
        assert CONTACT not in sink.messages[0]["mail_from"] + "".join(sink.messages[0]["rcpt_to"])
        subject = str(email.header.make_header(email.header.decode_header(
            email.message_from_string(sink.messages[0]["data"])["Subject"])))
        assert subject == f"[DEMO → {CONTACT}] Checking in"  # decoded as a mail client would; says who it was for


def test_with_no_test_inbox_nothing_is_delivered_at_all_and_it_is_recorded_as_captured():
    tenant_id, action_id = _world(inbox=None)
    with SmtpSink() as sink:
        _real(sink)
        r = _approve(tenant_id, action_id).json()
        assert sink.connections == 0, "demo mode with no inbox must not open a connection"
        assert r["state"] == "sent" and r["redirected_to"].startswith("captured")
        assert "demo" in r["state_reason"].lower()


def test_a_tenant_that_left_demo_mode_delivers_to_the_real_contact():
    tenant_id, action_id = _world(demo=False)
    with SmtpSink() as sink:
        _real(sink)
        r = _approve(tenant_id, action_id).json()
        assert r["state"] == "sent" and r["redirected_to"] is None
        assert [m["rcpt_to"] for m in sink.messages] == [[CONTACT]]


def test_a_tenant_that_never_chose_defaults_to_demo_and_does_not_email_the_customer():
    tenant_id, action_id = _world(set_demo_explicitly=False)
    with SmtpSink() as sink:
        _real(sink)
        _approve(tenant_id, action_id)
        assert all(CONTACT not in "".join(m["rcpt_to"]) for m in sink.messages)
