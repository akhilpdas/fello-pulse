"""TreeSHAP contributions, summed into the six driver groups.

Forty raw SHAP values is not an explanation a CSM can act on (research 5 /
contracts/features.md); the six driver groups are. ``explain.py`` computes the
exact per-feature attribution and then performs the sum -- the arithmetic a
reviewer or a CSM can check, never a second model standing in for the real one.
"""

from __future__ import annotations

import shap

from pulse.features.registry import REGISTRY
from pulse.ml.train import FEATURE_NAMES, TrainedModel, feature_matrix


def contributions(model: TrainedModel, feature_values: dict) -> dict[str, float]:
    idx = [FEATURE_NAMES.index(n) for n in model.feature_names]
    x = feature_matrix([feature_values])[:, idx]
    explainer = shap.TreeExplainer(model.base)
    shap_values = explainer.shap_values(x)
    return {name: float(val) for name, val in zip(model.feature_names, shap_values[0], strict=True)}


def expected_value(model: TrainedModel) -> float:
    """TreeExplainer's base value -- contributions reconcile to the base
    model's raw (log-odds) output as ``sum(contributions) + expected_value``.
    Used to prove no score persists without evidence that actually accounts
    for its own prediction (tests/integration/test_evidence_trail.py)."""
    explainer = shap.TreeExplainer(model.base)
    ev = explainer.expected_value
    return float(ev[0] if hasattr(ev, "__len__") else ev)


def driver_contributions(per_feature: dict[str, float]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for name, value in per_feature.items():
        driver = REGISTRY[name].driver
        totals[driver] = totals.get(driver, 0.0) + value
    return totals


def dominant_driver(driver_totals: dict[str, float]) -> str | None:
    if not driver_totals:
        return None
    return max(driver_totals, key=lambda k: abs(driver_totals[k]))
