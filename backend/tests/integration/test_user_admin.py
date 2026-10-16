"""T238 (FR-009, FR-007): an operator manages the users and account ownership of *their own tenant*,
and nothing else. A user they create can sign in; the password policy applies; an operator cannot
lock themselves out; and another tenant's users are simply not there (404).

Names the production change that makes it fail: ``/admin/users`` and ``/admin/accounts/{id}``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import text

from pulse.api.main import app
from pulse.db.session import owner_session
from tests.auth_helpers import auth_headers, make_user
from tests.integration._agent_fixtures import seed_account, seed_tenant

AS_OF = datetime(2026, 10, 1, tzinfo=UTC)
GOOD = "correct horse battery staple"


def _tenant_with_slug():
    tenant_id, _ = seed_tenant(AS_OF)
    with owner_session() as s:
        slug = s.execute(text("SELECT slug FROM tenant WHERE id = :i"), {"i": tenant_id}).scalar()
    return tenant_id, slug


def test_an_operator_creates_a_user_who_can_then_sign_in():
    tenant_id, slug = _tenant_with_slug()
    c, op = TestClient(app), auth_headers(tenant_id)
    r = c.post("/admin/users", json={"email": "new@example.test", "name": "New", "role": "csm", "password": GOOD},
               headers=op)
    assert r.status_code == 201, r.text
    assert "password" not in r.text and "hash" not in r.text.lower()
    login = TestClient(app).post("/auth/login", json={"workspace": slug, "email": "new@example.test", "password": GOOD})
    assert login.status_code == 200 and login.json()["user"]["role"] == "csm"


def test_password_policy_role_and_duplicate_email_are_enforced():
    tenant_id, _ = _tenant_with_slug()
    c, op = TestClient(app), auth_headers(tenant_id)
    body = {"email": "a@example.test", "name": "A", "role": "csm", "password": GOOD}
    assert c.post("/admin/users", json={**body, "password": "short"}, headers=op).status_code == 422
    assert c.post("/admin/users", json={**body, "role": "superuser"}, headers=op).status_code == 422
    assert c.post("/admin/users", json=body, headers=op).status_code == 201
    assert c.post("/admin/users", json=body, headers=op).status_code == 409


def test_a_csm_cannot_manage_users():
    tenant_id, _ = _tenant_with_slug()
    r = TestClient(app).post("/admin/users", json={"email": "x@example.test", "name": "X", "role": "csm",
                                                  "password": GOOD}, headers=auth_headers(tenant_id, role="csm"))
    assert r.status_code == 403


def test_disable_change_role_and_reset_password():
    tenant_id, slug = _tenant_with_slug()
    c, op = TestClient(app), auth_headers(tenant_id)
    uid = c.post("/admin/users", json={"email": "p@example.test", "name": "P", "role": "csm", "password": GOOD},
                 headers=op).json()["id"]
    assert c.patch(f"/admin/users/{uid}", json={"role": "operator"}, headers=op).json()["role"] == "operator"
    newpw = "a different long passphrase"
    assert c.patch(f"/admin/users/{uid}", json={"password": newpw}, headers=op).status_code == 200
    ok = TestClient(app).post("/auth/login", json={"workspace": slug, "email": "p@example.test", "password": newpw})
    assert ok.status_code == 200
    assert c.patch(f"/admin/users/{uid}", json={"disabled": True}, headers=op).json()["disabled"] is True
    assert TestClient(app).post("/auth/login", json={"workspace": slug, "email": "p@example.test",
                                                    "password": newpw}).status_code == 401


def test_an_operator_cannot_disable_or_demote_themselves():
    tenant_id, _ = _tenant_with_slug()
    me = make_user(tenant_id, "operator")
    c, h = TestClient(app), auth_headers(tenant_id, me)
    assert c.patch(f"/admin/users/{me}", json={"disabled": True}, headers=h).status_code == 409
    assert c.patch(f"/admin/users/{me}", json={"role": "csm"}, headers=h).status_code == 409


def test_another_tenants_users_do_not_exist_to_an_operator():
    a, _ = _tenant_with_slug()
    b, _ = _tenant_with_slug()
    their_user = make_user(b, "csm")
    c, op = TestClient(app), auth_headers(a)
    assert c.patch(f"/admin/users/{their_user}", json={"disabled": True}, headers=op).status_code == 404
    with owner_session() as s:
        assert s.execute(text("SELECT disabled_at FROM app_user WHERE id = :i"), {"i": their_user}).scalar() is None
    assert their_user not in {uuid.UUID(u["id"]) for u in c.get("/admin/users", headers=op).json()}


def test_an_operator_assigns_account_ownership_and_the_csm_then_sees_it():
    tenant_id, _ = _tenant_with_slug()
    csm = make_user(tenant_id, "csm")
    with owner_session() as s:
        account_id = seed_account(s, tenant_id, AS_OF, "own-a", n_tickets=1)
    c, op = TestClient(app), auth_headers(tenant_id)
    assert c.get(f"/accounts/{account_id}", headers=auth_headers(tenant_id, csm)).status_code == 404  # unowned
    assert c.patch(f"/admin/accounts/{account_id}", json={"owner_user_id": str(csm)}, headers=op).status_code == 200
    after = c.get(f"/accounts/{account_id}", headers=auth_headers(tenant_id, csm))
    assert after.status_code == 404 and after.json()["detail"] == "no score for this account"  # got past ownership
    other_tenant, _ = _tenant_with_slug()
    stranger = make_user(other_tenant, "csm")
    assert c.patch(f"/admin/accounts/{account_id}", json={"owner_user_id": str(stranger)}, headers=op).status_code == 404
