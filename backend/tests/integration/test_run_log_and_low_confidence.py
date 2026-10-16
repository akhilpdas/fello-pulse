"""T089/T090 backend surfaces: the run log (cycles with stage counts, declined
decisions, durations) and the low-confidence bucket (abstained accounts with
the machine-readable reason and a human remedy)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import text

from pulse.api.main import app
from pulse.db.session import owner_session, tenant_session
from pulse.scoring.service import score_and_persist
from tests.integration._agent_fixtures import seed_account, seed_tenant, toy_support_model

AS_OF = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def _h(tenant_id) -> dict:
    return {"X-Tenant-Id": str(tenant_id)}


def test_run_log_lists_cycles_newest_first_with_stage_counts_and_declined_decisions():
    tenant_id, _ = seed_tenant(AS_OF)
    declined = [{"account_id": str(uuid.uuid4()), "stage": "policy", "reason": "suppressed"}]
    with owner_session() as s:
        for i, started in enumerate(["2026-10-01T09:00:00+00", "2026-10-08T09:00:00+00"]):
            s.execute(
                text("INSERT INTO agent_run (id, tenant_id, trigger, started_at, finished_at, status,"
                     " as_of, stage_counts, decisions_declined, errors, duration_ms)"
                     " VALUES (:i,:t,'schedule',:st,:st,'succeeded',:st, CAST(:sc AS jsonb),"
                     " CAST(:d AS jsonb),'[]'::jsonb,:ms)"),
                {"i": uuid.uuid4(), "t": tenant_id, "st": started,
                 "sc": json.dumps({"scored": 10 + i}), "d": json.dumps(declined), "ms": 1200 + i},
            )
    r = TestClient(app).get("/runs", headers=_h(tenant_id))
    assert r.status_code == 200
    runs = r.json()
    assert [x["stage_counts"]["scored"] for x in runs] == [11, 10]  # newest first
    assert runs[0]["duration_ms"] == 1201 and runs[0]["status"] == "succeeded"
    assert runs[0]["decisions_declined"] == declined


def test_run_log_is_tenant_scoped():
    a, _ = seed_tenant(AS_OF)
    b, _ = seed_tenant(AS_OF)
    with owner_session() as s:
        s.execute(text("INSERT INTO agent_run (id, tenant_id, trigger, started_at, status, as_of)"
                       " VALUES (:i,:t,'schedule', now(),'succeeded', now())"),
                  {"i": uuid.uuid4(), "t": a})
    assert len(TestClient(app).get("/runs", headers=_h(a)).json()) == 1
    assert TestClient(app).get("/runs", headers=_h(b)).json() == []


def test_low_confidence_lists_abstained_accounts_with_reason_and_remedy():
    tenant_id, cfg = seed_tenant(AS_OF)
    with owner_session() as s:
        account_id = seed_account(s, tenant_id, AS_OF, "lc-a", n_tickets=2)
    thin = {**cfg, "min_days_history": 10_000}  # forces insufficient_history
    with tenant_session(tenant_id) as s:
        score_and_persist(s, tenant_id=tenant_id, account_id=account_id, model=toy_support_model(3),
                          model_version="t", tenant_config=thin, as_of=AS_OF)
    r = TestClient(app).get("/queue/low-confidence", headers=_h(tenant_id))
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert [x["account_id"] for x in rows] == [str(account_id)]
    assert rows[0]["abstain_reason"] == "insufficient_history"
    assert rows[0]["remedy"]  # a human-readable next step, not just a code


def test_low_confidence_excludes_trusted_scores():
    tenant_id, cfg = seed_tenant(AS_OF)
    with owner_session() as s:
        account_id = seed_account(s, tenant_id, AS_OF, "lc-b", n_tickets=2)
    with tenant_session(tenant_id) as s:
        score_and_persist(s, tenant_id=tenant_id, account_id=account_id, model=toy_support_model(3),
                          model_version="t", tenant_config=cfg, as_of=AS_OF)
    assert TestClient(app).get("/queue/low-confidence", headers=_h(tenant_id)).json()["rows"] == []
