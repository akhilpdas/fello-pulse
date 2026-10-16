"""T274 (FR-024, FR-030): the *only* material a language model is given about an account is a short list of
facts derived deterministically from the features the system already computed. No ticket subject, email body or
free text from any source can reach it.

Names the production change that makes it fail: ``pulse.agent.grounding.build_facts``.
"""

from __future__ import annotations

import pytest

from pulse.agent.grounding import build_facts


def test_support_facts_state_the_real_numbers():
    facts = build_facts("support_experience", {
        "support_tickets_28d": 7.0, "support_p1_tickets_28d": 2.0, "support_median_first_response_h_28d": 31.46,
        "support_max_unresolved_age_days": 9.0, "support_reopened_28d": 0.0, "support_negative_csat_share_90d": None})
    assert "7 support tickets in the last 28 days" in facts
    assert "2 of them were urgent (P1)" in facts
    assert "the median first response took 31.5 hours" in facts
    assert "the oldest open ticket is 9 days old" in facts
    assert not any("reopened" in f for f in facts)  # zero is not a fact worth stating
    assert not any("rating" in f for f in facts)    # an absent value is omitted, never guessed


def test_each_play_driver_has_facts_and_an_unknown_driver_has_none():
    sample = {"usage_active_users_28d": 3.0, "seats": 45, "usage_days_since_last_activity": 29.0,
              "billing_failed_payments_90d": 2.0, "billing_dunning_active": True,
              "crm_days_since_meeting": 273.0, "crm_qbr_done_180d": False, "days_to_renewal": 39.0}
    for driver in ("usage_decline", "payment_friction", "relationship_engagement", "commercial_signals"):
        assert build_facts(driver, sample), driver
    assert build_facts("something_else", sample) == []
    assert "3 active users in the last 28 days, on 45 seats" in build_facts("usage_decline", sample)
    assert "the renewal is in 39 days" in build_facts("commercial_signals", sample)


def test_facts_are_deterministic_and_all_values_absent_gives_nothing():
    values = {"support_tickets_28d": 4.0}
    assert build_facts("support_experience", values) == build_facts("support_experience", dict(values))
    assert build_facts("support_experience", {}) == []


@pytest.mark.parametrize("driver", ["support_experience", "usage_decline", "payment_friction",
                                    "relationship_engagement", "commercial_signals"])
def test_facts_are_short_plain_sentences_with_no_markup_or_urls(driver):
    values = {k: 5.0 for k in ("support_tickets_28d", "support_p1_tickets_28d", "usage_active_users_28d", "seats",
                               "usage_days_since_last_activity", "billing_failed_payments_90d",
                               "crm_days_since_meeting", "days_to_renewal", "email_days_since_customer_reply")}
    for f in build_facts(driver, values):
        assert len(f) <= 120 and "http" not in f and "<" not in f and "\n" not in f
