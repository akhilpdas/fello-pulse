"""Browse every scored account, not just the capacity-bound head of the queue (gap found 2026-10-17).

``GET /queue`` shows only the top ``weekly_capacity`` rows and a count of "N more below the cut"; the rest were
unreachable. ``GET /queue/all`` is the same ranking, paginated and filterable, so a CSM or operator can see them.

Names the production change that makes these fail: the ``/queue/all`` route in ``pulse.api.routers.queue``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from pulse.api.main import app
from pulse.db.session import owner_session, tenant_session
from pulse.scoring.service import score_and_persist
from tests.auth_helpers import auth_headers, make_user
from tests.integration._agent_fixtures import seed_account, seed_tenant, toy_support_model

AS_OF = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
CAPACITY = 2
TICKETS = {"alpha": 1, "bravo": 2, "charlie": 6, "delta": 12, "echo": 18}


@pytest.fixture
def world():
    tenant_id, cfg = seed_tenant(AS_OF)
    with owner_session() as s:
        s.execute(text("UPDATE tenant_config SET weekly_capacity = :c WHERE tenant_id = :t"),
                  {"c": CAPACITY, "t": tenant_id})
        accounts = {n: seed_account(s, tenant_id, AS_OF, n, n_tickets=k) for n, k in TICKETS.items()}
    model = toy_support_model(3)
    with tenant_session(tenant_id) as s:
        for a in accounts.values():
            score_and_persist(s, tenant_id=tenant_id, account_id=a, model=model,
                              model_version="t", tenant_config=cfg, as_of=AS_OF)
    return {"tenant": tenant_id, "accounts": accounts, "headers": auth_headers(tenant_id)}


def _all(world, **params):
    r = TestClient(app).get("/queue/all", params=params, headers=world["headers"])
    assert r.status_code == 200, r.text
    return r.json()


def test_reaches_accounts_below_the_cut_with_their_true_rank(world):
    body = _all(world)
    assert body["total"] == len(TICKETS)
    assert [r["rank"] for r in body["rows"]] == list(range(1, len(TICKETS) + 1))
    priorities = [r["priority"] for r in body["rows"]]
    assert priorities == sorted(priorities, reverse=True)
    assert [r["in_queue"] for r in body["rows"]] == [True] * CAPACITY + [False] * (len(TICKETS) - CAPACITY)


def test_the_head_matches_the_queue_the_csm_already_sees(world):
    c = TestClient(app)
    head = [r["account_id"] for r in c.get("/queue", headers=world["headers"]).json()["rows"]]
    assert head == [r["account_id"] for r in _all(world)["rows"]][:CAPACITY]


def test_pages_are_disjoint_ordered_and_cover_everything(world):
    first, second, third = (_all(world, limit=2, offset=o) for o in (0, 2, 4))
    pages = [first["rows"], second["rows"], third["rows"]]
    assert [len(p) for p in pages] == [2, 2, 1]
    ids = [r["account_id"] for p in pages for r in p]
    assert ids == [r["account_id"] for r in _all(world)["rows"]]
    assert len(set(ids)) == len(TICKETS)
    assert [r["rank"] for p in pages for r in p] == [1, 2, 3, 4, 5]  # rank is absolute, not per page
    assert first["total"] == second["total"] == third["total"] == len(TICKETS)


def test_filters_by_tier(world):
    everything = _all(world)["rows"]
    tier = everything[0]["tier"]
    body = _all(world, tier=tier)
    assert body["total"] == sum(1 for r in everything if r["tier"] == tier)
    assert {r["tier"] for r in body["rows"]} == {tier}


def test_filters_by_driver(world):
    everything = _all(world)["rows"]
    driver = everything[0]["dominant_driver"]
    body = _all(world, driver=driver)
    assert body["total"] == sum(1 for r in everything if r["dominant_driver"] == driver)
    assert {r["dominant_driver"] for r in body["rows"]} == {driver}


def test_searches_by_name_ignoring_case(world):
    body = _all(world, q="ChAr")
    assert [r["account_name"] for r in body["rows"]] == ["Charlie"]
    assert body["total"] == 1


def test_a_rank_keeps_its_absolute_position_when_filtered(world):
    body = _all(world, q="alpha")
    everything = _all(world)["rows"]
    expected = next(r["rank"] for r in everything if r["account_name"] == "Alpha")
    assert body["rows"][0]["rank"] == expected


def test_a_csm_browses_only_their_own_accounts(world):
    csm = make_user(world["tenant"], "csm")
    with owner_session() as s:
        s.execute(text("UPDATE account SET owner_user_id = :o WHERE id = :a"),
                  {"o": csm, "a": world["accounts"]["delta"]})
    h = auth_headers(world["tenant"], csm, role="csm")
    body = TestClient(app).get("/queue/all", headers=h).json()
    assert [r["account_name"] for r in body["rows"]] == ["Delta"]
    assert body["total"] == 1


def test_suppressed_accounts_stay_out_like_they_do_in_the_queue(world):
    with owner_session() as s:
        s.execute(text("INSERT INTO suppression (id, tenant_id, account_id, reason, expires_at)"
                       " VALUES (gen_random_uuid(), :t, :a, 'test', now() + interval '7 days')"),
                  {"t": world["tenant"], "a": world["accounts"]["echo"]})
    names = [r["account_name"] for r in _all(world)["rows"]]
    assert "Echo" not in names and len(names) == len(TICKETS) - 1


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 501}, {"offset": -1}])
def test_rejects_out_of_range_paging(world, params):
    r = TestClient(app).get("/queue/all", params=params, headers=world["headers"])
    assert r.status_code == 422


def test_requires_a_session():
    assert TestClient(app).get("/queue/all").status_code == 401


def test_accounts_with_equal_priority_keep_a_stable_order_so_paging_cannot_skip_or_repeat():
    # Regression guard, NOT test-first: it passed on its first run (the plan already returns ties in account-id
    # order). Mutation-checked instead: adding ``random()`` to the ORDER BY makes it fail.
    tenant_id, cfg = seed_tenant(AS_OF)
    with owner_session() as s:
        ids = [seed_account(s, tenant_id, AS_OF, f"tie{i}", n_tickets=6) for i in range(8)]
    model = toy_support_model(3)
    with tenant_session(tenant_id) as s:
        for a in ids:
            score_and_persist(s, tenant_id=tenant_id, account_id=a, model=model,
                              model_version="t", tenant_config=cfg, as_of=AS_OF)
    rows = TestClient(app).get("/queue/all", headers=auth_headers(tenant_id)).json()["rows"]
    assert len({r["priority"] for r in rows}) == 1  # the premise: they really are tied
    assert [r["account_id"] for r in rows] == sorted(r["account_id"] for r in rows)


def test_rows_carry_the_external_ref_so_same_named_accounts_can_be_told_apart(world):
    # Account names are not unique inside a tenant (clarifications / README gap); the CRM reference is.
    c = TestClient(app)
    refs = {r["account_name"]: r["external_ref"] for r in _all(world)["rows"]}
    assert refs == {n.title(): n for n in TICKETS}
    head = c.get("/queue", headers=world["headers"]).json()["rows"]
    assert all(r["external_ref"] == r["account_name"].lower() for r in head)
