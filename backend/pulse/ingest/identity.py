"""Resolving five identifier schemes onto one internal account.

Salesforce mints ``001...``, Stripe mints ``cus_...``, Zendesk mints
``zdorg_...``. Nothing connects them except a mapping table, and in any real
estate that table is incomplete. This module makes the incompleteness a visible,
queryable state rather than an exception or, worse, a phantom account.

The rule that matters: **an unresolved reference never creates an account.**
Inventing one from an unmapped identifier produces a duplicate of a customer
that already exists, splits their history in two, and makes both halves look
quieter than the whole. A visible gap is recoverable; a phantom account corrupts
the data and the scores derived from it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass
class Resolver:
    """In-memory view of one tenant's identity map for one source.

    Loaded once per ingestion pass rather than queried per record: at 350,000
    records a per-row lookup is the difference between a minute and an hour, and
    the map is small enough to hold.
    """

    tenant_id: uuid.UUID
    source: str
    _known: dict[str, uuid.UUID | None] = field(default_factory=dict)
    _new_unresolved: set[str] = field(default_factory=set)

    @classmethod
    def load(cls, session: Session, tenant_id: uuid.UUID, source: str) -> Resolver:
        rows = session.execute(
            text(
                "SELECT source_account_ref, account_id FROM identity_link"
                " WHERE source = :s"
            ),
            {"s": source},
        ).all()
        return cls(tenant_id, source, {r[0]: r[1] for r in rows})

    def resolve(self, source_account_ref: str) -> uuid.UUID | None:
        if source_account_ref in self._known:
            return self._known[source_account_ref]
        # Unknown reference: record it so it can be surfaced to an operator,
        # and return None. Do not create an account.
        self._new_unresolved.add(source_account_ref)
        self._known[source_account_ref] = None
        return None

    @property
    def unresolved_refs(self) -> set[str]:
        return self._new_unresolved

    def persist_unresolved(self, session: Session) -> int:
        """Record newly-seen unmapped references as an explicit state."""
        if not self._new_unresolved:
            return 0
        session.execute(
            text(
                "INSERT INTO identity_link"
                " (id, tenant_id, source, source_account_ref, account_id, method,"
                "  confidence, first_seen_at)"
                " SELECT gen_random_uuid(), :t, :s, ref, NULL, 'unresolved', 0.0, now()"
                " FROM unnest(CAST(:refs AS text[])) AS ref"
                " ON CONFLICT (tenant_id, source, source_account_ref) DO NOTHING"
            ),
            {"t": self.tenant_id, "s": self.source, "refs": list(self._new_unresolved)},
        )
        n = len(self._new_unresolved)
        self._new_unresolved = set()
        return n


def unresolved_summary(session: Session) -> list[dict]:
    """What an operator needs to see: which references are going nowhere.

    Surfaced in the coverage report rather than buried in a log, because an
    unmapped billing identity is the reason an otherwise-fine account cannot be
    scored, and the remedy is an operator action, not an engineering one.
    """
    rows = session.execute(
        text(
            "SELECT source, count(*) AS n FROM identity_link"
            " WHERE account_id IS NULL GROUP BY source ORDER BY n DESC"
        )
    ).all()
    return [{"source": r.source, "unresolved": r.n} for r in rows]
