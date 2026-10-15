"""features/denylist.py: the single source of truth for what feature code may read.

Per contracts/ingestion.md, the denylisted event types are exactly
``crm.closed_lost`` and ``billing.subscription_deleted`` -- mechanically
downstream of the outcome, stored for labelling and the evidence trail, never
read by feature code. Per db/models.py's Account, the denied outcome columns
are ``lifecycle_state``, ``churned_at``, ``churn_kind``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pulse.features.denylist import (
    DENIED_ACCOUNT_FIELDS,
    DENIED_EVENT_TYPES,
    AccountFeatureInput,
    filter_denied_events,
)
from pulse.ingest.contracts import NormalizedEvent


def _event(event_type: str) -> NormalizedEvent:
    return NormalizedEvent(
        source="stripe", source_event_id="e1", event_type=event_type,
        source_account_ref="ref", occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        received_at=datetime(2026, 1, 1, tzinfo=UTC), payload={},
    )


def test_denied_event_types_match_the_ingestion_contract():
    assert {"crm.closed_lost", "billing.subscription_deleted"} == DENIED_EVENT_TYPES


def test_denied_account_fields_match_the_outcome_columns():
    assert {"lifecycle_state", "churned_at", "churn_kind"} == DENIED_ACCOUNT_FIELDS


def test_filter_denied_events_drops_denylisted_types_only():
    events = [_event("billing.invoice_paid"), _event("billing.subscription_deleted"),
              _event("crm.closed_lost"), _event("support.ticket_created")]
    kept = filter_denied_events(events)
    assert [e.event_type for e in kept] == ["billing.invoice_paid", "support.ticket_created"]


def test_account_feature_input_cannot_structurally_hold_outcome_fields():
    row = {
        "segment": "mid", "industry": "saas", "region": "us", "seats": 42,
        "acv_cents": 1000, "mrr_cents": 90, "renewal_date": None,
        "signup_date": datetime(2024, 1, 1).date(),
        # Outcome fields present on the raw row but must never surface on the
        # feature-facing object -- not filtered, structurally absent.
        "lifecycle_state": "churned", "churned_at": datetime(2026, 1, 1, tzinfo=UTC),
        "churn_kind": "churn",
    }
    out = AccountFeatureInput.from_row(row)
    assert not hasattr(out, "lifecycle_state")
    assert not hasattr(out, "churned_at")
    assert not hasattr(out, "churn_kind")
    assert out.segment == "mid"
    assert out.seats == 42
