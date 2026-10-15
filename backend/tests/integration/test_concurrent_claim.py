"""agent/lease.py (T069): two workers racing to claim the same unit, exactly
one wins. ``FOR UPDATE SKIP LOCKED`` is the mechanism; this proves it under
genuine concurrent transactions, not just by reading the SQL.

Same TDD-provenance note as test_lease_recovery.py: written as a regression
test against the already-implemented lease primitive, not test-first.
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from sqlalchemy import text

from pulse.agent import lease
from pulse.db.session import owner_session

KIND = "test_concurrent_claim"


def test_exactly_one_of_many_concurrent_claims_succeeds():
    key = f"acct-{uuid.uuid4().hex[:8]}"
    now = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)

    def attempt(worker_id: str) -> bool:
        with owner_session() as s:
            return lease.claim(s, kind=KIND, key=key, owner=worker_id, lease_seconds=300, now=now)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, [f"worker-{i}" for i in range(8)]))

    with owner_session() as s:
        s.execute(text("DELETE FROM work_lease WHERE kind = :k AND key = :key"), {"k": KIND, "key": key})

    assert sum(results) == 1
