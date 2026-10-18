"""T083 (US6): GET /model serves the promoted model card as a report containing
the operating point, both baselines, calibration, per-tenant slices, lead time,
seed and version -- and says so explicitly when a section is not available
rather than omitting it."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

import pulse.api.deps as deps
from pulse.api.main import app
from tests.auth_helpers import auth_headers
from tests.integration._agent_fixtures import seed_tenant


def _card(version: str, promoted: bool, trained_at: str, **metrics_extra) -> dict:
    metrics = {
        "precision_at_capacity": 0.3, "captured_acv_at_capacity": 123.0, "roc_auc": 0.69,
        "pr_auc": 0.1, "brier": 0.03,
        "baseline_trivial": {"roc_auc": 0.5, "precision_at_capacity": 0.03},
        "baseline_heuristic": {"roc_auc": 0.6, "precision_at_capacity": 0.02},
        "per_tenant": {"northwind": {"n": 10, "positive_rate": 0.04, "pr_auc": 0.1, "roc_auc": 0.7}},
        **metrics_extra,
    }
    return {"version": version, "algorithm": "HGB", "feature_set_version": "fs-1", "feature_names": ["a"],
            "trained_at": trained_at, "train_window_start": "x", "train_window_end": "y",
            "horizon_days": 90, "seed": 7, "data_version": "dv", "metrics": metrics,
            "artifact_path": "p", "promoted": promoted, "promotion_note": "n"}


def _client(tmp_path: Path, cards: list[dict]) -> TestClient:
    for c in cards:
        (tmp_path / f"{c['version']}.json").write_text(json.dumps(c))
    app.dependency_overrides[deps.get_artifacts_dir] = lambda: tmp_path
    tenant_id, _ = seed_tenant(datetime(2026, 10, 1, tzinfo=UTC))
    return TestClient(app, headers=auth_headers(tenant_id, role="operator"))  # /model is operator-only


def teardown_function():
    app.dependency_overrides.pop(deps.get_artifacts_dir, None)


def test_report_has_every_required_section(tmp_path):
    card = _card("m-1", True, "2026-10-01", reliability=[{"predicted": 0.1, "observed": 0.09}],
                 operating_point={"capacity": 100}, lead_time_days={"median": 21})
    r = _client(tmp_path, [card]).get("/model")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == "m-1" and body["seed"] == 7
    assert body["operating_point"]["capacity"] == 100
    assert body["operating_point"]["precision_at_capacity"] == 0.3
    assert set(body["baselines"]) == {"trivial", "heuristic"}
    assert body["calibration"]["reliability"][0]["observed"] == 0.09
    assert "northwind" in body["per_tenant"]
    assert body["lead_time_days"] == {"median": 21}


def test_absent_calibration_and_lead_time_are_stated_not_omitted(tmp_path):
    r = _client(tmp_path, [_card("m-1", True, "2026-10-01")]).get("/model")
    body = r.json()
    assert body["calibration"]["available"] is False and body["calibration"]["reason"]
    assert body["lead_time_days"]["available"] is False and body["lead_time_days"]["reason"]


def test_serves_latest_promoted_and_ignores_unpromoted(tmp_path):
    cards = [_card("m-old", True, "2026-09-01"), _card("m-new", True, "2026-10-01"),
             _card("m-newest-unpromoted", False, "2026-10-10")]
    assert _client(tmp_path, cards).get("/model").json()["version"] == "m-new"


def test_404_when_nothing_is_promoted(tmp_path):
    assert _client(tmp_path, [_card("m-1", False, "2026-10-01")]).get("/model").status_code == 404


def test_nan_metric_in_a_slice_is_served_as_null_not_a_500(tmp_path):
    # A tenant slice with no positives has an undefined PR-AUC; the pipeline writes NaN.
    card = _card("m-1", True, "2026-10-01")
    card["metrics"]["per_tenant"]["tiny"] = {"n": 3, "positive_rate": 0.0, "pr_auc": float("nan"),
                                              "roc_auc": float("nan")}
    r = _client(tmp_path, [card]).get("/model")
    assert r.status_code == 200
    assert r.json()["per_tenant"]["tiny"]["pr_auc"] is None


# T209 (001/FR-018): leave-one-tenant-out is served, and its absence is stated, not omitted.
def test_leave_one_tenant_out_is_served_from_the_card(tmp_path):
    loto = {"northwind": {"n_train": 100, "n_test": 40, "roc_auc": 0.64, "precision_at_capacity": 0.2},
            "initech": {"n_train": 300, "n_test": 9, "roc_auc": None, "precision_at_capacity": 0.0}}
    r = _client(tmp_path, [_card("m-1", True, "2026-10-01", leave_one_tenant_out=loto)]).get("/model")
    assert r.json()["leave_one_tenant_out"] == loto


def test_missing_leave_one_tenant_out_is_stated_with_a_reason(tmp_path):
    r = _client(tmp_path, [_card("m-1", True, "2026-10-01")]).get("/model")
    section = r.json()["leave_one_tenant_out"]
    assert section["available"] is False and section["reason"]


def test_the_rolling_backtest_is_reported_when_the_pipeline_ran_it(tmp_path):
    backtest = {"method": "rolling origin", "auc_by_fold": [0.64, 0.62, 0.69, 0.71], "auc_mean": 0.665,
                "eval_weeks": 52, "n_folds": 4, "n_scored": 100, "lead_time": {}}
    body = _client(tmp_path, [_card("m-1", True, "2026-10-01", rolling_backtest=backtest)]).get("/model").json()
    assert body["rolling_backtest"]["auc_by_fold"] == [0.64, 0.62, 0.69, 0.71]
    assert body["rolling_backtest"]["auc_mean"] == 0.665


def test_a_card_without_a_backtest_says_so(tmp_path):
    body = _client(tmp_path, [_card("m-1", True, "2026-10-01")]).get("/model").json()
    assert body["rolling_backtest"]["available"] is False and body["rolling_backtest"]["reason"]
