"""Weekday-aligned window helpers.

Every week-over-week comparison compares whole aligned weeks, never a trailing
window offset by an arbitrary calendar boundary (contracts/features.md). The
generator injects weekday and holiday seasonality strong enough that a naive
"current calendar week vs prior calendar week" comparison false-positives a
decline every time ``as_of`` falls early in a week, because the current window
is partial while the prior one is whole.

The fix used throughout this module: anchor every window to ``as_of`` itself
and require whole multiples of 7 days. Two windows built this way always carry
an identical weekday composition, so a raw-count comparison between them
cannot be fooled by which day of the week ``as_of`` happens to be.
"""

from __future__ import annotations

from datetime import datetime, timedelta


def aligned_window(as_of: datetime, days: int) -> tuple[datetime, datetime]:
    """``[as_of - days, as_of)``, anchored to as_of. ``days`` must be a whole
    multiple of 7 -- a window that isn't cannot be compared week-over-week
    without reintroducing the exact bias this module exists to avoid."""
    if days % 7 != 0:
        raise ValueError(f"window must be a whole multiple of 7 days, got {days}")
    return as_of - timedelta(days=days), as_of


def week_over_week(
    as_of: datetime, weeks: int
) -> tuple[tuple[datetime, datetime], tuple[datetime, datetime]]:
    """Two adjacent, equal-length, non-overlapping whole-week blocks ending at
    ``as_of``: the current block and the one immediately before it."""
    days = weeks * 7
    cur_start, cur_end = aligned_window(as_of, days)
    prior_start, prior_end = aligned_window(cur_start, days)
    return (cur_start, cur_end), (prior_start, prior_end)
