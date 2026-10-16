"""T232 (FR-005, 001/FR-042): a CSM sees only the accounts they own -- in the queue, low-confidence list,
drafts, account detail, evidence, score-diff -- and cannot act on anyone else's. An operator sees the
whole tenant. An account that has no owner is visible to operators only. An account a CSM does not own is a
404, not a 403: its existence is not disclosed.

Names the production change that makes it fail: ``pulse.api.visibility`` applied by every account-level query.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from pulse.api.main import app
from pulse.db.session import owner_session, tenant_session
from pulse.scoring.service import score_and_persist
from tests.auth_helpers import auth_headers, make_user
from tests.integration._agent_fixtures import seed_account, seed_tenant, toy_support_model

AS_OF = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


@pytest.fixture
def world():
    tenant_id, cfg = seed_tenant(AS_OF)
    csm1, csm2 = make_user(tenant_id, "csm"), make_user(tenant_id, "csm")
    operator = make_user(tenant_id, "operator")
    accounts, actions = {}, {}
    with owner_session() as s:
        for name, owner in (("mine", csm1), ("theirs", csm2), ("unowned", None)):
            accounts[name] = seed_account(s, tenant_id, AS_OF, f"scope-{name}", n_tickets=12)
            s.execute(text("UPDATE account SET owner_user_id = :o WHERE id = :a"),
                      {"o": owner, "a": accounts[name]})
            actions[name] = uuid.uuid4()
            s.execute(text("INSERT INTO action (id, tenant_id, account_id, play_key, subject, body)"
                           " VALUES (:i,:t,:a,'support_recovery','s','b')"),
                      {"i": actions[name], "t": tenant_id, "a": accounts[name]})
    model = toy_support_model(3)
    with tenant_session(tenant_id) as s:
        for a in accounts.values():
            for as_of in (AS_OF - timedelta(days=7), AS_OF):
                score_and_persist(s, tenant_id=tenant_id, account_id=a, model=model,
                                  model_version="t", tenant_config=cfg, as_of=as_of)
    return {"tenant": tenant_id, "csm1": csm1, "csm2": csm2, "operator": operator,
            "accounts": accounts, "actions": actions}


def _as(world, who):
    return auth_headers(world["tenant"], world[who], role="operator" if who == "operator" else "csm")


def _ids(resp, key="account_id"):
    return {r[key] for r in resp.json()["rows"]}


def test_queue_is_scoped_to_the_callers_accounts_and_operators_see_all(world):
    c, a = TestClient(app), world["accounts"]
    assert _ids(c.get("/queue", headers=_as(world, "csm1"))) == {str(a["mine"])}
    assert _ids(c.get("/queue", headers=_as(world, "csm2"))) == {str(a["theirs"])}
    assert _ids(c.get("/queue", headers=_as(world, "operator"))) == {str(x) for x in a.values()}


def test_drafts_are_scoped_to_the_callers_accounts(world):
    c, a = TestClient(app), world["accounts"]
    assert _ids(c.get("/actions", headers=_as(world, "csm1"))) == {str(a["mine"])}
    assert _ids(c.get("/actions", headers=_as(world, "operator"))) == {str(x) for x in a.values()}


def test_account_detail_evidence_and_score_diff_are_404_for_someone_elses_account(world):
    c, a = TestClient(app), world["accounts"]
    h = _as(world, "csm1")
    diff = {"from_as_of": (AS_OF - timedelta(days=7)).isoformat(), "to_as_of": AS_OF.isoformat()}
    assert c.get(f"/accounts/{a['mine']}", headers=h).status_code == 200  # control: own account works
    assert c.get(f"/accounts/{a['mine']}/score-diff", params=diff, headers=h).status_code == 200
    for other in ("theirs", "unowned"):
        assert c.get(f"/accounts/{a[other]}", headers=h).status_code == 404, other
        assert c.get(f"/accounts/{a[other]}/evidence", params={"event_ids": [1]}, headers=h).status_code == 404
        assert c.get(f"/accounts/{a[other]}/score-diff", params=diff, headers=h).status_code == 404
    assert c.get(f"/accounts/{a['unowned']}", headers=_as(world, "operator")).status_code == 200


def test_a_csm_cannot_act_on_someone_elses_account_or_draft(world):
    c, a, act = TestClient(app), world["accounts"], world["actions"]
    h = _as(world, "csm1")
    future = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    assert c.post(f"/accounts/{a['mine']}/feedback", json={"kind": "true_positive"}, headers=h).status_code == 201
    assert c.post(f"/accounts/{a['theirs']}/feedback", json={"kind": "false_positive"}, headers=h).status_code == 404
    assert c.post(f"/accounts/{a['theirs']}/suppress", json={"reason": "x", "expires_at": future},
                  headers=h).status_code == 404
    uid = str(world["csm1"])
    assert c.post(f"/actions/{act['theirs']}/reject", json={"actor_user_id": uid, "reason": "no"},
                  headers=h).status_code == 404
    assert c.post(f"/actions/{act['theirs']}/approve", json={"actor_user_id": uid}, headers=h).status_code == 404


def test_low_confidence_list_is_scoped_too(world):
    tenant_id, a = world["tenant"], world["accounts"]
    thin = {"connected_sources": frozenset({"zendesk", "stripe"}), "min_days_history": 10_000,
            "min_sources_with_data": 2, "tier_red_at": 0.35, "tier_amber_at": 0.15, "material_delta": 0.08,
            "suppression_days": 14, "max_sends_per_cycle": 25}
    later = AS_OF + timedelta(days=7)
    with tenant_session(tenant_id) as s:
        for acct in a.values():
            score_and_persist(s, tenant_id=tenant_id, account_id=acct, model=toy_support_model(3),
                              model_version="t", tenant_config=thin, as_of=later)
    c = TestClient(app)
    assert _ids(c.get("/queue/low-confidence", headers=_as(world, "csm1"))) == {str(a["mine"])}
    assert _ids(c.get("/queue/low-confidence", headers=_as(world, "operator"))) == {str(x) for x in a.values()}
