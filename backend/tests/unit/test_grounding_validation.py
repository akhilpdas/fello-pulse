"""T074: an unsupported claim is rejected before a human (or an auto-send)
ever sees it. The mechanism itself is implemented and unit-tested alongside
the drafter in test_drafter.py; this file is the dedicated T074 target named
in tasks.md, covering the multi-claim case that file doesn't."""

from __future__ import annotations

from pulse.agent.drafter import Draft, validate_grounding


def test_a_draft_with_every_claim_grounded_is_accepted():
    d = Draft(subject="s", body="b", draft_source="template", claims=["support_experience"])
    ok, reason = validate_grounding(d, {"support_experience", "usage_decline"})
    assert ok is True
    assert reason is None


def test_a_draft_with_one_ungrounded_claim_among_several_is_rejected():
    d = Draft(
        subject="s", body="b", draft_source="template",
        claims=["support_experience", "payment_friction"],
    )
    ok, reason = validate_grounding(d, {"support_experience"})
    assert ok is False
    assert "payment_friction" in reason
    assert "support_experience" not in reason


def test_a_draft_with_no_claims_is_trivially_grounded():
    d = Draft(subject="s", body="b", draft_source="template", claims=[])
    ok, reason = validate_grounding(d, set())
    assert ok is True
    assert reason is None
