"""Crash-safe claiming against ``work_lease`` (T066, T068, T069). A lease
with an expiry, not a bare in-progress flag, because the failure that
matters is a worker dying mid-unit -- a status column with no expiry leaves
that unit never retried and never reported, exactly the silent gap the
original brief complained about.

``work_lease`` is schema-global (never tenant-scoped) and never serves a
request, so it is managed through ``owner_session`` -- the same invariant
``owner_session`` already carries ("migrations and test fixtures", extended
here to "and worker infrastructure that likewise never serves a request").
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session


def _ensure_row(session: Session, *, kind: str, key: str) -> None:
    session.execute(
        text(
            "INSERT INTO work_lease (id, kind, key, state, attempts, updated_at)"
            " VALUES (:i, :k, :key, 'pending', 0, now())"
            " ON CONFLICT (kind, key) DO NOTHING"
        ),
        {"i": uuid.uuid4(), "k": kind, "key": key},
    )


def claim(session: Session, *, kind: str, key: str, owner: str, lease_seconds: int, now: datetime) -> bool:
    """True if this call claimed the lease. ``FOR UPDATE SKIP LOCKED`` means a
    row currently locked by another transaction (an active claim) is simply
    skipped rather than blocked on -- the second worker loses the race
    instead of waiting for it, which is what makes two concurrent claims on
    the same key resolve to exactly one winner (T069)."""
    _ensure_row(session, kind=kind, key=key)
    row = session.execute(
        text(
            "SELECT id FROM work_lease WHERE kind = :k AND key = :key"
            " AND (state = 'pending' OR leased_until < :now)"
            " FOR UPDATE SKIP LOCKED"
        ),
        {"k": kind, "key": key, "now": now},
    ).mappings().first()
    if row is None:
        return False
    session.execute(
        text(
            "UPDATE work_lease SET owner = :o, leased_until = :lu, state = 'in_progress',"
            " attempts = attempts + 1, last_error = NULL, updated_at = now() WHERE id = :i"
        ),
        {"o": owner, "lu": now + timedelta(seconds=lease_seconds), "i": row["id"]},
    )
    return True


def release(session: Session, *, kind: str, key: str, error: str | None = None) -> None:
    """Hand the lease back immediately on completion (success or failure) so
    the next due cycle isn't blocked on the lease's own expiry -- the worker
    tick loop's ``due_tenants`` check is what actually paces re-runs."""
    session.execute(
        text(
            "UPDATE work_lease SET state = 'pending', leased_until = NULL,"
            " last_error = :err, updated_at = now() WHERE kind = :k AND key = :key"
        ),
        {"err": error, "k": kind, "key": key},
    )
