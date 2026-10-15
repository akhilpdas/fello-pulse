"""FR-010 / constitution Principle I: denylisted event types are mechanically
downstream of the outcome and must have provably zero effect on the feature
vector -- not filtered by convention, unreachable by construction."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pulse.features.compute import EventRecord, compute
from pulse.features.denylist import AccountFeatureInput

AS_OF = datetime(2026, 3, 11, 9, 0, tzinfo=UTC)


def _account() -> AccountFeatureInput:
    return AccountFeatureInput.from_row({"signup_date": datetime(2024, 1, 1).date()})


def _allowed_events() -> list[EventRecord]:
    return [
        EventRecord(1, "stripe", "billing.invoice_paid",
                    occurred_at=AS_OF - timedelta(days=10), received_at=AS_OF - timedelta(days=10),
                    payload={"invoice_ref": "in_1", "amount_cents": 50000,
                             "due_at": (AS_OF - timedelta(days=12)).isoformat(),
                             "paid_at": (AS_OF - timedelta(days=10)).isoformat()}),
        EventRecord(2, "salesforce", "crm.opportunity_stage_changed",
                    occurred_at=AS_OF - timedelta(days=20), received_at=AS_OF - timedelta(days=20),
                    payload={"opportunity_ref": "opp-1", "stage": "Negotiation", "amount_cents": 50000}),
    ]


def test_denylisted_events_have_zero_effect_on_the_feature_vector():
    connected = frozenset({"stripe", "salesforce"})
    without = compute(connected_sources=connected, account=_account(), events=_allowed_events(), as_of=AS_OF)

    denylisted = [
        EventRecord(3, "stripe", "billing.subscription_deleted",
                    occurred_at=AS_OF - timedelta(days=1), received_at=AS_OF - timedelta(days=1),
                    payload={"subscription_ref": "sub_1", "reason": "cancelled"}),
        EventRecord(4, "salesforce", "crm.closed_lost",
                    occurred_at=AS_OF - timedelta(days=1), received_at=AS_OF - timedelta(days=1),
                    payload={"opportunity_ref": "opp-1", "stage": "Closed Lost", "amount_cents": 50000}),
    ]
    with_denylisted = compute(
        connected_sources=connected, account=_account(),
        events=_allowed_events() + denylisted, as_of=AS_OF,
    )

    assert with_denylisted.values == without.values
    # And the ids never show up as evidence for anything.
    all_evidence_ids = {i for ids in with_denylisted.evidence.values() for i in ids}
    assert 3 not in all_evidence_ids
    assert 4 not in all_evidence_ids


def test_outcome_account_columns_are_structurally_absent_from_compute_input():
    """compute() is only ever handed an AccountFeatureInput, which cannot carry
    lifecycle_state/churned_at/churn_kind -- see test_denylist.py for the
    construction-time proof. This test confirms compute() doesn't need them to
    run, i.e. it has no code path that assumes their presence."""
    account = _account()
    assert not hasattr(account, "lifecycle_state")
    result = compute(connected_sources=frozenset(), account=account, events=[], as_of=AS_OF)
    assert isinstance(result.values, dict)
