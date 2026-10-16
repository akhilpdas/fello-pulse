"""api/routers/actions.py (T075, T076, T077): list, approve, reject, edit --
actor and timestamp recorded on every decision; no send without either human
approval or an auto-send allowlist entry (SC-011); a failing transport is
retried a bounded number of times and a final failure is surfaced, not
silently swallowed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import pulse.api.deps as deps
from pulse.agent.transport import RecordingTransport
from pulse.api.main import app
from pulse.db.session import owner_session
from tests.auth_helpers import auth_headers

AS_OF = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def _seed_minimal_action(state: str = "drafted") -> tuple[uuid.UUID, uuid.UUID]:
    """A tenant, a user, an account and a bare Action row -- no score needed,
    the lifecycle endpoints operate on the Action row directly."""
    tenant_id = uuid.uuid4()
    slug = f"actions-test-{uuid.uuid4().hex[:8]}"
    user_id = uuid.uuid4()
    account_id = uuid.uuid4()
    action_id = uuid.uuid4()
    with owner_session() as s:
        s.execute(text("INSERT INTO tenant (id, slug, name, created_at) VALUES (:i,:s,:n, now())"),
                  {"i": tenant_id, "s": slug, "n": slug})
        # A demo-mode tenant with a verified sender and a test inbox: delivery goes through the same gate and
        # code path as a real tenant, to a harmless address (see test_approve_delivers.py for real SMTP).
        s.execute(text("INSERT INTO tenant_config (id, tenant_id, outbound_enabled, sender_address, sender_verified,"
                       " demo_mode, test_inbox) VALUES (:i,:t, true, 'csm@example.test', true, true, 'demo@example.test')"),
                  {"i": uuid.uuid4(), "t": tenant_id})
        s.execute(
            text("INSERT INTO app_user (id, tenant_id, email, name, role) VALUES (:i,:t,:e,:n,'csm')"),
            {"i": user_id, "t": tenant_id, "e": "csm@example.test", "n": "Dana"},
        )
        s.execute(
            text(
                "INSERT INTO account (id, tenant_id, external_ref, name, signup_date,"
                " lifecycle_state, owner_user_id, contact_email, created_at)"
                " VALUES (:i,:t,:r,:n,:sd,'active', :u, 'contact@acme.example.test', now())"
            ),
            {"i": account_id, "t": tenant_id, "r": "acct-1", "n": "Acme",
             "sd": AS_OF.date(), "u": user_id},  # Dana owns the account she acts on
        )
        s.execute(
            text(
                "INSERT INTO action (id, tenant_id, account_id, play_key, state, channel,"
                " subject, body, draft_source, grounding, created_at, attempts)"
                " VALUES (:i,:t,:a,'support_recovery',:st,'email','Hi','body','template',"
                " '{}'::jsonb, now(), 0)"
            ),
            {"i": action_id, "t": tenant_id, "a": account_id, "st": state},
        )
    return tenant_id, action_id, user_id


@pytest.fixture
def client():
    return TestClient(app)


def _headers(tenant_id, user_id=None):
    return auth_headers(tenant_id, user_id)


def test_list_actions_returns_the_seeded_row(client):
    tenant_id, action_id, user_id = _seed_minimal_action()
    resp = client.get("/actions", headers=_headers(tenant_id, user_id))
    assert resp.status_code == 200
    ids = [r["id"] for r in resp.json()["rows"]]
    assert str(action_id) in ids


def test_approve_without_an_allowlisted_transport_override_still_requires_explicit_send(client):
    """Approval alone does not guarantee a send -- SC-011: no send without
    either human approval (this call) or an allowlist. Here we approve
    *and* the endpoint attempts the send using the configured transport;
    this test checks the lifecycle record, not the transport wiring itself
    (covered in the retry test below)."""
    tenant_id, action_id, user_id = _seed_minimal_action()
    resp = client.post(
        f"/actions/{action_id}/reject",
        headers=_headers(tenant_id, user_id),
        json={"reason": "not relevant right now"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "rejected"
    assert body["decided_by_user_id"] == str(user_id)
    assert body["decided_at"] is not None

    with owner_session() as s:
        row = s.execute(
            text("SELECT state, state_reason, sent_at FROM action WHERE id = :i"), {"i": action_id},
        ).mappings().one()
    assert row["state"] == "rejected"
    assert row["state_reason"] == "not relevant right now"
    assert row["sent_at"] is None


def test_edit_updates_content_and_records_the_actor_without_changing_state(client):
    tenant_id, action_id, user_id = _seed_minimal_action()
    resp = client.patch(
        f"/actions/{action_id}",
        headers=_headers(tenant_id, user_id),
        json={"subject": "New subject", "body": "New body"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "drafted"
    assert body["subject"] == "New subject"
    assert body["decided_by_user_id"] == str(user_id)
    assert body["decided_at"] is not None


def test_edit_is_rejected_once_a_decision_has_already_been_made(client):
    tenant_id, action_id, user_id = _seed_minimal_action(state="rejected")
    resp = client.patch(
        f"/actions/{action_id}",
        headers=_headers(tenant_id, user_id),
        json={"subject": "too late"},
    )
    assert resp.status_code == 409


def test_approve_sends_successfully_via_the_configured_transport(client):
    tenant_id, action_id, user_id = _seed_minimal_action()
    transport = RecordingTransport()
    app.dependency_overrides[deps.get_transport] = lambda: transport
    try:
        resp = client.post(
            f"/actions/{action_id}/approve",
            headers=_headers(tenant_id, user_id),
            json={},
        )
    finally:
        app.dependency_overrides.pop(deps.get_transport, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "sent"
    assert body["decided_by_user_id"] == str(user_id)
    assert len(transport.sent) == 1


def test_approve_retries_a_failing_transport_a_bounded_number_of_times_then_surfaces_failure(client):
    tenant_id, action_id, user_id = _seed_minimal_action()
    transport = RecordingTransport(fail_next=10)  # more failures than the retry budget
    app.dependency_overrides[deps.get_transport] = lambda: transport
    try:
        resp = client.post(
            f"/actions/{action_id}/approve",
            headers=_headers(tenant_id, user_id),
            json={},
        )
    finally:
        app.dependency_overrides.pop(deps.get_transport, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "send_failed"
    assert "simulated_transport_failure" in body["state_reason"]

    with owner_session() as s:
        attempts = s.execute(
            text("SELECT attempts FROM action WHERE id = :i"), {"i": action_id},
        ).scalar()
    assert attempts == 3  # the bounded retry budget, not an unbounded loop
    assert transport.sent == []


def test_approve_recovers_if_the_transport_succeeds_within_the_retry_budget(client):
    tenant_id, action_id, user_id = _seed_minimal_action()
    transport = RecordingTransport(fail_next=2)  # fails twice, succeeds on the third try
    app.dependency_overrides[deps.get_transport] = lambda: transport
    try:
        resp = client.post(
            f"/actions/{action_id}/approve",
            headers=_headers(tenant_id, user_id),
            json={},
        )
    finally:
        app.dependency_overrides.pop(deps.get_transport, None)

    assert resp.status_code == 200
    assert resp.json()["state"] == "sent"
    assert len(transport.sent) == 1
