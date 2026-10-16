"""T234 (FR-006, SC-004): the person who approved, rejected or edited a draft is the person whose
session made the request. An actor named in the request body is ignored -- an audit trail that
believes the caller about who the caller is, is not an audit trail.

Names the production change that makes it fail: ``routers/actions.py`` stops reading
``actor_user_id`` from the body and records ``principal.user_id``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from pulse.api.main import app
from pulse.db.session import owner_session
from tests.auth_helpers import auth_headers, make_user
from tests.integration._agent_fixtures import seed_account, seed_tenant

AS_OF = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def _drafted_action():
    tenant_id, _ = seed_tenant(AS_OF)
    me, someone_else = make_user(tenant_id, "operator"), make_user(tenant_id, "csm")
    action_id = uuid.uuid4()
    with owner_session() as s:
        account_id = seed_account(s, tenant_id, AS_OF, "actor-a", n_tickets=1)
        s.execute(text("INSERT INTO action (id, tenant_id, account_id, play_key, subject, body)"
                       " VALUES (:i,:t,:a,'support_recovery','s','b')"),
                  {"i": action_id, "t": tenant_id, "a": account_id})
    return tenant_id, me, someone_else, action_id


def _decided_by(action_id):
    with owner_session() as s:
        return s.execute(text("SELECT decided_by_user_id FROM action WHERE id = :i"), {"i": action_id}).scalar()


@pytest.mark.parametrize("method,path,body", [
    ("POST", "/actions/{id}/approve", {}),
    ("POST", "/actions/{id}/reject", {"reason": "not now"}),
    ("PATCH", "/actions/{id}", {"subject": "New subject"}),
])
def test_the_recorded_actor_is_the_authenticated_user_not_the_one_named_in_the_body(method, path, body):
    tenant_id, me, someone_else, action_id = _drafted_action()
    r = TestClient(app).request(
        method, path.format(id=action_id), json={**body, "actor_user_id": str(someone_else)},
        headers=auth_headers(tenant_id, me),
    )
    assert r.status_code == 200, r.text
    assert _decided_by(action_id) == me
    assert r.json()["decided_by_user_id"] == str(me)
