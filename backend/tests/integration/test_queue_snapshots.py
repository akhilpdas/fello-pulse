"""``GET /queue/snapshots`` lists the dates a queue exists for, so the UI can offer a week picker and show history.

Names the production change that makes it fail: the ``/queue/snapshots`` route in ``pulse.api.routers.queue``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from pulse.api.main import app
from pulse.db.session import owner_session, tenant_session
from pulse.scoring.service import score_and_persist
from tests.auth_helpers import auth_headers
from tests.integration._agent_fixtures import seed_account, seed_tenant, toy_support_model

NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def _tenant_scored_at(offsets_days):
    tenant_id, cfg = seed_tenant(NOW)
    with owner_session() as s:
        accounts = [seed_account(s, tenant_id, NOW, f"snap{i}", n_tickets=8) for i in range(2)]
    model = toy_support_model(3)
    with tenant_session(tenant_id) as s:
        for d in offsets_days:
            for a in accounts:
                score_and_persist(s, tenant_id=tenant_id, account_id=a, model=model, model_version="t",
                                  tenant_config=cfg, as_of=NOW - timedelta(days=d))
    return tenant_id


def test_lists_each_snapshot_once_newest_first_with_how_many_accounts_were_scored():
    tenant_id = _tenant_scored_at([14, 0, 7])
    body = TestClient(app).get("/queue/snapshots", headers=auth_headers(tenant_id)).json()
    assert [datetime.fromisoformat(r["as_of"]) for r in body["snapshots"]] == [
        NOW, NOW - timedelta(days=7), NOW - timedelta(days=14)]
    assert [r["scored"] for r in body["snapshots"]] == [2, 2, 2]


def test_an_earlier_snapshot_can_be_opened_and_the_later_one_shows_a_change_against_it():
    tenant_id = _tenant_scored_at([7, 0])
    c, h = TestClient(app), auth_headers(tenant_id)
    older = c.get("/queue", params={"as_of": (NOW - timedelta(days=7)).isoformat()}, headers=h).json()
    newer = c.get("/queue", headers=h).json()
    assert all(r["delta"] is None for r in older["rows"])      # nothing before it to compare with
    assert all(r["delta"] is not None for r in newer["rows"])  # compared with the previous snapshot


def test_a_tenant_with_no_scores_has_no_snapshots():
    tenant_id, _ = seed_tenant(NOW)
    assert TestClient(app).get("/queue/snapshots", headers=auth_headers(tenant_id)).json() == {"snapshots": []}


def test_snapshots_of_another_tenant_are_never_listed():
    mine, other = _tenant_scored_at([0]), _tenant_scored_at([21, 14])
    body = TestClient(app).get("/queue/snapshots", headers=auth_headers(mine)).json()
    assert len(body["snapshots"]) == 1
    assert other != mine


def test_requires_a_session():
    assert TestClient(app).get("/queue/snapshots").status_code == 401


def test_a_csm_sees_counts_for_their_own_accounts_only():
    from sqlalchemy import text

    from tests.auth_helpers import make_user

    tenant_id = _tenant_scored_at([0])
    csm = make_user(tenant_id, "csm")
    with owner_session() as s:
        one = s.execute(text("SELECT id FROM account WHERE tenant_id = :t LIMIT 1"), {"t": tenant_id}).scalar()
        s.execute(text("UPDATE account SET owner_user_id = :o WHERE id = :a"), {"o": csm, "a": one})
    body = TestClient(app).get("/queue/snapshots", headers=auth_headers(tenant_id, csm, role="csm")).json()
    assert [r["scored"] for r in body["snapshots"]] == [1]
