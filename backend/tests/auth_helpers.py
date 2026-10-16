"""Real sessions for tests. Identity is never faked by a header any more (002 / FR-002): a test that
wants to be a user creates that user, signs a real session in the database, and sends it as a bearer token."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from pulse.auth.sessions import create_session
from pulse.db.session import owner_session


def make_user(tenant_id: uuid.UUID, role: str = "operator", *, user_id: uuid.UUID | None = None) -> uuid.UUID:
    user_id = user_id or uuid.uuid4()
    with owner_session() as s:
        s.execute(
            text("INSERT INTO app_user (id, tenant_id, email, name, role) VALUES (:i,:t,:e,'Test User',:r)"),
            {"i": user_id, "t": tenant_id, "e": f"u{uuid.uuid4().hex[:8]}@example.test", "r": role},
        )
    return user_id


def auth_headers(tenant_id: uuid.UUID, user_id: uuid.UUID | None = None, role: str = "operator") -> dict:
    """``Authorization: Bearer`` for a (new or given) user of the tenant. Operator by default so the
    tests written before roles existed still see the whole tenant."""
    if user_id is None:
        user_id = make_user(tenant_id, role)
    else:
        with owner_session() as s:
            exists = s.execute(text("SELECT 1 FROM app_user WHERE id = :i"), {"i": user_id}).scalar()
        if not exists:
            make_user(tenant_id, role, user_id=user_id)
    token = create_session(tenant_id, user_id, now=datetime.now(UTC), ttl=timedelta(hours=1))
    return {"Authorization": f"Bearer {token}"}
