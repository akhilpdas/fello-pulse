"""The abstain rule (contracts/features.md). A score the system cannot trust
is routed to an explicit low-confidence state with a machine-readable reason,
never silently presented as healthy (FR-026, SC-012).

The three conditions and their reasons are checked in the order the contract
states them; the first one that fires is the reported reason.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConfidenceResult:
    confidence: str  # "high" | "low"
    abstain: bool
    reason: str | None


def assess_confidence(
    feature_values: dict, min_days_history: int, min_sources_with_data: int
) -> ConfidenceResult:
    days = feature_values.get("cov_days_of_history") or 0
    sources = feature_values.get("cov_sources_with_data") or 0
    unresolved = bool(feature_values.get("cov_identity_unresolved"))

    if days < min_days_history:
        return ConfidenceResult("low", True, "insufficient_history")
    if sources < min_sources_with_data:
        return ConfidenceResult("low", True, "insufficient_sources")
    if unresolved:
        return ConfidenceResult("low", True, "no_billing_identity")
    return ConfidenceResult("high", False, None)


# What a person can do about each abstain reason (the low-confidence surface
# shows these beside the reason code, so a low-confidence account is a task
# with a next step, not a dead end).
REMEDIES = {
    "insufficient_history": "Too little history to score reliably. Re-check once more activity has accumulated, or review the account manually.",
    "insufficient_sources": "Too few connected data sources have data for this account. Connect or repair the missing sources.",
    "no_billing_identity": "The account could not be matched to a billing record. Resolve the identity link so billing signals count.",
}
