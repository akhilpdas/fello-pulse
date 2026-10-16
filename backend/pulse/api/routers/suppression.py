"""POST/DELETE /accounts/{id}/suppress (001/FR-048): hide an account from the *queue* for a
stated reason until an expiry. Never from scoring -- an account deliberately being allowed to
churn is a legitimate business state, and deleting its data to express that would destroy the record.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from pulse.api.deps import get_principal, get_session
from pulse.api.visibility import require_visible_account
from pulse.auth.principal import Principal

router = APIRouter()


class SuppressRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str
    expires_at: datetime

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("a reason is required")
        return v.strip()

    @field_validator("expires_at")
    @classmethod
    def _expiry_in_future(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("expires_at must carry a timezone")
        if v <= datetime.now(UTC):
            raise ValueError("expires_at must be in the future")
        return v


@router.post("/accounts/{account_id}/suppress", status_code=201)
def suppress_account(
    account_id: uuid.UUID, req: SuppressRequest,
    session: Session = Depends(get_session), principal: Principal = Depends(get_principal),
):
    user_id = principal.user_id
    require_visible_account(session, principal, account_id)
    suppression_id = uuid.uuid4()
    session.execute(
        text(
            "INSERT INTO suppression (id, tenant_id, account_id, reason, created_by_user_id, expires_at)"
            " VALUES (:i, current_setting('pulse.tenant_id')::uuid, :a, :r, :u, :e)"
        ),
        {"i": suppression_id, "a": account_id, "r": req.reason, "u": user_id, "e": req.expires_at},
    )
    return {"id": str(suppression_id), "account_id": str(account_id), "expires_at": req.expires_at.isoformat()}


@router.delete("/accounts/{account_id}/suppress")
def lift_suppression(
    account_id: uuid.UUID, session: Session = Depends(get_session),
    principal: Principal = Depends(get_principal),
):
    """Ends every active suppression now. The rows are kept (expiry set to now), not deleted."""
    require_visible_account(session, principal, account_id)
    result = session.execute(
        text(
            "UPDATE suppression SET expires_at = now() - interval '1 second'"
            " WHERE account_id = :a AND (expires_at IS NULL OR expires_at > now())"
        ),
        {"a": account_id},
    )
    return {"lifted": result.rowcount}
