"""features/windows.py: weekday-aligned window helpers.

The bug this defends against: a naive "current week" vs "prior week"
comparison where the current window is partial (as_of falls mid-week against a
calendar Monday boundary) looks like a decline every time it's computed near
the start of a week. The fix is windows that are whole multiples of 7 days
anchored to as_of, never calendar boundaries -- so both sides of any
week-over-week comparison carry an identical weekday composition.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pulse.features.windows import aligned_window, week_over_week


def test_aligned_window_rejects_non_week_multiples():
    as_of = datetime(2026, 3, 11, 9, 0, tzinfo=UTC)
    with pytest.raises(ValueError):
        aligned_window(as_of, 10)


def test_aligned_window_is_a_whole_multiple_of_seven_days_ending_at_as_of():
    as_of = datetime(2026, 3, 11, 9, 0, tzinfo=UTC)  # a Wednesday
    start, end = aligned_window(as_of, 28)
    assert end == as_of
    assert (end - start) == timedelta(days=28)


def test_week_over_week_gives_two_adjacent_equal_length_non_overlapping_blocks():
    as_of = datetime(2026, 3, 11, 9, 0, tzinfo=UTC)
    (cur_start, cur_end), (prior_start, prior_end) = week_over_week(as_of, weeks=4)
    assert cur_end == as_of
    assert (cur_end - cur_start) == timedelta(weeks=4)
    assert prior_end == cur_start
    assert (prior_end - prior_start) == timedelta(weeks=4)


def test_week_over_week_identical_regardless_of_which_weekday_as_of_falls_on():
    """The whole point: alignment is to as_of, not to a calendar Monday, so the
    block length and adjacency hold no matter which weekday as_of is."""
    for offset in range(7):
        as_of = datetime(2026, 3, 9, 9, 0, tzinfo=UTC) + timedelta(days=offset)
        (cur_start, cur_end), (prior_start, prior_end) = week_over_week(as_of, weeks=4)
        assert (cur_end - cur_start) == (prior_end - prior_start) == timedelta(weeks=4)
        assert prior_end == cur_start
