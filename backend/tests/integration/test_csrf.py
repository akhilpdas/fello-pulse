"""T227a (R-5): the session cookie is sent by the browser on any request to our origin, so a state-changing
request authenticated *only* by the cookie must also carry ``X-Requested-With`` -- a header a cross-site
form or image cannot set. (``SameSite=Strict`` is the first control; this is the second.) Bearer-token
clients are not CSRF-able and are exempt, as are safe methods.

Names the production change that makes it fail: ``get_principal`` enforcing the header for cookie auth.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import text

from pulse.api.main import app
from pulse.auth.passwords import hash_password
from pulse.db.session import owner_session
from tests.integration._agent_fixtures import seed_tenant

PASSWORD = "correct horse battery staple"
MUTATION = ("PUT", "/admin/allowlist/support_recovery", {"auto_send": False})


def _signed_in_client():
    tenant_id, _ = seed_tenant(datetime(2026, 10, 1, tzinfo=UTC))
    email = f"c{uuid.uuid4().hex[:6]}@example.test"
    with owner_session() as s:
        slug = s.execute(text("SELECT slug FROM tenant WHERE id = :i"), {"i": tenant_id}).scalar()
        s.execute(text("INSERT INTO app_user (id, tenant_id, email, name, role, password_hash)"
                       " VALUES (:i,:t,:e,'C','operator',:h)"),
                  {"i": uuid.uuid4(), "t": tenant_id, "e": email, "h": hash_password(PASSWORD)})
    c = TestClient(app)
    r = c.post("/auth/login", json={"workspace": slug, "email": email, "password": PASSWORD})
    assert r.status_code == 200
    return c, r.cookies["pulse_session"]


def test_cookie_authenticated_mutation_without_the_header_is_refused():
    c, _ = _signed_in_client()
    method, path, body = MUTATION
    assert c.request(method, path, json=body).status_code == 403


def test_cookie_authenticated_mutation_with_the_header_is_allowed():
    c, _ = _signed_in_client()
    method, path, body = MUTATION
    assert c.request(method, path, json=body, headers={"X-Requested-With": "pulse"}).status_code == 200


def test_reads_and_bearer_clients_are_exempt():
    c, token = _signed_in_client()
    assert c.get("/auth/me").status_code == 200  # a GET with only the cookie
    method, path, body = MUTATION
    api = TestClient(app)  # no cookie jar
    assert api.request(method, path, json=body, headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_logout_by_cookie_also_needs_the_header():
    c, _ = _signed_in_client()
    assert c.post("/auth/logout").status_code == 403
    assert c.post("/auth/logout", headers={"X-Requested-With": "pulse"}).status_code == 200
