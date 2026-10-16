"""Sign-in rate limiting (FR-007), in process.

Keyed by (address, workspace, email) and blind to whether the account exists, so a refusal reveals
nothing. This in-memory version is per process; the API uses ``PgLoginLimiter`` (below), which shares state
across instances.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict, deque
from datetime import datetime, timedelta
from threading import Lock

from sqlalchemy import text

from pulse.db.session import public_session

Key = tuple[str, str, str]


class LoginLimiter:
    def __init__(self, max_failures: int, window_seconds: int, max_keys: int = 10_000) -> None:
        self._max = max_failures
        self._window = timedelta(seconds=window_seconds)
        self._max_keys = max_keys
        self._failures: OrderedDict[Key, deque[datetime]] = OrderedDict()
        self._lock = Lock()

    def _recent(self, key: Key, now: datetime) -> deque[datetime]:
        dq = self._failures.get(key)
        if dq is None:
            return deque()
        while dq and now - dq[0] >= self._window:
            dq.popleft()
        return dq

    def allowed(self, key: Key, *, now: datetime) -> bool:
        with self._lock:
            return len(self._recent(key, now)) < self._max

    def record_failure(self, key: Key, *, now: datetime) -> None:
        with self._lock:
            dq = self._recent(key, now)
            dq.append(now)
            self._failures[key] = dq
            self._failures.move_to_end(key)
            while len(self._failures) > self._max_keys:
                self._failures.popitem(last=False)

    def record_success(self, key: Key) -> None:
        with self._lock:
            self._failures.pop(key, None)

    def size(self) -> int:
        with self._lock:
            return len(self._failures)


class PgLoginLimiter:
    """The same limiter with its state in Postgres, so the allowance holds across API instances (closes the
    per-process limit stated in research R-4). Only a hash of the key is stored; failures older than the window are
    deleted as the key is touched, and ``purge`` sweeps the rest."""

    def __init__(self, max_failures: int, window_seconds: int, max_per_source: int | None = None) -> None:
        self._max = max_failures
        self._max_per_source = max_per_source if max_per_source is not None else max_failures
        self._window = timedelta(seconds=window_seconds)

    def _limit_for(self, key: Key) -> int:
        """A key whose workspace and email are ``*`` counts a whole source address, across every account."""
        return self._max_per_source if key[1] == "*" and key[2] == "*" else self._max

    @staticmethod
    def _hash(key: Key) -> str:
        return hashlib.sha256("\x1f".join(key).encode()).hexdigest()

    def allowed(self, key: Key, *, now: datetime) -> bool:
        with public_session() as s:
            n = s.execute(
                text("SELECT count(*) FROM login_attempt WHERE key_hash = :h AND at > :since"),
                {"h": self._hash(key), "since": now - self._window},
            ).scalar()
        return n < self._limit_for(key)

    def record_failure(self, key: Key, *, now: datetime) -> None:
        h = self._hash(key)
        with public_session() as s:
            s.execute(text("DELETE FROM login_attempt WHERE key_hash = :h AND at <= :since"),
                      {"h": h, "since": now - self._window})
            s.execute(text("INSERT INTO login_attempt (key_hash, at) VALUES (:h, :at)"), {"h": h, "at": now})

    def record_success(self, key: Key) -> None:
        with public_session() as s:
            s.execute(text("DELETE FROM login_attempt WHERE key_hash = :h"), {"h": self._hash(key)})

    def purge(self, *, now: datetime) -> int:
        with public_session() as s:
            return s.execute(text("DELETE FROM login_attempt WHERE at <= :since"),
                             {"since": now - self._window}).rowcount
