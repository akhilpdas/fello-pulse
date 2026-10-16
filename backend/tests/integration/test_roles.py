"""T229 (FR-004, SC-003): operator-only capabilities are refused to a ``csm`` on the server, and an
operator is not refused on any of them. The UI hiding a nav item is courtesy; this is the control.

Names the production change that makes it fail: ``GET /model`` (the model report) must require the
operator role -- today any signed-in user may read it.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import pulse.api.deps as deps
from pulse.api.main import app
from tests.auth_helpers import auth_headers
from tests.integration._agent_fixtures import seed_tenant

OPERATOR_ROUTES = [
    ("GET", "/admin/config", None),
    ("PATCH", "/admin/config", {"weekly_capacity": 7}),
    ("GET", "/admin/allowlist", None),
    ("PUT", "/admin/allowlist/support_recovery", {"auto_send": False}),
    ("GET", "/admin/coverage", None),
    ("GET", "/model", None),
]


@pytest.fixture
def artifacts(tmp_path):
    card = {"version": "m-1", "algorithm": "HGB", "feature_set_version": "fs-1", "feature_names": ["a"],
            "trained_at": "2026-10-01", "train_window_start": "x", "train_window_end": "y",
            "horizon_days": 90, "seed": 7, "data_version": "dv", "promoted": True, "promotion_note": "n",
            "artifact_path": "p",
            "metrics": {"precision_at_capacity": 0.2, "captured_acv_at_capacity": 0.0, "roc_auc": 0.68,
                        "pr_auc": 0.1, "brier": 0.03,
                        "baseline_trivial": {"roc_auc": 0.5, "precision_at_capacity": 0.03},
                        "baseline_heuristic": {"roc_auc": 0.6, "precision_at_capacity": 0.02}}}
    (tmp_path / "m-1.json").write_text(json.dumps(card))
    app.dependency_overrides[deps.get_artifacts_dir] = lambda: Path(tmp_path)
    yield
    app.dependency_overrides.pop(deps.get_artifacts_dir, None)


@pytest.mark.parametrize("method,path,body", OPERATOR_ROUTES)
def test_a_csm_is_refused_and_an_operator_is_not(method, path, body, artifacts):
    tenant_id, _ = seed_tenant(datetime(2026, 10, 1, tzinfo=UTC))
    client = TestClient(app)
    csm = client.request(method, path, json=body, headers=auth_headers(tenant_id, role="csm"))
    assert csm.status_code == 403, f"{method} {path} let a csm in ({csm.status_code})"
    op = client.request(method, path, json=body, headers=auth_headers(tenant_id, role="operator"))
    assert op.status_code == 200, f"{method} {path} refused an operator ({op.status_code}: {op.text[:80]})"
