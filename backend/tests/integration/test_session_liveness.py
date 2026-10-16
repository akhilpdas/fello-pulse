"""T236 (FR-008): a session is only as good as the user behind it *now*. Disabling a user, or
demoting an operator, takes effect on their next request -- not when their session happens to expire.

Names the production change that makes the disable case fail: ``resolve_session`` must refuse a
session whose user has ``disabled_at`` set. (Demotion already works because the role is read live; that
half is a guard, not test-first.)
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import text

from pulse.api.main import app
from pulse.db.session import owner_session
from tests.auth_helpers import auth_headers, make_user
from tests.integration._agent_fixtures import seed_tenant

AS_OF = datetime(2026, 10, 1, tzinfo=UTC)


def test_a_disabled_user_is_locked_out_on_the_next_request():
    tenant_id, _ = seed_tenant(AS_OF)
    user = make_user(tenant_id, "operator")
    h = auth_headers(tenant_id, user)
    c = TestClient(app)
    assert c.get("/admin/config", headers=h).status_code == 200  # control: the session works
    with owner_session() as s:
        s.execute(text("UPDATE app_user SET disabled_at = now() WHERE id = :i"), {"i": user})
    assert c.get("/admin/config", headers=h).status_code == 401
    assert c.get("/auth/me", headers=h).status_code == 401


def test_a_demoted_operator_loses_operator_routes_on_the_next_request():  # GUARD: role is read live
    tenant_id, _ = seed_tenant(AS_OF)
    user = make_user(tenant_id, "operator")
    h = auth_headers(tenant_id, user)
    c = TestClient(app)
    assert c.get("/admin/config", headers=h).status_code == 200
    with owner_session() as s:
        s.execute(text("UPDATE app_user SET role = 'csm' WHERE id = :i"), {"i": user})
    assert c.get("/admin/config", headers=h).status_code == 403
