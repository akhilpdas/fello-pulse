"""The single source of truth for what feature code may read.

Two things are denied, for the same reason: both are mechanically downstream of
the outcome the model predicts, not a predictor of it. Both are stored --
labelling and the evidence trail need them -- and both are unreadable from
feature code (constitution Principle I, FR-010).

``AccountFeatureInput`` makes the account-column half of that denial a type
guarantee rather than a convention: it is built with a whitelist constructor
that names only the safe fields, so ``lifecycle_state``, ``churned_at`` and
``churn_kind`` have no attribute path into feature code, even if a careless
caller handed it a raw row containing them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

DENIED_EVENT_TYPES: frozenset[str] = frozenset({"crm.closed_lost", "billing.subscription_deleted"})

DENIED_ACCOUNT_FIELDS: frozenset[str] = frozenset({"lifecycle_state", "churned_at", "churn_kind"})

_SAFE_ACCOUNT_FIELDS = (
    "segment", "industry", "region", "seats", "acv_cents", "mrr_cents",
    "renewal_date", "signup_date",
)


@dataclass(frozen=True, slots=True)
class AccountFeatureInput:
    """Only the account facts feature code is allowed to see.

    Deliberately thin: everything that varies over time (segment, seats,
    acv_cents, renewal_date) is point-in-time sensitive and compute.py derives
    it from the event stream as-of, never from this object -- see
    ``ingest/dimension.py``'s warning against reading current state for a
    point-in-time feature. ``signup_date`` is the one genuinely time-invariant
    fact and is the only commercial attribute this object actually carries from
    the account dimension.
    """

    segment: str | None
    industry: str | None
    region: str | None
    seats: int | None
    acv_cents: int | None
    mrr_cents: int | None
    renewal_date: date | None
    signup_date: date

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> AccountFeatureInput:
        return cls(**{k: row.get(k) for k in _SAFE_ACCOUNT_FIELDS})


def filter_denied_events(events: list) -> list:
    """Drop anything mechanically downstream of the outcome. Called by
    compute.py itself as defense in depth, not trusted to the caller."""
    return [e for e in events if e.event_type not in DENIED_EVENT_TYPES]
