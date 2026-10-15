"""SC-009: a feature vector computed as-of a given instant must be reproducible
from only the data that had actually arrived by then. Inserting a record that
arrives later must not change it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pulse.features.compute import EventRecord, compute
from pulse.features.denylist import AccountFeatureInput

AS_OF = datetime(2026, 3, 11, 9, 0, tzinfo=UTC)  # a Wednesday


def _account() -> AccountFeatureInput:
    return AccountFeatureInput.from_row({"signup_date": datetime(2024, 1, 1).date()})


def _base_events() -> list[EventRecord]:
    return [
        EventRecord(1, "zendesk", "support.ticket_created",
                    occurred_at=AS_OF - timedelta(days=5), received_at=AS_OF - timedelta(days=4),
                    payload={"ticket_ref": "t1", "priority": "high", "subject": "x", "requester_ref": "u1"}),
        EventRecord(2, "zendesk", "support.first_reply",
                    occurred_at=AS_OF - timedelta(days=4, hours=-2), received_at=AS_OF - timedelta(days=4),
                    payload={"ticket_ref": "t1", "response_minutes": 120.0}),
    ]


def test_an_event_that_arrives_after_as_of_does_not_change_the_vector():
    connected = frozenset({"zendesk"})
    before = compute(connected_sources=connected, account=_account(), events=_base_events(), as_of=AS_OF)

    late_arriving = EventRecord(
        3, "zendesk", "support.ticket_created",
        occurred_at=AS_OF - timedelta(days=1), received_at=AS_OF + timedelta(days=2),
        payload={"ticket_ref": "t2", "priority": "urgent", "subject": "y", "requester_ref": "u2"},
    )
    after = compute(
        connected_sources=connected, account=_account(),
        events=_base_events() + [late_arriving], as_of=AS_OF,
    )

    assert after.values == before.values


def test_received_at_filter_is_enforced_by_compute_itself_not_just_the_caller():
    """compute() must filter received_at <= as_of on its own, as defense in
    depth, even if a sloppy caller forgot to pre-filter."""
    connected = frozenset({"zendesk"})
    events = _base_events() + [
        EventRecord(9, "zendesk", "support.ticket_created",
                    occurred_at=AS_OF + timedelta(days=10), received_at=AS_OF + timedelta(days=10),
                    payload={"ticket_ref": "future", "priority": "urgent", "subject": "z",
                             "requester_ref": "u9"}),
    ]
    result = compute(connected_sources=connected, account=_account(), events=events, as_of=AS_OF)
    expected = compute(connected_sources=connected, account=_account(), events=_base_events(), as_of=AS_OF)
    assert result.values == expected.values
