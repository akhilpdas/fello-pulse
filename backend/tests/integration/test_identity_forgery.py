"""T225 (FR-001, FR-002, FR-003, SC-001, SC-002): identity comes from the verified credential and
nowhere else. A forged tenant id changes nothing; a missing, malformed, expired, tampered or
wrong-tenant credential is refused *before* any tenant-scoped work is done for the request.

Names the production change that makes it fail: ``deps.get_session`` must derive the tenant claim
from ``get_principal`` and stop reading ``X-Tenant-Id``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import pulse.api.deps as deps
from pulse.api.main import app
from pulse.auth.sessions import create_session
from pulse.db.session import tenant_session as real_tenant_session
from tests.auth_helpers import auth_headers, make_user
from tests.integration._agent_fixtures import seed_scored_account


def _queue_ids(client, headers) -> list[str]:
    r = client.get("/queue", headers=headers)
    assert r.status_code == 200, r.text
    return [row["account_id"] for row in r.json()["rows"]]


def test_a_forged_tenant_header_changes_nothing():
    a, acct_a, _ = seed_scored_account("forge-a")
    b, acct_b, _ = seed_scored_account("forge-b")
    c = TestClient(app)
    assert _queue_ids(c, auth_headers(a)) == [str(acct_a)]  # control: A's own session sees A
    forged = {**auth_headers(a), "X-Tenant-Id": str(b), "X-User-Id": str(uuid.uuid4())}
    assert _queue_ids(c, forged) == [str(acct_a)]  # still A, not B
    assert str(acct_b) not in _queue_ids(c, forged)


def test_a_header_alone_is_not_credentials():
    tenant, _, _ = seed_scored_account("forge-c")
    r = TestClient(app).get("/queue", headers={"X-Tenant-Id": str(tenant)})
    assert r.status_code == 401


def _bad_credentials():
    a, _, _ = seed_scored_account("forge-d")
    b, _, _ = seed_scored_account("forge-e")
    user_a = make_user(a)
    expired = create_session(a, user_a, now=datetime.now(UTC) - timedelta(days=2), ttl=timedelta(hours=1))
    real = create_session(a, user_a, now=datetime.now(UTC), ttl=timedelta(hours=1))
    _, secret = real.split(".", 1)
    return {
        "no credential": {},
        "garbage token": {"Authorization": "Bearer not-a-token"},
        "unknown tenant prefix": {"Authorization": f"Bearer {uuid.uuid4()}.{secret}"},
        "right secret, wrong tenant": {"Authorization": f"Bearer {b}.{secret}"},
        "tampered secret": {"Authorization": f"Bearer {a}.{secret[:-2]}xx"},
        "expired": {"Authorization": f"Bearer {expired}"},
    }


@pytest.mark.parametrize("which", [
    "no credential", "garbage token", "unknown tenant prefix", "right secret, wrong tenant",
    "tampered secret", "expired"])
def test_bad_credentials_are_refused_and_no_tenant_session_is_opened_for_the_request(which, monkeypatch):
    headers = _bad_credentials()[which]
    opened = []

    def spy(tenant_id):
        opened.append(tenant_id)
        return real_tenant_session(tenant_id)

    monkeypatch.setattr(deps, "tenant_session", spy)  # the one the data routes use
    r = TestClient(app).get("/queue", headers=headers)
    assert r.status_code == 401, which
    assert opened == [], f"{which}: a tenant-scoped session was opened for an unauthenticated request"
