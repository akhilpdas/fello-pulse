"""Honest metrics at the operating point the business actually uses
(constitution: "Honest metrics"). Aggregate AUCs are reported, but the numbers
that matter are precision@capacity and captured-ACV@capacity -- the bounded
weekly queue a CSM actually works, not an abstract ranking over the whole
estate.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import numpy as np
from sklearn.calibration import calibration_curve
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score


def roc_auc(y_true, y_prob) -> float:
    return float(roc_auc_score(y_true, y_prob))


def pr_auc(y_true, y_prob) -> float:
    return float(average_precision_score(y_true, y_prob))


def brier(y_true, y_prob) -> float:
    return float(brier_score_loss(y_true, y_prob))


def reliability_curve(y_true, y_prob, n_bins: int = 10) -> list[dict]:
    observed, predicted = calibration_curve(y_true, y_prob, n_bins=n_bins, strategy="quantile")
    return [{"predicted": float(p), "observed": float(o)} for p, o in zip(predicted, observed, strict=True)]


def _top_n_indices(y_prob, capacity: int) -> np.ndarray:
    capacity = min(capacity, len(y_prob))
    return np.argsort(-np.asarray(y_prob))[:capacity]


def precision_at_capacity(y_true, y_prob, capacity: int) -> float:
    y_true = np.asarray(y_true)
    idx = _top_n_indices(y_prob, capacity)
    if len(idx) == 0:
        return 0.0
    return float(y_true[idx].mean())


def captured_acv_at_capacity(y_true, y_prob, value_at_risk, capacity: int) -> float:
    """Fraction of the total at-risk value among true positives that the
    top-``capacity`` queue would actually have surfaced."""
    y_true = np.asarray(y_true)
    value_at_risk = np.asarray(value_at_risk, dtype=float)
    total_at_risk = value_at_risk[y_true == 1].sum()
    if total_at_risk == 0:
        return 0.0
    idx = _top_n_indices(y_prob, capacity)
    caught = value_at_risk[idx][y_true[idx] == 1].sum()
    return float(caught / total_at_risk)


def trivial_baseline(y_true, n: int) -> np.ndarray:
    """Predicts the base rate for everyone -- the floor any model must beat."""
    rate = float(np.mean(y_true))
    return np.full(n, rate)


def heuristic_baseline_score(feature_values: dict) -> float:
    """The rule a human would write without a model: more support trouble and
    more payment friction means more risk. Used as the bar the fitted model
    must clear, per FR-020 -- not a strawman, a real hand-built alternative."""
    tickets = feature_values.get("support_p1_tickets_28d") or 0.0
    reopened = feature_values.get("support_reopened_28d") or 0.0
    failed_payments = feature_values.get("billing_failed_payments_90d") or 0.0
    dunning = 1.0 if feature_values.get("billing_dunning_active") else 0.0
    inactivity = feature_values.get("usage_days_since_last_activity") or 0.0
    score = (
        0.35 * min(tickets, 10) / 10
        + 0.15 * min(reopened, 5) / 5
        + 0.2 * min(failed_payments, 5) / 5
        + 0.15 * dunning
        + 0.15 * min(inactivity, 60) / 60
    )
    return float(min(max(score, 0.0), 1.0))


@dataclass(frozen=True, slots=True)
class TenantMetrics:
    tenant: str
    n: int
    positive_rate: float
    pr_auc: float
    roc_auc: float
    brier: float


def per_tenant_metrics(tenant_ids: list, y_true, y_prob) -> list[TenantMetrics]:
    y_true = np.asarray(y_true)
    y_prob = np.asarray(y_prob)
    groups: dict = defaultdict(list)
    for i, t in enumerate(tenant_ids):
        groups[t].append(i)
    out = []
    for tenant, idx in groups.items():
        idx = np.array(idx)
        yt, yp = y_true[idx], y_prob[idx]
        if len(set(yt.tolist())) < 2:
            # Can't compute AUC-family metrics with a single class present;
            # report what is still honestly computable.
            out.append(TenantMetrics(tenant, len(idx), float(yt.mean()), float("nan"), float("nan"), brier(yt, yp)))
            continue
        out.append(TenantMetrics(
            tenant, len(idx), float(yt.mean()), pr_auc(yt, yp), roc_auc(yt, yp), brier(yt, yp),
        ))
    return out


class ImplausiblePerformance(AssertionError):
    """Raised when a backtest AUC exceeds the plausibility ceiling -- evidence
    of a broken harness (leakage), not a good model (settings.auc_plausibility_ceiling)."""


def check_plausibility(auc: float, ceiling: float) -> None:
    if auc > ceiling:
        raise ImplausiblePerformance(
            f"test AUC {auc:.4f} exceeds the plausibility ceiling {ceiling:.4f} -- "
            "this is evidence of leakage, not a good model. Fix the harness before trusting it."
        )


def lead_time_days(as_of_times: list, flagged_mask: list[bool], outcome_at) -> int | None:
    """Days of warning: time between the first as_of where the account was
    flagged and the outcome actually occurring. None if never flagged."""
    flagged_times = [t for t, f in zip(as_of_times, flagged_mask, strict=True) if f]
    if not flagged_times or outcome_at is None:
        return None
    first_flag = min(flagged_times)
    return (outcome_at - first_flag).days
