"""T227 (SC-002): no data route is reachable without a verified session. Iterates the application's
own route table, so a route added later without authentication fails this test instead of shipping open.

Names the production change that makes it fail: any route (today ``GET /model``) that does not depend
on ``get_principal``.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from pulse.api.main import app

PUBLIC = {("POST", "/auth/login"), ("GET", "/docs"), ("GET", "/openapi.json"), ("GET", "/redoc"),
          ("GET", "/docs/oauth2-redirect")}
_SAMPLE_UUID = "00000000-0000-0000-0000-000000000001"


def _routes():
    """Every (method, path) the application serves, read from its own OpenAPI schema -- which
    sees through however routers are nested, unlike walking ``app.routes``."""
    for path, ops in app.openapi()["paths"].items():
        for method in ops:
            if (method.upper(), path) not in PUBLIC:
                yield method.upper(), path


def test_every_non_public_route_is_401_without_a_session():
    client = TestClient(app, raise_server_exceptions=False)
    unguarded = []
    for method, path in _routes():
        url = path.replace("{action_id}", _SAMPLE_UUID).replace("{account_id}", _SAMPLE_UUID).replace(
            "{id}", _SAMPLE_UUID).replace("{play_key}", "support_recovery").replace("{user_id}", _SAMPLE_UUID)
        r = client.request(method, url, json={})
        if r.status_code != 401:
            unguarded.append(f"{method} {path} -> {r.status_code}")
    assert not unguarded, "routes reachable without authentication:\n  " + "\n  ".join(unguarded)


def test_the_sweep_actually_covers_routes():
    assert len(list(_routes())) >= 15  # guards against the iteration silently matching nothing
