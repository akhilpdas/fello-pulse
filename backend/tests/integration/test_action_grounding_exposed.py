"""T088 backend need: the draft is reviewed beside the evidence that grounds it,
so the action API must return the grounding the drafter recorded."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy import text

from pulse.api.main import app
from pulse.db.session import owner_session
from tests.integration.test_action_lifecycle import _seed_minimal_action


def test_list_actions_returns_the_recorded_grounding():
    tenant_id, action_id, _ = _seed_minimal_action()
    grounding = {"evidence_drivers": ["support"]}
    with owner_session() as s:
        s.execute(text("UPDATE action SET grounding = CAST(:g AS jsonb) WHERE id = :i"),
                  {"g": json.dumps(grounding), "i": action_id})
    rows = TestClient(app).get("/actions", headers={"X-Tenant-Id": str(tenant_id)}).json()["rows"]
    assert rows[0]["grounding"] == grounding
