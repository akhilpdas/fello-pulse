"""T222 (FR-001, FR-007, FR-008): signing in, who-am-I, and signing out.

Names the production change that makes it fail: ``pulse.api.routers.auth`` (POST /auth/login,
GET /auth/me, POST /auth/logout) and ``deps.get_principal``.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import text

from pulse.api.main import app
from pulse.auth.passwords import hash_password
from pulse.db.session import owner_session

PASSWORD = "correct horse battery staple"


def _tenant(role="csm", disabled=False):
    tenant_id, user_id = uuid.uuid4(), uuid.uuid4()
    slug = f"auth-{uuid.uuid4().hex[:8]}"
    email = f"u{uuid.uuid4().hex[:6]}@example.test"
    with owner_session() as s:
        s.execute(text("INSERT INTO tenant (id, slug, name, created_at) VALUES (:i,:s,'t', now())"),
                  {"i": tenant_id, "s": slug})
        s.execute(text("INSERT INTO app_user (id, tenant_id, email, name, role, password_hash, disabled_at)"
                       " VALUES (:i,:t,:e,'Ana',:r,:h, CASE WHEN :d THEN now() END)"),
                  {"i": user_id, "t": tenant_id, "e": email, "r": role, "h": hash_password(PASSWORD), "d": disabled})
    return slug, email, tenant_id, user_id


def _login(client, slug, email, password=PASSWORD):
    return client.post("/auth/login", json={"workspace": slug, "email": email, "password": password})


def test_login_sets_an_httponly_strict_cookie_and_me_returns_the_user():
    slug, email, tenant_id, user_id = _tenant(role="operator")
    c = TestClient(app)
    r = _login(c, slug, email)
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "pulse_session=" in cookie and "httponly" in cookie and "samesite=strict" in cookie
    assert r.json()["user"] == {"id": str(user_id), "name": "Ana", "role": "operator", "email": email}
    assert r.json()["tenant"] == {"id": str(tenant_id), "slug": slug}
    me = c.get("/auth/me")
    assert me.status_code == 200 and me.json()["user"]["id"] == str(user_id)


def test_every_kind_of_failure_looks_identical():
    slug, email, _, _ = _tenant()
    disabled_slug, disabled_email, _, _ = _tenant(disabled=True)
    c = TestClient(app)
    attempts = [
        _login(c, slug, email, "wrong password entirely"),
        _login(c, slug, "nobody@example.test"),
        _login(c, "no-such-workspace", email),
        _login(c, disabled_slug, disabled_email),  # right password, but disabled
    ]
    assert {r.status_code for r in attempts} == {401}
    assert len({r.text for r in attempts}) == 1  # same body: nothing to tell which part was wrong
    assert all("set-cookie" not in r.headers for r in attempts)


def test_repeated_failures_are_rate_limited_even_for_the_right_password_afterwards():
    slug, email, _, _ = _tenant()
    c = TestClient(app)
    for _ in range(5):
        assert _login(c, slug, email, "wrong password entirely").status_code == 401
    assert _login(c, slug, email).status_code == 429


def test_logout_revokes_the_session():
    slug, email, _, _ = _tenant()
    c = TestClient(app)
    _login(c, slug, email)
    assert c.get("/auth/me").status_code == 200
    assert c.post("/auth/logout", headers={"X-Requested-With": "pulse"}).status_code == 200
    assert c.get("/auth/me").status_code == 401


def test_me_without_a_session_is_401():
    assert TestClient(app).get("/auth/me").status_code == 401


def test_a_bearer_token_works_for_api_clients():
    slug, email, _, user_id = _tenant()
    c = TestClient(app)
    token = _login(c, slug, email).cookies["pulse_session"]
    api = TestClient(app)  # no cookie jar
    r = api.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r.json()["user"]["id"] == str(user_id)
