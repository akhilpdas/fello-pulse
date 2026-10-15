"""The thin, I/O-only adapter between the database and the pure feature engine.

Loads an account's full event history once; both the panel builder (ml/panel.py)
and the scoring service (scoring/service.py) call this and then hand the result
to the same ``features/compute.py`` function. One code path for both is the
only real defense against train/serve skew.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from pulse.features.compute import EventRecord
from pulse.features.denylist import AccountFeatureInput


def load_events(session: Session, account_id: uuid.UUID) -> list[EventRecord]:
    rows = session.execute(
        text(
            "SELECT id, source, event_type, occurred_at, received_at, payload"
            " FROM source_event WHERE account_id = :a ORDER BY received_at, id"
        ),
        {"a": account_id},
    ).mappings().all()
    return [
        EventRecord(r["id"], r["source"], r["event_type"], r["occurred_at"], r["received_at"], r["payload"])
        for r in rows
    ]


def load_account_feature_input(session: Session, account_id: uuid.UUID) -> AccountFeatureInput:
    row = session.execute(
        text("SELECT signup_date FROM account WHERE id = :a"), {"a": account_id}
    ).mappings().one()
    return AccountFeatureInput.from_row(dict(row))


def identity_unresolved_for_account(session: Session, account_id: uuid.UUID) -> bool:
    """True if nothing from any source has ever resolved to this account --
    see clarifications.md for why this is the chosen reading of 'unresolved
    identity' at account granularity."""
    n = session.execute(
        text("SELECT count(*) FROM identity_link WHERE account_id = :a"), {"a": account_id}
    ).scalar()
    return n == 0
