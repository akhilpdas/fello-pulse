"""T092: contracts/openapi.yaml is generated from the application and committed;
this fails whenever the API changes without regenerating it
(`python3 -m pulse.openapi_export`)."""

from __future__ import annotations

import json

import yaml

from pulse.api.main import app
from pulse.openapi_export import OPENAPI_PATH


def test_committed_openapi_matches_the_running_application():
    committed = yaml.safe_load(OPENAPI_PATH.read_text())
    assert committed == json.loads(json.dumps(app.openapi()))


def test_every_surface_the_frontend_uses_is_in_the_contract():
    paths = yaml.safe_load(OPENAPI_PATH.read_text())["paths"]
    for p in ("/queue", "/queue/low-confidence", "/accounts/{account_id}", "/runs", "/actions",
              "/model", "/admin/coverage"):
        assert p in paths, p
