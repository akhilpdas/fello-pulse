"""The weekly training panel (clarifications B-4).

One row per (account, Monday): features computed as-of that Monday by the same
``features/compute.py`` the serving path calls, label drawn from the following
``horizon_days`` by ``ml/labels.py``. A Monday is only included if the dataset
actually extends far enough past it to observe the full horizon -- including a
Monday that can't yet see its outcome would silently relabel a right-censored
row as a negative.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from pulse.features.compute import EventRecord, compute
from pulse.features.denylist import AccountFeatureInput
from pulse.ml.labels import label_for_window, outcome_events


def monday_on_or_after(d: date) -> date:
    return d + timedelta(days=(7 - d.weekday()) % 7) if d.weekday() != 0 else d


@dataclass(frozen=True, slots=True)
class PanelRow:
    account_id: object
    as_of: datetime
    feature_values: dict
    label: bool


def build_account_panel(
    *,
    account_id,
    connected_sources: frozenset[str],
    account_input: AccountFeatureInput,
    events: list[EventRecord],
    contraction_threshold: float,
    horizon_days: int,
    dataset_end: datetime,
    identity_unresolved: bool = False,
) -> list[PanelRow]:
    if not events:
        return []

    first_day = min(e.occurred_at for e in events).date()
    # The +1 day margin covers the fact that as_of is constructed at a fixed
    # hour (09:00 UTC) on a Monday: without it, the final Monday of a
    # horizon_days=0 dataset could nominally be "after" a midnight dataset_end
    # even though it falls on the same calendar day.
    last_monday = dataset_end.date() - timedelta(days=horizon_days + 1)
    outcomes = outcome_events(events, contraction_threshold)

    rows: list[PanelRow] = []
    d = monday_on_or_after(first_day)
    while d <= last_monday:
        as_of = datetime(d.year, d.month, d.day, 9, 0, tzinfo=UTC)
        result = compute(
            connected_sources=connected_sources, account=account_input,
            events=events, as_of=as_of, identity_unresolved=identity_unresolved,
        )
        label = label_for_window(outcomes, as_of, horizon_days)
        rows.append(PanelRow(account_id, as_of, result.values, label))
        d += timedelta(days=7)
    return rows
