"""T268 (constitution III, FR-019, SC-008): real delivery does not loosen the autonomy boundary. With a real
SMTP transport behind the unattended cycle: an un-allowlisted play still cannot self-send; an allowlisted
one goes through the *same* send gate as a human approval (switched off, no contact, opted out -> blocked, no
network traffic, reason recorded); the per-cycle rate limit holds; and in demo mode nothing reaches a real contact.

Names the production change that makes it fail: ``run_cycle`` delivered auto-sends through
``pulse.agent.delivery.deliver`` instead of calling the transport directly with a placeholder address.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import text

from pulse.agent.cycle import run_cycle
from pulse.agent.transport import SmtpTransport
from pulse.db.session import owner_session, tenant_session
from pulse.tools.smtp_sink import SmtpSink
from tests.integration._agent_fixtures import seed_account, seed_tenant, toy_support_model

AS_OF = datetime(2026, 7, 8, 9, 0, tzinfo=UTC)
INBOX = "demo-inbox@pulse.example.com"


def _world(*, allowlisted=True, enabled=True, demo=False, contacts=("a@acme.example.com",), opt_out=(), max_sends=25):
    tenant_id, cfg = seed_tenant(AS_OF)
    cfg = {**cfg, "max_sends_per_cycle": max_sends}
    with owner_session() as s:
        s.execute(text("UPDATE tenant_config SET outbound_enabled=:e, sender_address='csm@northwind.example.com',"
                       " sender_verified=true, demo_mode=:d, test_inbox=:i, max_sends_per_cycle=:m WHERE tenant_id=:t"),
                  {"e": enabled, "d": demo, "i": INBOX, "m": max_sends, "t": tenant_id})
        for n, contact in enumerate(contacts):
            acct = seed_account(s, tenant_id, AS_OF, f"auto-{n}", n_tickets=15)
            s.execute(text("UPDATE account SET contact_email = :c WHERE id = :a"), {"c": contact, "a": acct})
        for email in opt_out:
            s.execute(text("INSERT INTO contact_opt_out (id, tenant_id, email) VALUES (:i,:t,:e)"),
                      {"i": uuid.uuid4(), "t": tenant_id, "e": email})
        if allowlisted:
            s.execute(text("INSERT INTO play_allowlist (id, tenant_id, play_key, auto_send, enabled_at)"
                           " VALUES (:i,:t,'support_recovery', true, now())"), {"i": uuid.uuid4(), "t": tenant_id})
    return tenant_id, cfg


def _cycle(tenant_id, cfg, sink):
    transport = SmtpTransport(host="127.0.0.1", port=sink.port, starttls=False, timeout=2.0)
    with tenant_session(tenant_id) as s:
        return run_cycle(s, tenant_id=tenant_id, model=toy_support_model(13), model_version="t",
                         tenant_config=cfg, as_of=AS_OF, transport=transport)


def _states(run_id) -> dict:
    with owner_session() as s:
        rows = s.execute(text("SELECT state, state_reason FROM action WHERE agent_run_id = :r"), {"r": run_id}).all()
    return {state: reason for state, reason in rows}


def test_an_allowlisted_play_is_delivered_to_the_contact_through_the_gate():
    tenant_id, cfg = _world()
    with SmtpSink() as sink:
        result = _cycle(tenant_id, cfg, sink)
        assert result.stage_counts["sent"] == 1
        assert [m["rcpt_to"] for m in sink.messages] == [["a@acme.example.com"]]
        assert _states(result.run_id).keys() == {"sent"}


def test_an_un_allowlisted_play_cannot_self_send_even_with_real_delivery_available():
    tenant_id, cfg = _world(allowlisted=False)
    with SmtpSink() as sink:
        result = _cycle(tenant_id, cfg, sink)
        assert sink.connections == 0 and result.stage_counts["sent"] == 0
        assert _states(result.run_id) == {"drafted": "not_allowlisted_for_auto_send"}


def test_blocked_sends_are_recorded_with_their_reason_and_open_no_connection():
    for kwargs, state in [(dict(enabled=False), "outbound_disabled"),
                          (dict(contacts=(None,)), "no_recipient"),
                          (dict(opt_out=("A@acme.example.com",)), "opted_out")]:
        tenant_id, cfg = _world(**kwargs)
        with SmtpSink() as sink:
            result = _cycle(tenant_id, cfg, sink)
            assert sink.connections == 0, state
            assert state in _states(result.run_id), (state, _states(result.run_id))
            assert any(d["reason"].startswith("send_blocked") and state in d["reason"]
                       for d in result.decisions_declined), result.decisions_declined


def test_the_per_cycle_rate_limit_still_holds_with_real_delivery():
    tenant_id, cfg = _world(contacts=("a@acme.example.com", "b@acme.example.com"), max_sends=1)
    with SmtpSink() as sink:
        result = _cycle(tenant_id, cfg, sink)
        assert len(sink.messages) == 1 and result.stage_counts["sent"] == 1
        assert "rate_limit_reached" in _states(result.run_id).values()


def test_in_demo_mode_nothing_reaches_a_real_contact_across_a_whole_cycle():
    contacts = ("a@acme.example.com", "b@acme.example.com", "c@acme.example.com")
    tenant_id, cfg = _world(demo=True, contacts=contacts)
    with SmtpSink() as sink:
        _cycle(tenant_id, cfg, sink)
        recipients = {r for m in sink.messages for r in m["rcpt_to"]}
        assert recipients <= {INBOX}, f"a real contact was emailed in demo mode: {recipients - {INBOX}}"
        assert recipients  # and something was in fact sent to the inbox
