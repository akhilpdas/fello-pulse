"""T220 (FR-007): repeated failed sign-ins are refused for a while. The limiter is keyed only by
(address, workspace, email) and knows nothing about whether the account exists, so a refusal reveals nothing.

Names the production change that makes it fail: ``pulse.auth.limiter.LoginLimiter``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pulse.auth.limiter import LoginLimiter

T0 = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
KEY = ("203.0.113.9", "northwind", "ana@example.test")


def _fail(limiter, key, n, at):
    for i in range(n):
        limiter.record_failure(key, now=at + timedelta(seconds=i))


def test_allowed_until_the_limit_then_refused():
    lim = LoginLimiter(max_failures=3, window_seconds=300)
    assert lim.allowed(KEY, now=T0)
    _fail(lim, KEY, 2, T0)
    assert lim.allowed(KEY, now=T0 + timedelta(seconds=5))
    _fail(lim, KEY, 1, T0 + timedelta(seconds=3))
    assert not lim.allowed(KEY, now=T0 + timedelta(seconds=10))


def test_the_window_slides_so_old_failures_stop_counting():
    lim = LoginLimiter(max_failures=3, window_seconds=300)
    _fail(lim, KEY, 3, T0)
    assert not lim.allowed(KEY, now=T0 + timedelta(seconds=299))
    assert lim.allowed(KEY, now=T0 + timedelta(seconds=305))


def test_success_clears_the_count():
    lim = LoginLimiter(max_failures=3, window_seconds=300)
    _fail(lim, KEY, 2, T0)
    lim.record_success(KEY)
    _fail(lim, KEY, 2, T0 + timedelta(seconds=10))
    assert lim.allowed(KEY, now=T0 + timedelta(seconds=20))


def test_keys_are_independent():
    lim = LoginLimiter(max_failures=2, window_seconds=300)
    _fail(lim, KEY, 2, T0)
    other = ("198.51.100.4", "northwind", "ana@example.test")
    assert lim.allowed(other, now=T0 + timedelta(seconds=5))


def test_memory_is_bounded_old_keys_are_forgotten():
    lim = LoginLimiter(max_failures=3, window_seconds=60, max_keys=100)
    for i in range(500):
        lim.record_failure(("ip", "w", f"user{i}@example.test"), now=T0)
    assert lim.size() <= 100
