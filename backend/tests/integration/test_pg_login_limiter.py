"""Sign-in rate limiting that holds across API instances (research R-4 gap, closed).

The in-process limiter gives an attacker N times the allowance behind N instances. This one keeps its state in
Postgres, so two limiter objects -- standing in for two processes -- see one shared count. The table holds only a
*hash* of (address, workspace, email): no email address is stored, and it carries no tenant data, which is why it is
a declared global table and not a tenant-scoped one (nobody has a tenant before they have signed in).

Names the production change that makes it fail: ``pulse.auth.limiter.PgLoginLimiter`` and migration 0006.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from pulse.auth.limiter import PgLoginLimiter
from pulse.db.session import owner_session

T0 = datetime(2040, 1, 1, tzinfo=UTC)


def _key():
    return (f"ip-{uuid.uuid4().hex[:6]}", "northwind", f"ana-{uuid.uuid4().hex[:6]}@example.test")


def test_two_instances_share_one_count():
    a, b = PgLoginLimiter(3, 300), PgLoginLimiter(3, 300)  # two "processes"
    key = _key()
    for i in range(3):
        (a if i % 2 else b).record_failure(key, now=T0 + timedelta(seconds=i))
    assert not a.allowed(key, now=T0 + timedelta(seconds=5))
    assert not b.allowed(key, now=T0 + timedelta(seconds=5))


def test_the_window_slides_success_clears_and_keys_are_independent():
    lim = PgLoginLimiter(2, 60)
    key, other = _key(), _key()
    lim.record_failure(key, now=T0)
    lim.record_failure(key, now=T0 + timedelta(seconds=1))
    assert not lim.allowed(key, now=T0 + timedelta(seconds=30))
    assert lim.allowed(key, now=T0 + timedelta(seconds=90))  # the window slid
    assert lim.allowed(other, now=T0 + timedelta(seconds=30))  # independent
    lim.record_failure(other, now=T0)
    lim.record_success(other)
    assert lim.allowed(other, now=T0 + timedelta(seconds=1))


def test_no_email_address_or_ip_is_stored_only_a_hash():
    key = _key()
    PgLoginLimiter(3, 300).record_failure(key, now=T0)
    with owner_session() as s:
        rows = s.execute(text("SELECT row_to_json(t)::text FROM login_attempt t")).scalars().all()
    blob = " ".join(rows)
    assert key[2] not in blob and key[0] not in blob


def test_old_attempts_are_purged_so_the_table_does_not_grow_forever():
    lim = PgLoginLimiter(5, 60)
    key = _key()
    lim.record_failure(key, now=T0)
    lim.purge(now=T0 + timedelta(hours=1))
    with owner_session() as s:
        assert s.execute(text("SELECT count(*) FROM login_attempt WHERE at = :t"), {"t": T0}).scalar() == 0
