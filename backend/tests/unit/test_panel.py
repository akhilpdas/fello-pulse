"""ml/panel.py: weekly account-level snapshots (clarifications B-4). For each
Monday from the account's first activity to (dataset_end - horizon), compute
features as-of that Monday and the label from the following horizon."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from pulse.features.compute import EventRecord
from pulse.features.denylist import AccountFeatureInput
from pulse.ml.panel import build_account_panel, monday_on_or_after


def test_monday_on_or_after_a_monday_is_itself():
    assert monday_on_or_after(date(2026, 1, 5)) == date(2026, 1, 5)  # a Monday


def test_monday_on_or_after_rolls_forward_to_the_next_monday():
    assert monday_on_or_after(date(2026, 1, 7)) == date(2026, 1, 12)  # Wed -> next Mon


def test_panel_has_one_row_per_monday_in_the_observable_range():
    first_event = datetime(2026, 1, 5, 9, tzinfo=UTC)  # a Monday
    events = [
        EventRecord(1, "zendesk", "support.ticket_created", first_event, first_event,
                    {"ticket_ref": "t1", "priority": "low", "subject": "x", "requester_ref": "u1"}),
    ]
    dataset_end = datetime(2026, 2, 2, 0, tzinfo=UTC)  # 4 weeks later
    rows = build_account_panel(
        account_id="acct-1", connected_sources=frozenset({"zendesk"}),
        account_input=AccountFeatureInput.from_row({"signup_date": date(2025, 1, 1)}),
        events=events, contraction_threshold=0.25, horizon_days=0, dataset_end=dataset_end,
    )
    mondays = {r.as_of.date() for r in rows}
    assert mondays == {date(2026, 1, 5), date(2026, 1, 12), date(2026, 1, 19), date(2026, 1, 26)}


def test_panel_excludes_mondays_too_close_to_dataset_end_to_observe_the_full_horizon():
    first_event = datetime(2026, 1, 5, 9, tzinfo=UTC)
    events = [
        EventRecord(1, "zendesk", "support.ticket_created", first_event, first_event,
                    {"ticket_ref": "t1", "priority": "low", "subject": "x", "requester_ref": "u1"}),
    ]
    dataset_end = datetime(2026, 1, 20, 0, tzinfo=UTC)
    rows = build_account_panel(
        account_id="acct-1", connected_sources=frozenset({"zendesk"}),
        account_input=AccountFeatureInput.from_row({"signup_date": date(2025, 1, 1)}),
        events=events, contraction_threshold=0.25, horizon_days=90, dataset_end=dataset_end,
    )
    assert rows == []  # no Monday can see a full 90-day future inside a 15-day dataset


def test_panel_row_label_reflects_outcome_in_its_own_horizon():
    first_event = datetime(2026, 1, 5, 9, tzinfo=UTC)
    cancel = EventRecord(2, "stripe", "billing.subscription_deleted",
                          first_event + timedelta(days=20), first_event + timedelta(days=20),
                          {"subscription_ref": "s1", "reason": "x"})
    events = [
        EventRecord(1, "zendesk", "support.ticket_created", first_event, first_event,
                    {"ticket_ref": "t1", "priority": "low", "subject": "x", "requester_ref": "u1"}),
        cancel,
    ]
    # Generous dataset_end: both Mondays checked below need their own full
    # 90-day horizon observable inside it, with no censoring.
    dataset_end = datetime(2026, 7, 1, 0, tzinfo=UTC)
    rows = build_account_panel(
        account_id="acct-1", connected_sources=frozenset({"zendesk", "stripe"}),
        account_input=AccountFeatureInput.from_row({"signup_date": date(2025, 1, 1)}),
        events=events, contraction_threshold=0.25, horizon_days=90, dataset_end=dataset_end,
    )
    by_date = {r.as_of.date(): r.label for r in rows}
    # The Monday of week 1 (2026-01-05) sees the cancellation 20 days later --
    # inside a 90-day horizon -- so it must be labelled True.
    assert by_date[date(2026, 1, 5)] is True
    # A much later Monday, after the cancellation already happened, sees nothing
    # new ahead of it within its own horizon.
    assert by_date[date(2026, 3, 2)] is False


def test_panel_row_carries_the_date_of_the_outcome_its_label_refers_to():
    # Lead time needs to know *when* the loss happened, not only that one did (clarifications B-21).
    first_event = datetime(2026, 1, 5, 9, tzinfo=UTC)
    cancel_at = first_event + timedelta(days=20)
    events = [
        EventRecord(1, "zendesk", "support.ticket_created", first_event, first_event,
                    {"ticket_ref": "t1", "priority": "low", "subject": "x", "requester_ref": "u1"}),
        EventRecord(2, "stripe", "billing.subscription_deleted", cancel_at, cancel_at,
                    {"subscription_ref": "s1", "reason": "x"}),
    ]
    rows = build_account_panel(
        account_id="acct-1", connected_sources=frozenset({"zendesk", "stripe"}),
        account_input=AccountFeatureInput.from_row({"signup_date": date(2025, 1, 1)}),
        events=events, contraction_threshold=0.25, horizon_days=28, dataset_end=datetime(2026, 4, 1, tzinfo=UTC),
    )
    by_day = {r.as_of.date(): r for r in rows}
    assert by_day[date(2026, 1, 5)].label and by_day[date(2026, 1, 5)].outcome_at == cancel_at
    assert not by_day[date(2026, 2, 16)].label and by_day[date(2026, 2, 16)].outcome_at is None
