"""POST /accounts/{id}/feedback (001/FR-047): a CSM's judgement on a flagged account, retained
as a label. A dismissal that only removes a row from a list throws away the most valuable label
the system is handed -- a domain expert saying "this one is wrong".
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.orm import Session

from pulse.api.deps import get_principal, get_session
from pulse.api.visibility import require_visible_account
from pulse.auth.principal import Principal

router = APIRouter()


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["false_positive", "true_positive", "not_actionable"]
    note: str | None = None


@router.post("/accounts/{account_id}/feedback", status_code=201)
def post_feedback(
    account_id: uuid.UUID, req: FeedbackRequest,
    session: Session = Depends(get_session), principal: Principal = Depends(get_principal),
):
    user_id = principal.user_id
    require_visible_account(session, principal, account_id)
    score_id = session.execute(
        text("SELECT id FROM score WHERE account_id = :a ORDER BY as_of DESC LIMIT 1"), {"a": account_id}
    ).scalar()
    feedback_id = uuid.uuid4()
    session.execute(
        text(
            "INSERT INTO feedback (id, tenant_id, account_id, score_id, kind, note, created_by_user_id)"
            " VALUES (:i, current_setting('pulse.tenant_id')::uuid, :a, :s, :k, :n, :u)"
        ),
        {"i": feedback_id, "a": account_id, "s": score_id, "k": req.kind, "n": req.note, "u": user_id},
    )
    return {"id": str(feedback_id), "account_id": str(account_id), "score_id": str(score_id) if score_id else None,
            "kind": req.kind}
