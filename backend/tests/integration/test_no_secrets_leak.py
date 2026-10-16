"""T270 (FR-021): provider credentials appear nowhere a person, a log or a database dump could read them --
not in an API response, not in an action or run record, not in the audit trail, not in a log line, not in an
exception message. Also: a misconfigured provider (here: credentials supplied, server offers no AUTH) is a
*classified, recorded* failure, not an unhandled exception.

Names the production change that makes it fail: ``SmtpTransport.send`` catching ``smtplib.SMTPException``
generally (it only handled response errors, disconnects and OS errors).
"""

from __future__ import annotations

import json
import logging
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

SECRET = "hunter2-smtp-SECRET-7731"
AS_OF = datetime(2026, 10, 1, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _reset():
    yield
    app.dependency_overrides.pop(deps.get_transport, None)


def test_credentials_against_a_server_without_auth_is_a_classified_failure_not_an_exception():
    with SmtpSink() as sink:  # the sink offers no AUTH
        t = SmtpTransport(host="127.0.0.1", port=sink.port, user="mailer", password=SECRET, starttls=False, timeout=2.0)
        result = t.send(to="a@b.example.com", subject="s", body="b", sender="x@y.example.com", message_id="<m@p>")
    assert (result.ok, result.kind) == (False, "permanent")  # a configuration problem retrying cannot fix
    assert SECRET not in repr(result) and SECRET not in (result.error or "") and SECRET not in repr(t)


def test_a_failing_authenticated_send_leaks_the_secret_nowhere(caplog):
    caplog.set_level(logging.DEBUG)
    tenant_id, _ = seed_tenant(AS_OF)
    action_id = uuid.uuid4()
    with owner_session() as s:
        acct = seed_account(s, tenant_id, AS_OF, "leak-a", n_tickets=1)
        s.execute(text("UPDATE account SET contact_email = 'c@acme.example.com' WHERE id = :a"), {"a": acct})
        s.execute(text("UPDATE tenant_config SET outbound_enabled=true, sender_address='csm@northwind.example.com',"
                       " sender_verified=true, demo_mode=false WHERE tenant_id=:t"), {"t": tenant_id})
        s.execute(text("INSERT INTO action (id, tenant_id, account_id, play_key, subject, body)"
                       " VALUES (:i,:t,:a,'support_recovery','s','b')"), {"i": action_id, "t": tenant_id, "a": acct})
    with SmtpSink() as sink:
        app.dependency_overrides[deps.get_transport] = lambda: SmtpTransport(
            host="127.0.0.1", port=sink.port, user="mailer", password=SECRET, starttls=False, timeout=2.0)
        r = TestClient(app).post(f"/actions/{action_id}/approve", json={}, headers=auth_headers(tenant_id))
    assert r.status_code == 200 and r.json()["state"] == "send_failed"

    surfaces = [r.text, caplog.text]
    with owner_session() as s:
        for table in ("action", "agent_run", "audit_event", "tenant_config"):
            surfaces.append(json.dumps(s.execute(text(f"SELECT row_to_json(t)::text FROM {table} t WHERE tenant_id = :t"),
                                                 {"t": tenant_id}).scalars().all()))
    assert not [i for i, blob in enumerate(surfaces) if SECRET in blob], "a credential reached a readable surface"
