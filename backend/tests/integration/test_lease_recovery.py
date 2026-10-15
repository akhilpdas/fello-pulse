"""agent/lease.py (T068): killed mid-unit work is reclaimed after expiry and
not double-processed -- a claim attempted before expiry while the original
holder is still "alive" (lease unexpired) must fail, and only after expiry
does a new claim succeed.

Note on TDD provenance: ``lease.py`` was written alongside ``cycle.py`` and
``worker.py`` as one coupled slice, driven to green by
``test_worker_unattended.py`` (T067) rather than by a test of this specific
expiry/reclaim behavior written first. This test was added after the fact to
pin down that behavior precisely -- it is a real regression test, but it is
not a test-first proof the way T061-T064's unit tests were. Flagged
explicitly rather than silently claimed as red-green.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from pulse.agent import lease
from pulse.db.session import owner_session

KIND = "test_lease_recovery"


def test_an_unexpired_lease_cannot_be_reclaimed_then_expiry_allows_reclaim():
    key = f"acct-{uuid.uuid4().hex[:8]}"
    t0 = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)

    with owner_session() as s:
        claimed_a = lease.claim(s, kind=KIND, key=key, owner="worker-a", lease_seconds=60, now=t0)
    assert claimed_a is True

    # worker-a "crashes" -- never releases. A second claim before expiry must fail.
    with owner_session() as s:
        claimed_b_too_soon = lease.claim(
            s, kind=KIND, key=key, owner="worker-b", lease_seconds=60, now=t0 + timedelta(seconds=30),
        )
    assert claimed_b_too_soon is False

    # Past expiry, the lease is reclaimable exactly once.
    with owner_session() as s:
        claimed_b = lease.claim(
            s, kind=KIND, key=key, owner="worker-b", lease_seconds=60, now=t0 + timedelta(seconds=61),
        )
    assert claimed_b is True

    with owner_session() as s:
        row = s.execute(
            text("SELECT owner, state FROM work_lease WHERE kind = :k AND key = :key"),
            {"k": KIND, "key": key},
        ).mappings().one()
        s.execute(
            text("DELETE FROM work_lease WHERE kind = :k AND key = :key"),
            {"k": KIND, "key": key},
        )
    assert row["owner"] == "worker-b"
    assert row["state"] == "in_progress"
