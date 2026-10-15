"""contracts/features.md: a weekend-heavy seasonal series must not produce a
spurious week-over-week decline, regardless of which weekday `as_of` lands on.
This is the direct test of whether windows.py's whole-multiple-of-7-days fix
actually defends the feature layer: any 28-day window built that way contains
exactly 4 of each weekday, so a constant weekly pattern gives a WoW ratio of
1.0 no matter where as_of falls."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from pulse.features.compute import EventRecord, compute
from pulse.features.denylist import AccountFeatureInput

# Fixed weekday pattern: weekdays busy, weekends quiet. Identical every week --
# no real trend, pure seasonality.
_DAILY_PATTERN = {0: 12, 1: 12, 2: 12, 3: 12, 4: 10, 5: 2, 6: 1}  # Mon..Sun


def _account() -> AccountFeatureInput:
    return AccountFeatureInput.from_row({"signup_date": date(2024, 1, 1)})


def _weekly_rollups(start: date, weeks: int) -> list[EventRecord]:
    events = []
    d = start
    for w in range(weeks):
        week_days = [d + timedelta(days=i) for i in range(7)]
        daily = [
            {"date": day.isoformat(), "active_users": _DAILY_PATTERN[day.weekday()], "sessions": 1}
            for day in week_days
        ]
        occurred = datetime(week_days[-1].year, week_days[-1].month, week_days[-1].day, 12, tzinfo=UTC)
        events.append(EventRecord(
            w + 1, "product", "product.usage_rollup",
            occurred_at=occurred, received_at=occurred,
            payload={"period_start": d.isoformat(), "period_days": 7,
                     "active_users": sum(1 for _ in week_days), "sessions": 7,
                     "feature_keys": ["reports"], "seats_snapshot": 20,
                     "daily": daily, "user_refs": ["u1"]},
        ))
        d += timedelta(days=7)
    return events


def test_constant_weekly_seasonality_never_reports_a_spurious_wow_decline():
    start = date(2026, 1, 5)  # a Monday
    events = _weekly_rollups(start, weeks=10)
    connected = frozenset({"product"})

    # Walk as_of across every weekday of the final week and confirm none of
    # them produce a false decline.
    last_week_monday = start + timedelta(days=7 * 9)
    for offset in range(7):
        as_of = datetime(
            last_week_monday.year, last_week_monday.month, last_week_monday.day,
            9, 0, tzinfo=UTC,
        ) + timedelta(days=offset + 7)  # into week 11, no data added there
        result = compute(connected_sources=connected, account=_account(), events=events, as_of=as_of)
        ratio = result.values["usage_active_users_wow"]
        assert ratio is not None
        assert abs(ratio - 1.0) < 1e-9, f"as_of={as_of} weekday={as_of.weekday()} ratio={ratio}"
