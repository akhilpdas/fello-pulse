"""The run log (T089): autonomous cycles with stage counts, what the agent
declined to do and why, and durations -- the audit surface for Principle III."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from pulse.api.deps import get_session

router = APIRouter()


@router.get("/runs")
def list_runs(limit: int = Query(default=50, ge=1, le=500), session: Session = Depends(get_session)):
    rows = session.execute(
        text("SELECT id, trigger, started_at, finished_at, status, as_of, stage_counts,"
             " decisions_declined, errors, duration_ms FROM agent_run"
             " ORDER BY started_at DESC LIMIT :n"),
        {"n": limit},
    ).mappings().all()
    return [{
        "id": str(r["id"]), "trigger": r["trigger"], "status": r["status"],
        "started_at": r["started_at"].isoformat(),
        "finished_at": r["finished_at"].isoformat() if r["finished_at"] else None,
        "as_of": r["as_of"].isoformat(), "stage_counts": r["stage_counts"],
        "decisions_declined": r["decisions_declined"], "errors": r["errors"],
        "duration_ms": r["duration_ms"],
    } for r in rows]
