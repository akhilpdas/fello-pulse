"""The audit trail (FR-012): who or what did what, per tenant. Append-only for the application role.

Never put a secret in ``detail`` -- passwords, tokens and keys are not recorded, only the facts
(who, which event, what they were doing).
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from pulse.db.session import tenant_session


def record(
    session: Session, event: str, *, actor_user_id: uuid.UUID | None = None, actor_kind: str = "user",
    subject: str | None = None, detail: dict | None = None,
) -> None:
    """Write an event inside the caller's tenant-scoped transaction (so it is atomic with the change)."""
    session.execute(
        text(
            "INSERT INTO audit_event (id, tenant_id, actor_user_id, actor_kind, event, subject, detail)"
            " VALUES (:i, current_setting('pulse.tenant_id')::uuid, :u, :k, :e, :s, CAST(:d AS jsonb))"
        ),
        {"i": uuid.uuid4(), "u": actor_user_id, "k": actor_kind, "e": event, "s": subject,
         "d": json.dumps(detail or {})},
    )


def record_separately(tenant_id: uuid.UUID, event: str, **kwargs) -> None:
    """Write an event in its own transaction -- for refusals and failures, where the request's own
    transaction is about to be abandoned."""
    with tenant_session(tenant_id) as s:
        record(s, event, **kwargs)
