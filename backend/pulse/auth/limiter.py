"""Sign-in rate limiting (FR-007), in process.

Keyed by (address, workspace, email) and blind to whether the account exists, so a refusal reveals
nothing. **Known limit, stated:** the state is per process -- with N API instances an attacker gets N
times the allowance. A shared store is the fix and is not built (specs/002 research R-4).
"""

from __future__ import annotations

from collections import OrderedDict, deque
from datetime import datetime, timedelta
from threading import Lock

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
