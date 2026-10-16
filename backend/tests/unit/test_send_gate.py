"""T258 (FR-014, FR-015, FR-016): nothing leaves unless every precondition holds, and each way of not
leaving is a distinct, named state -- so an operator can tell "switched off" from "no sender" from "no
address" from "asked us to stop". Pure: no I/O, so the whole truth table is testable.

Names the production change that makes it fail: ``pulse.domain.send_gate.decide_send``.
"""

from __future__ import annotations

import itertools

import pytest

from pulse.domain.send_gate import decide_send

OK = dict(outbound_enabled=True, sender_address="csm@northwind.example.com", sender_verified=True,
          smtp_configured=True, demo_mode=False, contact_email="sofia@acme.example.com", opted_out=False)


def _d(**over):
    return decide_send(**{**OK, **over})


def test_everything_in_place_is_allowed():
    d = _d()
    assert d.allowed and d.state == "ok" and d.reason is None


@pytest.mark.parametrize("over,state", [
    (dict(outbound_enabled=False), "outbound_disabled"),
    (dict(sender_address=None), "not_configured"),
    (dict(sender_address=""), "not_configured"),
    (dict(sender_verified=False), "not_configured"),
    (dict(smtp_configured=False), "not_configured"),
    (dict(contact_email=None), "no_recipient"),
    (dict(contact_email="  "), "no_recipient"),
    (dict(opted_out=True), "opted_out"),
])
def test_each_failure_is_its_own_state_with_a_reason(over, state):
    d = _d(**over)
    assert not d.allowed and d.state == state and d.reason


def test_demo_mode_without_a_smtp_server_is_captured_not_blocked():
    d = _d(smtp_configured=False, demo_mode=True)
    assert d.allowed and d.state == "ok"  # the demo path records the message; nothing real is sent


def test_demo_mode_never_excuses_a_missing_recipient_or_an_opt_out():
    assert _d(demo_mode=True, contact_email=None).state == "no_recipient"
    assert _d(demo_mode=True, opted_out=True).state == "opted_out"
    assert _d(demo_mode=True, outbound_enabled=False).state == "outbound_disabled"


def test_precedence_is_stable_so_the_reported_reason_is_the_first_thing_to_fix():
    worst = dict(outbound_enabled=False, sender_address=None, contact_email=None, opted_out=True)
    assert _d(**worst).state == "outbound_disabled"
    assert _d(**{**worst, "outbound_enabled": True}).state == "not_configured"
    assert _d(**{**worst, "outbound_enabled": True, "sender_address": "a@b.example.com"}).state == "no_recipient"


def test_only_one_combination_of_the_four_switches_allows_a_real_send():
    allowed = []
    for enabled, verified, smtp, has_to in itertools.product([True, False], repeat=4):
        d = _d(outbound_enabled=enabled, sender_verified=verified, smtp_configured=smtp,
               contact_email="a@b.example.com" if has_to else None)
        if d.allowed:
            allowed.append((enabled, verified, smtp, has_to))
    assert allowed == [(True, True, True, True)]
