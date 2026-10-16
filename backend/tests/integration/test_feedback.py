"""T201 (001/FR-047): a CSM can mark a flagged account as a false positive (or confirm it)
with a note, and it is retained as labelled feedback -- a domain expert saying "this one is
wrong" is the most valuable label the system is ever handed, so it is stored, not just hidden.

Names the production change that makes it fail: ``POST /accounts/{id}/feedback`` and the router
that writes the ``feedback`` table (api/routers/feedback.py).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import text

from pulse.api.main import app
from pulse.db.session import owner_session, tenant_session
from pulse.scoring.service import score_and_persist
from tests.auth_helpers import auth_headers
from tests.integration._agent_fixtures import seed_account, seed_tenant, toy_support_model

AS_OF = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def _scored_account(slug: str):
    tenant_id, cfg = seed_tenant(AS_OF)
    user_id = uuid.uuid4()
    with owner_session() as s:
        account_id = seed_account(s, tenant_id, AS_OF, slug, n_tickets=12)
        s.execute(text("INSERT INTO app_user (id, tenant_id, email, name, role)"
                       " VALUES (:i,:t,'csm@example.test','C','csm')"), {"i": user_id, "t": tenant_id})
        s.execute(text("UPDATE account SET owner_user_id = :u WHERE id = :a"), {"u": user_id, "a": account_id})  # their own account
    with tenant_session(tenant_id) as s:
        score_and_persist(s, tenant_id=tenant_id, account_id=account_id, model=toy_support_model(3),
                          model_version="t", tenant_config=cfg, as_of=AS_OF)
    return tenant_id, user_id, account_id


def _h(tenant_id, user_id) -> dict:
    return auth_headers(tenant_id, user_id)


def test_feedback_is_stored_against_the_latest_score_with_its_author():
    tenant_id, user_id, account_id = _scored_account("fb-a")
    r = TestClient(app).post(
        f"/accounts/{account_id}/feedback",
        json={"kind": "false_positive", "note": "renewed early last week"},
        headers=_h(tenant_id, user_id),
    )
    assert r.status_code == 201
    with owner_session() as s:
        row = s.execute(
            text("SELECT f.kind, f.note, f.created_by_user_id, f.score_id, sc.as_of"
                 " FROM feedback f LEFT JOIN score sc ON sc.id = f.score_id WHERE f.account_id = :a"),
            {"a": account_id},
        ).mappings().one()
    assert (row["kind"], row["note"], row["created_by_user_id"]) == (
        "false_positive", "renewed early last week", user_id)
    assert row["as_of"] == AS_OF  # linked to the score the CSM was looking at


def test_unknown_feedback_kind_is_rejected():
    tenant_id, user_id, account_id = _scored_account("fb-b")
    r = TestClient(app).post(f"/accounts/{account_id}/feedback", json={"kind": "meh"},
                             headers=_h(tenant_id, user_id))
    assert r.status_code == 422


def test_feedback_on_another_tenants_account_is_a_404_and_writes_nothing():
    _, _, their_account = _scored_account("fb-c")
    mine, my_user, my_account = _scored_account("fb-d")
    c = TestClient(app)
    # Same route works for my own account -- so the 404 below is isolation, not a missing route.
    assert c.post(f"/accounts/{my_account}/feedback", json={"kind": "true_positive"},
                  headers=_h(mine, my_user)).status_code == 201
    r = c.post(f"/accounts/{their_account}/feedback", json={"kind": "false_positive"},
               headers=_h(mine, my_user))
    assert r.status_code == 404
    with owner_session() as s:
        assert s.execute(text("SELECT count(*) FROM feedback WHERE account_id = :a"),
                         {"a": their_account}).scalar() == 0
