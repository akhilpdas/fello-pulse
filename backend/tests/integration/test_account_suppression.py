"""T203 (001/FR-048): a CSM can suppress an account from the queue with a reason and an expiry,
without deleting it. Suppression hides the account from the *queue*, never from scoring --
an account deliberately being allowed to churn is a legitimate business state.

Names the production change that makes it fail: ``POST/DELETE /accounts/{id}/suppress`` and the
router that writes the ``suppression`` table (api/routers/suppression.py).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import text

from pulse.api.main import app
from pulse.db.session import owner_session, tenant_session
from pulse.scoring.service import score_and_persist
from tests.auth_helpers import auth_headers
from tests.integration._agent_fixtures import seed_account, seed_tenant, toy_support_model

AS_OF = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def _setup():
    tenant_id, cfg = seed_tenant(AS_OF)
    user_id = uuid.uuid4()
    with owner_session() as s:
        account_id = seed_account(s, tenant_id, AS_OF, "sup-a", n_tickets=12)
        s.execute(text("INSERT INTO app_user (id, tenant_id, email, name, role)"
                       " VALUES (:i,:t,'csm@example.test','C','csm')"), {"i": user_id, "t": tenant_id})
        s.execute(text("UPDATE account SET owner_user_id = :u WHERE id = :a"), {"u": user_id, "a": account_id})  # their own account
    with tenant_session(tenant_id) as s:
        score_and_persist(s, tenant_id=tenant_id, account_id=account_id, model=toy_support_model(3),
                          model_version="t", tenant_config=cfg, as_of=AS_OF)
    h = auth_headers(tenant_id, user_id, role="csm")
    return tenant_id, user_id, account_id, h


def _queue_ids(client, h):
    return [r["account_id"] for r in client.get("/queue", headers=h).json()["rows"]]


def _future(days=14):
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


def test_suppressed_account_leaves_the_queue_but_keeps_its_score():
    _, user_id, account_id, h = _setup()
    c = TestClient(app)
    assert str(account_id) in _queue_ids(c, h)  # precondition: it is on the queue

    r = c.post(f"/accounts/{account_id}/suppress",
               json={"reason": "deliberately letting this one go", "expires_at": _future()}, headers=h)
    assert r.status_code == 201
    assert str(account_id) not in _queue_ids(c, h)
    with owner_session() as s:
        assert s.execute(text("SELECT count(*) FROM score WHERE account_id = :a"),
                         {"a": account_id}).scalar() == 1
        assert s.execute(text("SELECT created_by_user_id FROM suppression WHERE account_id = :a"),
                         {"a": account_id}).scalar() == user_id


def test_reason_is_required_and_expiry_must_be_in_the_future():
    _, _, account_id, h = _setup()
    c = TestClient(app)
    assert c.post(f"/accounts/{account_id}/suppress", json={"reason": "  ", "expires_at": _future()},
                  headers=h).status_code == 422
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    assert c.post(f"/accounts/{account_id}/suppress", json={"reason": "x", "expires_at": past},
                  headers=h).status_code == 422


def test_lifting_a_suppression_returns_the_account_to_the_queue():
    _, _, account_id, h = _setup()
    c = TestClient(app)
    c.post(f"/accounts/{account_id}/suppress", json={"reason": "x", "expires_at": _future()}, headers=h)
    assert c.delete(f"/accounts/{account_id}/suppress", headers=h).status_code == 200
    assert str(account_id) in _queue_ids(c, h)


# GUARD: queue.py already honours expiry; this pins existing behaviour, it is not test-first.
def test_an_expired_suppression_no_longer_hides_the_account():
    tenant_id, user_id, account_id, h = _setup()
    with owner_session() as s:
        s.execute(text("INSERT INTO suppression (id, tenant_id, account_id, reason, expires_at)"
                       " VALUES (:i,:t,:a,'old', now() - interval '1 day')"),
                  {"i": uuid.uuid4(), "t": tenant_id, "a": account_id})
    assert str(account_id) in _queue_ids(TestClient(app), h)


def test_suppressing_another_tenants_account_is_a_404():
    _, _, their_account, _ = _setup()
    _, _, my_account, mine = _setup()
    c = TestClient(app)
    # Same route works for my own account -- so the 404 below is isolation, not a missing route.
    assert c.post(f"/accounts/{my_account}/suppress", json={"reason": "x", "expires_at": _future()},
                  headers=mine).status_code == 201
    r = c.post(f"/accounts/{their_account}/suppress", json={"reason": "x", "expires_at": _future()},
               headers=mine)
    assert r.status_code == 404
