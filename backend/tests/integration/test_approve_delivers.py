"""T260 (FR-013..FR-018, SC-006, SC-007): approving a draft really delivers it -- once -- through the tenant's
sender, and every way of *not* delivering is its own state with zero network traffic.

Names the production change that makes it fail: ``routers/actions.py::approve`` replaced its placeholder
recipient (``csm+<id>@example.test``) and unconditional ``sent`` with the send gate, a real transport,
an atomic claim, and the outcome classification.
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
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
SENDER = "csm@northwind.example.com"
CONTACT = "sofia.reyes@acme.example.com"


@pytest.fixture(autouse=True)
def _reset_overrides():
    yield
    app.dependency_overrides.pop(deps.get_transport, None)


def _world(*, enabled=True, sender=SENDER, verified=True, contact=CONTACT, opted_out=False):
    tenant_id, _ = seed_tenant(AS_OF)
    action_id = uuid.uuid4()
    with owner_session() as s:
        account_id = seed_account(s, tenant_id, AS_OF, "deliver-a", n_tickets=1)
        s.execute(text("UPDATE account SET contact_email = :c, contact_name = 'Sofia Reyes' WHERE id = :a"),
                  {"c": contact, "a": account_id})
        s.execute(text("UPDATE tenant_config SET outbound_enabled = :e, sender_address = :s, sender_verified = :v,"
                       " demo_mode = false WHERE tenant_id = :t"),
                  {"e": enabled, "s": sender, "v": verified, "t": tenant_id})
        s.execute(text("INSERT INTO action (id, tenant_id, account_id, play_key, subject, body)"
                       " VALUES (:i,:t,:a,'support_recovery','Checking in','Hello Sofia')"),
                  {"i": action_id, "t": tenant_id, "a": account_id})
        if opted_out:
            s.execute(text("INSERT INTO contact_opt_out (id, tenant_id, email) VALUES (:i,:t,:e)"),
                      {"i": uuid.uuid4(), "t": tenant_id, "e": CONTACT.upper()})  # matched case-insensitively
    return tenant_id, action_id


def _use(sink: SmtpSink, timeout=2.0):
    app.dependency_overrides[deps.get_transport] = lambda: SmtpTransport(
        host="127.0.0.1", port=sink.port, starttls=False, timeout=timeout)


def _approve(tenant_id, action_id, client=None):
    return (client or TestClient(app)).post(f"/actions/{action_id}/approve", json={}, headers=auth_headers(tenant_id))


def _row(action_id) -> dict:
    with owner_session() as s:
        return dict(s.execute(text("SELECT state, state_reason, attempts, sent_at, provider_message_id,"
                                   " delivery_error FROM action WHERE id = :i"), {"i": action_id}).mappings().one())


def test_an_approved_draft_is_delivered_once_to_the_contact_from_the_tenants_sender():
    tenant_id, action_id = _world()
    with SmtpSink() as sink:
        _use(sink)
        r = _approve(tenant_id, action_id)
        assert r.status_code == 200 and r.json()["state"] == "sent"
        assert len(sink.messages) == 1
        m = sink.messages[0]
        assert (m["mail_from"], m["rcpt_to"]) == (SENDER, [CONTACT])
        assert f"<{action_id}@northwind.example.com>" in m["data"]  # Message-ID derived from the action
    row = _row(action_id)
    assert row["state"] == "sent" and row["attempts"] == 1 and row["sent_at"] and row["provider_message_id"]


@pytest.mark.parametrize("kwargs,state", [
    (dict(enabled=False), "outbound_disabled"),
    (dict(sender=None), "not_configured"),
    (dict(verified=False), "not_configured"),
    (dict(contact=None), "no_recipient"),
    (dict(opted_out=True), "opted_out"),
])
def test_every_blocked_case_has_its_own_state_and_makes_no_network_call(kwargs, state):
    tenant_id, action_id = _world(**kwargs)
    with SmtpSink() as sink:
        _use(sink)
        r = _approve(tenant_id, action_id)
        assert r.status_code == 200 and r.json()["state"] == state and r.json()["state_reason"]
        assert sink.connections == 0, "a blocked send must not even open a connection"
    assert _row(action_id)["state"] == state


def test_approving_twice_delivers_once_and_the_second_call_reports_the_first_result():
    tenant_id, action_id = _world()
    with SmtpSink() as sink:
        _use(sink)
        first, second = _approve(tenant_id, action_id), _approve(tenant_id, action_id)
        assert first.status_code == second.status_code == 200
        assert first.json()["state"] == second.json()["state"] == "sent"
        assert len(sink.messages) == 1


def test_two_simultaneous_approvals_deliver_exactly_once():
    tenant_id, action_id = _world()
    with SmtpSink() as sink:
        _use(sink)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: _approve(tenant_id, action_id, TestClient(app)), range(2)))
        assert [r.status_code for r in results] == [200, 200]
        assert len(sink.messages) == 1


def test_transient_failures_are_retried_and_the_attempt_count_is_recorded():
    tenant_id, action_id = _world()
    with SmtpSink(mode="tempfail_rcpt", fail_first=2) as sink:
        _use(sink)
        assert _approve(tenant_id, action_id).json()["state"] == "sent"
        assert len(sink.messages) == 1
    assert _row(action_id)["attempts"] == 3


def test_a_permanent_refusal_is_send_failed_with_the_reason_and_is_not_retried():
    tenant_id, action_id = _world()
    with SmtpSink(mode="reject_rcpt") as sink:
        _use(sink)
        r = _approve(tenant_id, action_id).json()
        assert r["state"] == "send_failed" and "550" in r["state_reason"]
        assert sink.rcpt_attempts == 1
    assert _row(action_id)["attempts"] == 1 and "550" in _row(action_id)["delivery_error"]


def test_an_ambiguous_outcome_is_send_unconfirmed_and_approving_again_never_resends():
    tenant_id, action_id = _world()
    with SmtpSink(mode="hang_after_data") as sink:
        _use(sink, timeout=0.6)
        assert _approve(tenant_id, action_id).json()["state"] == "send_unconfirmed"
        assert _approve(tenant_id, action_id).json()["state"] == "send_unconfirmed"
        assert sink.data_attempts == 1, "a second delivery attempt could have emailed the customer twice"


def test_config_is_checked_at_send_time_so_fixing_it_and_approving_again_delivers():
    tenant_id, action_id = _world(enabled=False)
    with SmtpSink() as sink:
        _use(sink)
        assert _approve(tenant_id, action_id).json()["state"] == "outbound_disabled"
        assert len(sink.messages) == 0
        with owner_session() as s:
            s.execute(text("UPDATE tenant_config SET outbound_enabled = true WHERE tenant_id = :t"), {"t": tenant_id})
        assert _approve(tenant_id, action_id).json()["state"] == "sent"
        assert len(sink.messages) == 1


def test_a_rejected_draft_cannot_be_approved_afterwards():
    tenant_id, action_id = _world()
    c = TestClient(app)
    c.post(f"/actions/{action_id}/reject", json={"reason": "no"}, headers=auth_headers(tenant_id))
    assert _approve(tenant_id, action_id, c).status_code == 409
