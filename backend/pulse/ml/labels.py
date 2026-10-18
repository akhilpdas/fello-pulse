"""Churn-or-material-contraction labelling (clarifications A1).

The one module in the system allowed to look forward from ``as_of`` -- it
produces the training target, never a feature. ``panel.py`` is the only
caller; ``features/compute.py`` must never import this module.

A Stripe cancellation is always an outcome. An MRR contraction counts only if
it is sustained past one billing cycle (~30 days): a billing blip that
recovers within the cycle is noise, not a decision. Salesforce corroboration
is recorded when present but is not required -- billing alone is the adopted,
authoritative signal (clarifications A1).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from pulse.features.compute import EventRecord

ONE_BILLING_CYCLE_DAYS = 35


@dataclass(frozen=True, slots=True)
class OutcomeEvent:
    occurred_at: datetime
    kind: str  # "churn" | "contraction"
    corroborated: bool


def _sf_corroborates(events: list[EventRecord], at: datetime, window_days: int = 45) -> bool:
    return any(
        e.event_type == "crm.closed_lost" and abs((e.occurred_at - at).days) <= window_days
        for e in events
    )


def outcome_events(events: list[EventRecord], contraction_threshold: float) -> list[OutcomeEvent]:
    """Every qualifying loss event across an account's full history, drawn
    from billing (and corroborated by CRM where available). Order of input
    does not matter; output is sorted by occurrence."""
    out: list[OutcomeEvent] = []

    for e in events:
        if e.event_type == "billing.subscription_deleted":
            out.append(OutcomeEvent(e.occurred_at, "churn", _sf_corroborates(events, e.occurred_at)))

    subs = sorted(
        (e for e in events if e.event_type == "billing.subscription_updated"),
        key=lambda e: e.occurred_at,
    )
    for i, e in enumerate(subs):
        prev = e.payload.get("previous_mrr_cents")
        cur = e.payload.get("mrr_cents")
        if not prev or cur is None or cur > prev * (1 - contraction_threshold):
            continue
        cycle_end = e.occurred_at + timedelta(days=ONE_BILLING_CYCLE_DAYS)
        reverted = any(
            subs[j].occurred_at <= cycle_end and subs[j].payload.get("mrr_cents", 0) > cur
            for j in range(i + 1, len(subs))
        )
        if reverted:
            continue
        out.append(OutcomeEvent(e.occurred_at, "contraction", _sf_corroborates(events, e.occurred_at)))

    return sorted(out, key=lambda o: o.occurred_at)


def next_outcome_at(outcomes: list[OutcomeEvent], as_of: datetime, horizon_days: int) -> datetime | None:
    """When the first qualifying loss event in (as_of, as_of + horizon] happened, or None. The date behind a
    positive label -- lead time (how early a flag came) cannot be measured without it."""
    end = as_of + timedelta(days=horizon_days)
    return min((o.occurred_at for o in outcomes if as_of < o.occurred_at <= end), default=None)


def label_for_window(outcomes: list[OutcomeEvent], as_of: datetime, horizon_days: int) -> bool:
    """True iff a qualifying loss event falls in (as_of, as_of + horizon]."""
    return next_outcome_at(outcomes, as_of, horizon_days) is not None
