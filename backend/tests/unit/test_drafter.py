"""agent/drafter.py (T063 + T074): the deterministic template drafter, and
grounding validation that rejects a claim not backed by evidence actually
gathered for the score (FR on grounding)."""

from __future__ import annotations

import pytest

from pulse.agent.drafter import draft, draft_template, validate_grounding


def test_template_draft_is_deterministic_and_personalised():
    d1 = draft_template("support_recovery", account_name="Acme Co", csm_name="Dana")
    d2 = draft_template("support_recovery", account_name="Acme Co", csm_name="Dana")
    assert d1 == d2
    assert "Acme Co" in d1.body
    assert d1.draft_source == "template"


def test_unknown_play_key_raises():
    with pytest.raises(KeyError):
        draft_template("not_a_real_play", account_name="Acme", csm_name="Dana")


def test_draft_falls_back_to_template_when_llm_disabled():
    """Constitution Principle II: the system is fully functional with no LLM
    configured. The default dispatcher must never require one."""
    d = draft("adoption_nudge", account_name="Acme", csm_name="Dana", llm_enabled=False)
    assert d.draft_source == "template"


def test_grounding_passes_when_every_claim_has_nonempty_evidence():
    d = draft_template("support_recovery", account_name="Acme", csm_name="Dana")
    ok, reason = validate_grounding(d, {"support_experience"})
    assert ok is True
    assert reason is None


def test_grounding_rejects_a_claim_with_no_backing_evidence():
    d = draft_template("support_recovery", account_name="Acme", csm_name="Dana")
    ok, reason = validate_grounding(d, set())
    assert ok is False
    assert "support_experience" in reason
