"""The promoted model card as a report (T082, US6). Global, not tenant-scoped:
one shared model serves every tenant (clarifications B-7), so no tenant session. Operator-only
(002 / FR-004): it describes the shared model, including how it performs per tenant.

Sections the pipeline did not produce are reported as unavailable with a reason,
never silently omitted -- a report that hides its gaps is the failure mode.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from pulse.api.deps import get_artifacts_dir, require_operator

router = APIRouter()


def _unavailable(reason: str) -> dict:
    return {"available": False, "reason": reason}


def _nan_to_none(value):
    """Undefined metrics (e.g. PR-AUC on a slice with no positives) are NaN on disk,
    which is not valid JSON; the honest wire form is null."""
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, dict):
        return {k: _nan_to_none(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_nan_to_none(v) for v in value]
    return value


def _latest_promoted(directory: Path) -> dict | None:
    cards = [json.loads(p.read_text()) for p in directory.glob("*.json")] if directory.exists() else []
    promoted = [c for c in cards if c.get("promoted")]
    return max(promoted, key=lambda c: c["trained_at"]) if promoted else None


@router.get("/model", dependencies=[Depends(require_operator)])
def get_model_report(directory: Path = Depends(get_artifacts_dir)):
    card = _latest_promoted(directory)
    if card is None:
        raise HTTPException(status_code=404, detail="no promoted model")
    m = card["metrics"]
    reliability = m.get("reliability")
    lead = m.get("lead_time_days")
    return _nan_to_none({
        "version": card["version"], "algorithm": card["algorithm"], "seed": card["seed"],
        "data_version": card["data_version"], "feature_set_version": card["feature_set_version"],
        "trained_at": card["trained_at"], "horizon_days": card["horizon_days"],
        "promotion_note": card["promotion_note"],
        "operating_point": {
            **(m.get("operating_point") or {}),
            "precision_at_capacity": m["precision_at_capacity"],
            "captured_acv_at_capacity": m["captured_acv_at_capacity"],
        },
        "metrics": {k: m[k] for k in ("roc_auc", "pr_auc", "brier")},
        "baselines": {"trivial": m["baseline_trivial"], "heuristic": m["baseline_heuristic"]},
        "calibration": {"brier": m["brier"], "reliability": reliability} if reliability
        else _unavailable("reliability curve not recorded by the training pipeline"),
        "per_tenant": m.get("per_tenant", {}),
        "leave_one_tenant_out": m.get("leave_one_tenant_out")
        or _unavailable("the training pipeline that produced this model did not run leave-one-tenant-out"),
        "lead_time_days": lead if lead else _unavailable("this model was trained before the rolling backtest existed"),
        "rolling_backtest": m.get("rolling_backtest")
        or _unavailable("this model was trained before the rolling backtest existed"),
    })
