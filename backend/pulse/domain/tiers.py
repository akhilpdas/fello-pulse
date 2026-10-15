"""Probability -> red/amber/green, from tenant-configured thresholds, plus the
0-100 "health score" a CSM reads on the queue row. Thresholds are per-tenant
configuration (tenant_config.tier_red_at / tier_amber_at), not constants --
clarifications A1/User Story 5."""

from __future__ import annotations


def tier_for(probability: float, tier_red_at: float, tier_amber_at: float) -> str:
    if probability >= tier_red_at:
        return "red"
    if probability >= tier_amber_at:
        return "amber"
    return "green"


def health_score(probability: float) -> int:
    """Higher is healthier. A display transform only -- ranking uses the raw
    probability, never this rounded number."""
    clipped = min(max(probability, 0.0), 1.0)
    return round((1.0 - clipped) * 100)
