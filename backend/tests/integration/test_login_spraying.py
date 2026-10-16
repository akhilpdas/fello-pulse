"""FR-007 ("rate-limited per identity *and per source*"): trying one password against many different accounts from
one address -- password spraying -- never trips a per-account limit, because each account sees only one failure. A
limit on the *source address* across all accounts is what stops it. Found by re-running /speckit-analyze on spec 002.

Names the production change that makes it fail: a second, address-wide limiter key in ``/auth/login`` and the
``login_max_failures_per_address`` setting.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import pulse.api.routers.auth as auth_routes
from pulse.api.main import app
from pulse.auth.passwords import hash_password
from pulse.config import reset_settings
from pulse.db.session import owner_session
from tests.integration._agent_fixtures import seed_tenant

PASSWORD = "correct horse battery staple"


@pytest.fixture
def small_address_limit(monkeypatch):
    monkeypatch.setenv("PULSE_LOGIN_MAX_FAILURES_PER_ADDRESS", "6")
    reset_settings()
    auth_routes._limiter = None
    yield
    auth_routes._limiter = None
    reset_settings()


def _tenant():
    tenant_id, _ = seed_tenant(datetime(2026, 10, 1, tzinfo=UTC))
    email = f"real-{uuid.uuid4().hex[:6]}@example.test"
    with owner_session() as s:
        slug = s.execute(text("SELECT slug FROM tenant WHERE id = :i"), {"i": tenant_id}).scalar()
        s.execute(text("INSERT INTO app_user (id, tenant_id, email, name, role, password_hash)"
                       " VALUES (:i,:t,:e,'R','csm',:h)"), {"i": uuid.uuid4(), "t": tenant_id, "e": email,
                                                           "h": hash_password(PASSWORD)})
    return slug, email


def _login(client, slug, email, password):
    return client.post("/auth/login", json={"workspace": slug, "email": email, "password": password})


def test_spraying_many_accounts_from_one_address_is_stopped_even_though_no_account_fails_twice(small_address_limit):
    slug, real_email = _tenant()
    spray = TestClient(app, client=("203.0.113.50", 4000))
    for i in range(6):  # one failure per distinct email: no per-account limit is ever near
        assert _login(spray, slug, f"victim{i}-{uuid.uuid4().hex[:4]}@example.test", "Summer2026!!!!").status_code == 401
    refused = _login(spray, slug, real_email, PASSWORD)  # even a correct login from the sprayer is refused
    assert refused.status_code == 429


def test_a_different_address_is_not_affected_by_someone_elses_spraying(small_address_limit):
    slug, real_email = _tenant()
    spray = TestClient(app, client=("203.0.113.51", 4000))
    for i in range(6):
        _login(spray, slug, f"v{i}-{uuid.uuid4().hex[:4]}@example.test", "wrong wrong wrong")
    honest = TestClient(app, client=("198.51.100.7", 4000))
    assert _login(honest, slug, real_email, PASSWORD).status_code == 200
