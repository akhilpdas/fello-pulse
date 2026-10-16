"""T240 (FR-012): security-relevant events are recorded, per tenant, with who did them -- sign-ins and
failures, sign-outs, refusals, attempts to assert a different identity, and administrative changes. The
trail never contains a password or token, and only the tenant's operator can read it.

Names the production change that makes it fail: ``pulse.auth.audit`` and ``GET /admin/audit``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import text

from pulse.api.main import app
from pulse.auth.passwords import hash_password
from pulse.db.session import owner_session
from tests.auth_helpers import auth_headers, make_user
from tests.integration._agent_fixtures import seed_tenant

AS_OF = datetime(2026, 10, 1, tzinfo=UTC)
PASSWORD = "correct horse battery staple"


def _tenant_with_login():
    tenant_id, _ = seed_tenant(AS_OF)
    user_id, email = uuid.uuid4(), f"a{uuid.uuid4().hex[:6]}@example.test"
    with owner_session() as s:
        slug = s.execute(text("SELECT slug FROM tenant WHERE id = :i"), {"i": tenant_id}).scalar()
        s.execute(text("INSERT INTO app_user (id, tenant_id, email, name, role, password_hash)"
                       " VALUES (:i,:t,:e,'Ana','operator',:h)"),
                  {"i": user_id, "t": tenant_id, "e": email, "h": hash_password(PASSWORD)})
    return tenant_id, slug, user_id, email


def _events(tenant_id) -> list[dict]:
    with owner_session() as s:
        rows = s.execute(text("SELECT event, actor_kind, actor_user_id, subject, detail::text AS detail"
                              " FROM audit_event WHERE tenant_id = :t ORDER BY at, id"), {"t": tenant_id}).mappings().all()
    return [dict(r) for r in rows]


def _names(tenant_id):
    return [e["event"] for e in _events(tenant_id)]


def test_login_success_failure_and_logout_are_recorded_without_secrets():
    tenant_id, slug, user_id, email = _tenant_with_login()
    c = TestClient(app)
    c.post("/auth/login", json={"workspace": slug, "email": email, "password": "wrong wrong wrong"})
    ok = c.post("/auth/login", json={"workspace": slug, "email": email, "password": PASSWORD})
    token = ok.cookies["pulse_session"]
    c.post("/auth/logout", headers={"X-Requested-With": "pulse"})
    events = _events(tenant_id)
    assert [e["event"] for e in events] == ["login_failed", "login_ok", "logout"]
    assert events[0]["actor_kind"] == "anonymous" and events[0]["subject"] == email
    assert events[1]["actor_kind"] == "user" and events[1]["actor_user_id"] == user_id
    blob = " ".join(str(e) for e in events)
    assert PASSWORD not in blob and "wrong wrong wrong" not in blob and token.split(".")[1] not in blob


def test_an_unknown_workspace_login_is_not_recorded_in_anyones_trail():
    tenant_id, _, _, email = _tenant_with_login()
    TestClient(app).post("/auth/login", json={"workspace": "no-such-workspace", "email": email, "password": "x" * 14})
    assert _names(tenant_id) == []


def test_a_refused_operator_route_is_recorded_as_forbidden_with_the_caller():
    tenant_id, _ = seed_tenant(AS_OF)
    csm = make_user(tenant_id, "csm")
    TestClient(app).get("/admin/config", headers=auth_headers(tenant_id, csm))
    events = _events(tenant_id)
    assert [e["event"] for e in events] == ["forbidden"]
    assert events[0]["actor_user_id"] == csm and "/admin/config" in events[0]["subject"]


def test_asserting_a_different_tenant_or_user_is_recorded_as_a_mismatch():
    a, _ = seed_tenant(AS_OF)
    b, _ = seed_tenant(AS_OF)
    me = make_user(a, "operator")
    c = TestClient(app)
    c.get("/auth/me", headers={**auth_headers(a, me), "X-Tenant-Id": str(b)})
    c.get("/auth/me", headers={**auth_headers(a, me), "X-Tenant-Id": str(a), "X-User-Id": str(me)})  # matches: fine
    assert _names(a) == ["tenant_mismatch"]
    assert _names(b) == []  # nothing leaks into the tenant that was named


def test_admin_changes_are_recorded():
    tenant_id, _ = seed_tenant(AS_OF)
    op = make_user(tenant_id, "operator")
    h, c = auth_headers(tenant_id, op), TestClient(app)
    uid = c.post("/admin/users", json={"email": "n@example.test", "name": "N", "role": "csm",
                                      "password": PASSWORD}, headers=h).json()["id"]
    c.patch(f"/admin/users/{uid}", json={"role": "operator"}, headers=h)
    c.patch(f"/admin/users/{uid}", json={"disabled": True}, headers=h)
    assert _names(tenant_id) == ["user_created", "role_changed", "user_disabled"]
    assert PASSWORD not in " ".join(str(e) for e in _events(tenant_id))


def test_only_the_tenants_operator_can_read_the_audit_trail_and_only_their_own():
    a, _ = seed_tenant(AS_OF)
    b, _ = seed_tenant(AS_OF)
    c = TestClient(app)
    c.get("/admin/config", headers=auth_headers(a, role="csm"))  # produces a 'forbidden' in A
    c.get("/admin/config", headers=auth_headers(b, role="csm"))  # and one in B
    assert c.get("/admin/audit", headers=auth_headers(a, role="csm")).status_code == 403
    rows = c.get("/admin/audit", headers=auth_headers(a)).json()
    assert rows and {r["event"] for r in rows} >= {"forbidden"}
    assert all(r["event"] != "tenant_mismatch" for r in rows)
    with owner_session() as s:
        own = s.execute(text("SELECT count(*) FROM audit_event WHERE tenant_id = :t AND event='forbidden'"), {"t": a}).scalar()
    assert sum(1 for r in rows if r["event"] == "forbidden") == own  # only A's, none of B's
