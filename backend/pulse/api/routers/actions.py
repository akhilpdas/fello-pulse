"""Draft review (T075, T076): list, approve, reject, edit -- actor and
timestamp recorded on every decision (constitution Principle III: an
autonomous system's output is reviewed by a visible, accountable human).

No action is ever sent without either this endpoint's explicit approval or
the autonomous cycle's own allowlist check (SC-011) -- this router never
bypasses the state machine the agent's cycle also writes into: ``drafted`` is
the only state either path starts from, and only a human approval (here) or
an allowlisted auto-send (agent/cycle.py) produces ``sent``.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from pulse.agent.delivery import RETRYABLE_STATES, apply_outcome, deliver
from pulse.agent.transport import Transport
from pulse.api.deps import get_principal, get_session, get_transport
from pulse.api.visibility import require_visible_account, visible_clause
from pulse.auth.principal import Principal

router = APIRouter()



# The actor is never in the request body: it is the authenticated user (FR-006). A client that still
# sends ``actor_user_id`` is ignored, not trusted.
class ApproveRequest(BaseModel):
    pass


class RejectRequest(BaseModel):
    reason: str | None = None


class EditRequest(BaseModel):
    subject: str | None = None
    body: str | None = None


def _row_to_dict(row) -> dict:
    return {
        "id": str(row["id"]), "account_id": str(row["account_id"]), "play_key": row["play_key"],
        "state": row["state"], "state_reason": row["state_reason"], "channel": row["channel"],
        "subject": row["subject"], "body": row["body"], "draft_source": row["draft_source"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "decided_at": row["decided_at"].isoformat() if row["decided_at"] else None,
        "decided_by_user_id": str(row["decided_by_user_id"]) if row["decided_by_user_id"] else None,
        "sent_at": row["sent_at"].isoformat() if row["sent_at"] else None,
        "attempts": row["attempts"], "grounding": row["grounding"],
        "redirected_to": row["redirected_to"], "provider_message_id": row["provider_message_id"],
        "delivery_error": row["delivery_error"], "draft_model": row["draft_model"],
        "draft_fallback_reason": row["draft_fallback_reason"], "original_subject": row["original_subject"],
        "original_body": row["original_body"],
    }


def _fetch(session: Session, action_id: uuid.UUID) -> dict:
    row = session.execute(
        text(
            "SELECT id, account_id, play_key, state, state_reason, channel, subject, body,"
            " draft_source, created_at, decided_at, decided_by_user_id, sent_at, attempts, grounding, redirected_to, provider_message_id, delivery_error, draft_model, draft_fallback_reason, original_subject, original_body"
            " FROM action WHERE id = :i"
        ),
        {"i": action_id},
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="action not found")
    return dict(row)


@router.get("/actions")
def list_actions(
    state: str | None = Query(default=None), session: Session = Depends(get_session),
    principal: Principal = Depends(get_principal),
):
    visible, params = visible_clause(principal)
    sql = "SELECT id, account_id, play_key, state, state_reason, channel, subject, body," \
          " draft_source, created_at, decided_at, decided_by_user_id, sent_at, attempts, grounding, redirected_to, provider_message_id, delivery_error, draft_model, draft_fallback_reason, original_subject, original_body FROM action" \
          f" WHERE account_id IN (SELECT a.id FROM account a WHERE {visible})"
    if state is not None:
        sql += " AND state = :state"
        params["state"] = state
    sql += " ORDER BY created_at DESC"
    rows = session.execute(text(sql), params).mappings().all()
    return {"rows": [_row_to_dict(r) for r in rows]}


@router.post("/actions/{action_id}/approve")
def approve_action(
    action_id: uuid.UUID, req: ApproveRequest,
    session: Session = Depends(get_session), transport: Transport = Depends(get_transport),
    principal: Principal = Depends(get_principal),
):
    """Approve a draft and deliver it -- once. The claim below is a single conditional UPDATE, so of two
    simultaneous approvals exactly one wins and sends; the other returns the winner's result. States in
    which the message may already have left (sent, send_unconfirmed) are never claimed again."""
    row = _fetch(session, action_id)
    require_visible_account(session, principal, row["account_id"])

    claimed = session.execute(
        text(
            "UPDATE action SET state = 'approved', decided_by_user_id = :u, decided_at = now()"
            " WHERE id = :i AND state = ANY(:ok) RETURNING id"
        ),
        {"u": principal.user_id, "i": action_id, "ok": list(RETRYABLE_STATES)},
    ).scalar()
    if claimed is None:
        current = _fetch(session, action_id)
        if current["state"] == "rejected":
            raise HTTPException(status_code=409, detail="action was rejected and cannot be approved")
        return _row_to_dict(current)  # idempotent: report what the first approval did

    outcome = deliver(
        session, action_id=action_id, account_id=row["account_id"], subject=row["subject"] or "",
        body=row["body"] or "", transport=transport,
    )
    apply_outcome(session, action_id, outcome)
    return _row_to_dict(_fetch(session, action_id))


@router.post("/actions/{action_id}/reject")
def reject_action(
    action_id: uuid.UUID, req: RejectRequest, session: Session = Depends(get_session),
    principal: Principal = Depends(get_principal),
):
    row = _fetch(session, action_id)
    require_visible_account(session, principal, row["account_id"])
    if row["state"] != "drafted":
        raise HTTPException(status_code=409, detail=f"action is already '{row['state']}'")

    session.execute(
        text(
            "UPDATE action SET state = 'rejected', state_reason = :r, decided_by_user_id = :u,"
            " decided_at = now() WHERE id = :i"
        ),
        {"r": req.reason, "u": principal.user_id, "i": action_id},
    )
    return _row_to_dict(_fetch(session, action_id))


@router.patch("/actions/{action_id}")
def edit_action(
    action_id: uuid.UUID, req: EditRequest, session: Session = Depends(get_session),
    principal: Principal = Depends(get_principal),
):
    row = _fetch(session, action_id)
    require_visible_account(session, principal, row["account_id"])
    if row["state"] != "drafted":
        raise HTTPException(
            status_code=409, detail=f"cannot edit an action already '{row['state']}'",
        )

    session.execute(
        text(
            "UPDATE action SET subject = COALESCE(:subj, subject), body = COALESCE(:body, body),"
            " decided_by_user_id = :u, decided_at = now() WHERE id = :i"
        ),
        {"subj": req.subject, "body": req.body, "u": principal.user_id, "i": action_id},
    )
    return _row_to_dict(_fetch(session, action_id))
