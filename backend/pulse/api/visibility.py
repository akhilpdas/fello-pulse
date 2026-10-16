"""Which accounts may this caller see? (FR-005, 001/FR-042)

An operator sees the tenant. A CSM sees only the accounts they own; an account with no owner is
operator-only. One helper, used by every account-level query, so no route can forget it. Row-level
security still isolates tenants underneath this -- this narrows *within* a tenant.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from pulse.auth.principal import Principal


def visible_clause(principal: Principal, alias: str = "a") -> tuple[str, dict]:
    """A SQL predicate over ``<alias>.owner_user_id`` plus its bind parameters."""
    if principal.is_operator:
        return "TRUE", {}
    return f"{alias}.owner_user_id = :_viewer", {"_viewer": principal.user_id}


def require_visible_account(session: Session, principal: Principal, account_id: uuid.UUID) -> None:
    """404 -- not 403 -- unless the caller may see the account: existence is not disclosed."""
    clause, params = visible_clause(principal)
    found = session.execute(
        text(f"SELECT 1 FROM account a WHERE a.id = :acct AND {clause}"), {"acct": account_id, **params}
    ).scalar()
    if found is None:
        raise HTTPException(status_code=404, detail="account not found")
