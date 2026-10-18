"""One service, one origin: the API and the built UI behind a single port (spec 003, T016).

A free host runs one web service. The UI already calls ``/api/...`` (nginx strips the prefix in the container stack), so
the hosted wrapper does the same: ``/api/*`` is the existing application with the prefix removed; every other path is
the built UI, with a fallback to ``index.html`` so a browser refresh on ``/browse`` still works.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pulse.api.hosted import build_hosted_app


def _api() -> FastAPI:
    api = FastAPI()

    @api.get("/queue")
    def queue():
        return {"rows": []}

    return api


def _ui(tmp_path):
    (tmp_path / "index.html").write_text("<html>the app</html>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    return tmp_path


def _client(tmp_path):
    return TestClient(build_hosted_app(_api(), _ui(tmp_path)))


def test_the_api_is_served_under_the_api_prefix(tmp_path):
    r = _client(tmp_path).get("/api/queue")
    assert r.status_code == 200 and r.json() == {"rows": []}


def test_the_ui_is_served_at_the_root_and_its_assets_are_served_as_themselves(tmp_path):
    c = _client(tmp_path)
    assert "the app" in c.get("/").text
    assert c.get("/assets/app.js").text == "console.log(1)"


def test_a_browser_refresh_on_a_ui_route_gets_the_app_not_a_404(tmp_path):
    r = _client(tmp_path).get("/browse")
    assert r.status_code == 200 and "the app" in r.text


def test_an_unknown_api_path_is_a_json_404_never_the_app(tmp_path):
    r = _client(tmp_path).get("/api/nothing-here")
    assert r.status_code == 404 and r.headers["content-type"].startswith("application/json")


def test_the_real_application_answers_through_the_wrapper_and_still_demands_a_session(tmp_path):
    from pulse.api.main import app
    r = TestClient(build_hosted_app(app, _ui(tmp_path))).get("/api/queue")
    assert r.status_code == 401
