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

from pulse.agent.transport import Transport, send_with_retry
from pulse.api.deps import get_session, get_transport

router = APIRouter()

MAX_SEND_ATTEMPTS = 3


class ApproveRequest(BaseModel):
    actor_user_id: uuid.UUID


class RejectRequest(BaseModel):
    actor_user_id: uuid.UUID
    reason: str | None = None


class EditRequest(BaseModel):
    actor_user_id: uuid.UUID
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
    }


def _fetch(session: Session, action_id: uuid.UUID) -> dict:
    row = session.execute(
        text(
            "SELECT id, account_id, play_key, state, state_reason, channel, subject, body,"
            " draft_source, created_at, decided_at, decided_by_user_id, sent_at, attempts, grounding"
            " FROM action WHERE id = :i"
        ),
        {"i": action_id},
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="action not found")
    return dict(row)


@router.get("/actions")
def list_actions(state: str | None = Query(default=None), session: Session = Depends(get_session)):
    sql = "SELECT id, account_id, play_key, state, state_reason, channel, subject, body," \
          " draft_source, created_at, decided_at, decided_by_user_id, sent_at, attempts, grounding FROM action"
    params = {}
    if state is not None:
        sql += " WHERE state = :state"
        params["state"] = state
    sql += " ORDER BY created_at DESC"
    rows = session.execute(text(sql), params).mappings().all()
    return {"rows": [_row_to_dict(r) for r in rows]}


@router.post("/actions/{action_id}/approve")
def approve_action(
    action_id: uuid.UUID, req: ApproveRequest,
    session: Session = Depends(get_session), transport: Transport = Depends(get_transport),
):
    row = _fetch(session, action_id)
    if row["state"] != "drafted":
        raise HTTPException(status_code=409, detail=f"action is already '{row['state']}'")

    session.execute(
        text(
            "UPDATE action SET state = 'approved', decided_by_user_id = :u, decided_at = now()"
            " WHERE id = :i"
        ),
        {"u": req.actor_user_id, "i": action_id},
    )

    to = f"csm+{row['account_id']}@example.test"
    result, attempts = send_with_retry(
        transport, to=to, subject=row["subject"] or "", body=row["body"] or "",
        max_attempts=MAX_SEND_ATTEMPTS,
    )
    if result.ok:
        session.execute(
            text(
                "UPDATE action SET state = 'sent', state_reason = NULL, sent_at = now(),"
                " attempts = :att WHERE id = :i"
            ),
            {"att": attempts, "i": action_id},
        )
    else:
        # Surfaced, not swallowed: 'send_failed' is a distinct, queryable
        # state a human (or an alert) can act on, carrying exactly why the
        # last attempt failed.
        session.execute(
            text(
                "UPDATE action SET state = 'send_failed', state_reason = :r, attempts = :att"
                " WHERE id = :i"
            ),
            {"r": result.error, "att": attempts, "i": action_id},
        )

    return _row_to_dict(_fetch(session, action_id))


@router.post("/actions/{action_id}/reject")
def reject_action(action_id: uuid.UUID, req: RejectRequest, session: Session = Depends(get_session)):
    row = _fetch(session, action_id)
    if row["state"] != "drafted":
        raise HTTPException(status_code=409, detail=f"action is already '{row['state']}'")

    session.execute(
        text(
            "UPDATE action SET state = 'rejected', state_reason = :r, decided_by_user_id = :u,"
            " decided_at = now() WHERE id = :i"
        ),
        {"r": req.reason, "u": req.actor_user_id, "i": action_id},
    )
    return _row_to_dict(_fetch(session, action_id))


@router.patch("/actions/{action_id}")
def edit_action(action_id: uuid.UUID, req: EditRequest, session: Session = Depends(get_session)):
    row = _fetch(session, action_id)
    if row["state"] != "drafted":
        raise HTTPException(
            status_code=409, detail=f"cannot edit an action already '{row['state']}'",
        )

    session.execute(
        text(
            "UPDATE action SET subject = COALESCE(:subj, subject), body = COALESCE(:body, body),"
            " decided_by_user_id = :u, decided_at = now() WHERE id = :i"
        ),
        {"subj": req.subject, "body": req.body, "u": req.actor_user_id, "i": action_id},
    )
    return _row_to_dict(_fetch(session, action_id))
