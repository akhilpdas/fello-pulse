"""FR-009: absence is not zero. None means the evidence needed to compute a
feature doesn't exist (a data problem); 0.0 means the evidence exists and the
count is genuinely zero (a customer fact). email_inbound_28d is the contract's
own example: None for a tenant with no Gmail connection, 0.0 for a customer who
has gone silent."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pulse.features.compute import EventRecord, compute
from pulse.features.denylist import AccountFeatureInput

AS_OF = datetime(2026, 3, 11, 9, 0, tzinfo=UTC)


def _account() -> AccountFeatureInput:
    return AccountFeatureInput.from_row({"signup_date": datetime(2024, 1, 1).date()})


def test_email_inbound_28d_is_none_when_tenant_has_no_gmail_source():
    result = compute(
        connected_sources=frozenset({"zendesk", "stripe"}),  # no gmail
        account=_account(), events=[], as_of=AS_OF,
    )
    assert result.values["email_inbound_28d"] is None


def test_email_inbound_28d_is_zero_for_a_connected_but_silent_customer():
    result = compute(
        connected_sources=frozenset({"gmail"}),
        account=_account(), events=[], as_of=AS_OF,
    )
    assert result.values["email_inbound_28d"] == 0.0


def test_email_inbound_28d_counts_real_inbound_events_when_present():
    events = [
        EventRecord(1, "gmail", "email.inbound",
                    occurred_at=AS_OF - timedelta(days=5), received_at=AS_OF - timedelta(days=5),
                    payload={"thread_ref": "t1", "direction": "inbound", "participants": ["u1"],
                             "subject": "Re: hi", "word_count": 40, "has_exec_participant": False,
                             "reply_lag_days": 1.0, "sentiment": 0.2}),
    ]
    result = compute(connected_sources=frozenset({"gmail"}), account=_account(), events=events, as_of=AS_OF)
    assert result.values["email_inbound_28d"] == 1.0


def test_support_tickets_28d_is_none_when_zendesk_not_connected():
    result = compute(connected_sources=frozenset({"gmail"}), account=_account(), events=[], as_of=AS_OF)
    assert result.values["support_tickets_28d"] is None


def test_support_tickets_28d_is_zero_when_connected_with_no_tickets():
    result = compute(connected_sources=frozenset({"zendesk"}), account=_account(), events=[], as_of=AS_OF)
    assert result.values["support_tickets_28d"] == 0.0


def test_usage_seat_utilisation_is_none_when_seats_unknown():
    events = [
        EventRecord(1, "product", "product.usage_daily",
                    occurred_at=AS_OF - timedelta(days=5), received_at=AS_OF - timedelta(days=5),
                    payload={"period_start": (AS_OF - timedelta(days=7)).date().isoformat(),
                             "period_days": 7, "active_users": 10, "sessions": 20,
                             "feature_keys": ["reports"], "seats_snapshot": None,
                             "daily": [{"date": (AS_OF - timedelta(days=5)).date().isoformat(),
                                        "active_users": 10, "sessions": 20}],
                             "user_refs": ["u1"]}),
    ]
    # No crm.account_updated ever -> seats unknown as-of.
    result = compute(connected_sources=frozenset({"product"}), account=_account(), events=events, as_of=AS_OF)
    assert result.values["usage_seat_utilisation"] is None
    assert result.values["seats"] is None
