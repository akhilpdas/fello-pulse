"""domain/confidence.py: the abstain rule from contracts/features.md, with a
machine-readable reason -- the system must be able to say "I don't know"
rather than present thin evidence as healthy (FR-026, SC-012)."""

from __future__ import annotations

from pulse.domain.confidence import assess_confidence


def test_insufficient_history_abstains_with_that_reason():
    values = {"cov_days_of_history": 10, "cov_sources_with_data": 3, "cov_identity_unresolved": False}
    result = assess_confidence(values, min_days_history=30, min_sources_with_data=2)
    assert result.abstain is True
    assert result.reason == "insufficient_history"
    assert result.confidence == "low"


def test_insufficient_sources_abstains_with_that_reason():
    values = {"cov_days_of_history": 100, "cov_sources_with_data": 1, "cov_identity_unresolved": False}
    result = assess_confidence(values, min_days_history=30, min_sources_with_data=2)
    assert result.abstain is True
    assert result.reason == "insufficient_sources"


def test_unresolved_identity_abstains_with_that_reason():
    values = {"cov_days_of_history": 100, "cov_sources_with_data": 5, "cov_identity_unresolved": True}
    result = assess_confidence(values, min_days_history=30, min_sources_with_data=2)
    assert result.abstain is True
    assert result.reason == "no_billing_identity"


def test_sufficient_evidence_does_not_abstain():
    values = {"cov_days_of_history": 400, "cov_sources_with_data": 4, "cov_identity_unresolved": False}
    result = assess_confidence(values, min_days_history=30, min_sources_with_data=2)
    assert result.abstain is False
    assert result.confidence == "high"
    assert result.reason is None
