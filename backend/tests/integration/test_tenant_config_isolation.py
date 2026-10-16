"""T078/T080: per-tenant config and play allowlist management is operator-only,
and a change in one tenant alters only that tenant's behaviour.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import text

from pulse.api.main import app
from pulse.db.session import owner_session


def _seed_tenant(role_of_user: str = "operator") -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id, user_id = uuid.uuid4(), uuid.uuid4()
    with owner_session() as s:
        s.execute(text("INSERT INTO tenant (id, slug, name, created_at) VALUES (:i,:s,:n, now())"),
                  {"i": tenant_id, "s": f"cfg-{uuid.uuid4().hex[:8]}", "n": "cfg"})
        s.execute(text("INSERT INTO tenant_config (id, tenant_id) VALUES (:i,:t)"),
                  {"i": uuid.uuid4(), "t": tenant_id})
        s.execute(text("INSERT INTO app_user (id, tenant_id, email, name, role)"
                       " VALUES (:i,:t,'u@example.test','U',:r)"),
                  {"i": user_id, "t": tenant_id, "r": role_of_user})
    return tenant_id, user_id


def _h(tenant_id, user_id) -> dict:
    return {"X-Tenant-Id": str(tenant_id), "X-User-Id": str(user_id)}


def test_non_operator_cannot_change_config():
    tenant, csm = _seed_tenant("csm")
    r = TestClient(app).patch("/admin/config", json={"weekly_capacity": 3}, headers=_h(tenant, csm))
    assert r.status_code == 403


def test_config_change_alters_only_that_tenant():
    a, op_a = _seed_tenant()
    b, op_b = _seed_tenant()
    client = TestClient(app)
    r = client.patch("/admin/config", json={"weekly_capacity": 3}, headers=_h(a, op_a))
    assert r.status_code == 200
    assert client.get("/admin/config", headers=_h(a, op_a)).json()["weekly_capacity"] == 3
    assert client.get("/admin/config", headers=_h(b, op_b)).json()["weekly_capacity"] == 10


def test_operator_toggles_allowlist_and_it_is_per_tenant():
    a, op_a = _seed_tenant()
    b, op_b = _seed_tenant()
    client = TestClient(app)
    r = client.put("/admin/allowlist/support_recovery", json={"auto_send": True}, headers=_h(a, op_a))
    assert r.status_code == 200
    la = client.get("/admin/allowlist", headers=_h(a, op_a)).json()
    lb = client.get("/admin/allowlist", headers=_h(b, op_b)).json()
    assert [(e["play_key"], e["auto_send"], e["enabled_by_user_id"]) for e in la] == \
        [("support_recovery", True, str(op_a))]
    assert lb == []


def test_unknown_config_field_is_rejected():
    a, op = _seed_tenant()
    r = TestClient(app).patch("/admin/config", json={"tenant_id": str(uuid.uuid4())}, headers=_h(a, op))
    assert r.status_code == 422
