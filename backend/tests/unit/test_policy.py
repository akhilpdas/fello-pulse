"""agent/policy.py (T062): the reviewed boundary (constitution Principle III).
Every declined decision returns a reason. Pure function, no DB."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pulse.agent.policy import decide

NOW = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)


def _decide(**overrides):
    base = dict(
        human_suppressed=False, last_action_at=None, now=NOW, suppression_days=14,
        auto_send_allowlisted=False, sends_this_cycle=0, max_sends_per_cycle=25,
    )
    base.update(overrides)
    return decide(**base)


def test_human_suppressed_account_is_declined_entirely():
    d = _decide(human_suppressed=True)
    assert d.allow_draft is False
    assert d.allow_auto_send is False
    assert d.reason == "suppressed"


def test_inside_the_suppression_window_declines_entirely():
    d = _decide(last_action_at=NOW - timedelta(days=3), suppression_days=14)
    assert d.allow_draft is False
    assert d.reason == "suppression_window_active"


def test_outside_the_suppression_window_allows_a_draft():
    d = _decide(last_action_at=NOW - timedelta(days=15), suppression_days=14)
    assert d.allow_draft is True


def test_default_is_draft_only_without_an_allowlist_row():
    """Absence of a play_allowlist row is the safe default (constitution
    Principle III): draft for a human, never autonomous send -- and the
    withholding itself carries a reason, not a silent flag (T070)."""
    d = _decide(auto_send_allowlisted=False)
    assert d.allow_draft is True
    assert d.allow_auto_send is False
    assert d.reason == "not_allowlisted_for_auto_send"


def test_allowlisted_and_under_capacity_permits_auto_send():
    d = _decide(auto_send_allowlisted=True, sends_this_cycle=5, max_sends_per_cycle=25)
    assert d.allow_draft is True
    assert d.allow_auto_send is True
    assert d.reason is None


def test_allowlisted_but_rate_limited_drafts_without_sending():
    d = _decide(auto_send_allowlisted=True, sends_this_cycle=25, max_sends_per_cycle=25)
    assert d.allow_draft is True
    assert d.allow_auto_send is False
    assert d.reason == "rate_limit_reached"
