"""Opaque, revocable, expiring sessions (FR-008).

The token a client holds is ``<tenant_id>.<secret>``. Only ``sha256(secret)`` is stored. The tenant
prefix is *untrusted*: it is used solely to choose which tenant claim the lookup runs under. Row-level
security then hides every row that is not that tenant's, so a forged prefix finds nothing -- no
``SECURITY DEFINER`` function and no cross-tenant read on the request path (constitution IV).
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta

from sqlalchemy import text

from pulse.auth.principal import Principal
from pulse.db.session import tenant_session


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _parse(token: str) -> tuple[uuid.UUID, str] | None:
    prefix, dot, secret = token.partition(".")
    if not dot or not secret or "." in secret:
        return None
    try:
        return uuid.UUID(prefix), secret
    except ValueError:
        return None


def create_session(
    tenant_id: uuid.UUID, user_id: uuid.UUID, *, now: datetime, ttl: timedelta, user_agent: str | None = None,
) -> str:
    secret = secrets.token_urlsafe(32)
    with tenant_session(tenant_id) as s:
        s.execute(
            text(
                "INSERT INTO app_session (id, tenant_id, user_id, token_hash, created_at, expires_at, user_agent)"
                " VALUES (:i, :t, :u, :h, :now, :exp, :ua)"
            ),
            {"i": uuid.uuid4(), "t": tenant_id, "u": user_id, "h": _hash(secret), "now": now,
             "exp": now + ttl, "ua": user_agent},
        )
    return f"{tenant_id}.{secret}"


def resolve_session(token: str, *, now: datetime) -> Principal | None:
    parsed = _parse(token)
    if parsed is None:
        return None
    tenant_id, secret = parsed
    with tenant_session(tenant_id) as s:
        row = s.execute(
            text(
                "SELECT se.id, se.user_id, u.role FROM app_session se JOIN app_user u ON u.id = se.user_id"
                " WHERE se.token_hash = :h AND se.revoked_at IS NULL AND se.expires_at > :now"
                " AND u.disabled_at IS NULL"
            ),
            {"h": _hash(secret), "now": now},
        ).one_or_none()
        if row is None:
            return None
        s.execute(text("UPDATE app_session SET last_seen_at = :now WHERE id = :i"), {"now": now, "i": row[0]})
        return Principal(tenant_id=tenant_id, user_id=row[1], role=row[2])


def revoke_session(token: str) -> None:
    parsed = _parse(token)
    if parsed is None:
        return
    tenant_id, secret = parsed
    with tenant_session(tenant_id) as s:
        s.execute(
            text("UPDATE app_session SET revoked_at = now() WHERE token_hash = :h AND revoked_at IS NULL"),
            {"h": _hash(secret)},
        )
