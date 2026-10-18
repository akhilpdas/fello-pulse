"""GET /queue -- the Monday morning work list (User Story 1, the MVP).

Bounded by the tenant's weekly capacity, ordered by priority, every row
carrying what a CSM needs to act: the reason (dominant driver), the value at
risk, the renewal distance, and the delta from the account's previous score
(material-change context, not just a snapshot).
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from pulse.api.deps import get_principal, get_session
from pulse.api.visibility import visible_clause
from pulse.auth.principal import Principal
from pulse.domain.confidence import REMEDIES

router = APIRouter()

_QUEUE_SQL = """
    WITH scored AS (
        SELECT
            s.account_id, s.as_of, s.tier, s.health_score, s.probability,
            s.value_at_risk_cents, s.dominant_driver, s.priority, s.confidence,
            s.abstain_reason, (s.ranking_math->>'days_to_renewal')::float AS days_to_renewal,
            LAG(s.probability) OVER (PARTITION BY s.account_id ORDER BY s.as_of) AS prev_probability
        FROM score s
        WHERE s.tenant_id = :tenant_id
    )
    SELECT scored.*, a.name AS account_name, a.external_ref
    FROM scored
    JOIN account a ON a.id = scored.account_id
    WHERE scored.as_of = :as_of
      AND scored.tier <> 'abstain'
      AND {visible}
      AND scored.account_id NOT IN (
          SELECT account_id FROM suppression
          WHERE tenant_id = :tenant_id AND (expires_at IS NULL OR expires_at > now())
      )
    ORDER BY scored.priority DESC
    """



def _latest_as_of(session: Session) -> datetime | None:
    return session.execute(text("SELECT max(as_of) FROM score")).scalar()


def _ranked(session: Session, principal: Principal, as_of: datetime) -> tuple[list, int]:
    """Every visible, non-suppressed, scored account at ``as_of`` in priority order, plus the weekly capacity."""
    tenant_row_id = session.execute(text("SELECT current_setting('pulse.tenant_id')::uuid")).scalar()
    capacity = session.execute(
        text("SELECT weekly_capacity FROM tenant_config WHERE tenant_id = :t"), {"t": tenant_row_id}
    ).scalar() or 10
    visible, vparams = visible_clause(principal)
    rows = session.execute(
        text(_QUEUE_SQL.format(visible=visible)), {"tenant_id": tenant_row_id, "as_of": as_of, **vparams}
    ).mappings().all()
    return list(rows), capacity


def _row(r) -> dict:
    delta = None
    if r["prev_probability"] is not None:
        delta = float(r["probability"]) - float(r["prev_probability"])
    return {
        "account_id": str(r["account_id"]),
        "account_name": r["account_name"],
        "external_ref": r["external_ref"],
        "tier": r["tier"],
        "health_score": r["health_score"],
        "probability": float(r["probability"]),
        "value_at_risk_cents": r["value_at_risk_cents"],
        "dominant_driver": r["dominant_driver"],
        "days_to_renewal": r["days_to_renewal"],
        "priority": float(r["priority"]),
        "confidence": r["confidence"],
        "abstain_reason": r["abstain_reason"],
        "delta": delta,
    }


@router.get("/queue")
def get_queue(
    as_of: datetime | None = Query(default=None),
    session: Session = Depends(get_session),
    principal: Principal = Depends(get_principal),
):
    if as_of is None:
        as_of = _latest_as_of(session)
        if as_of is None:
            return {"as_of": None, "rows": [], "below_cut": 0}

    rows, capacity = _ranked(session, principal, as_of)
    out_rows = [_row(r) for r in rows[:capacity]]
    below_cut = max(0, len(rows) - capacity)
    return {"as_of": as_of.isoformat(), "rows": out_rows, "below_cut": below_cut}


@router.get("/queue/snapshots")
def get_queue_snapshots(
    session: Session = Depends(get_session),
    principal: Principal = Depends(get_principal),
):
    """The days a queue exists for, newest first, with how many of the caller's accounts were scored. The worker cycles
    every 15 minutes, so a day holds many snapshots; one entry per (UTC) day -- the day's last -- keeps the picker usable."""
    visible, vparams = visible_clause(principal)
    rows = session.execute(
        text("SELECT DISTINCT ON ((as_of AT TIME ZONE 'UTC')::date) as_of, scored FROM ("
             "  SELECT s.as_of, count(*) AS scored FROM score s JOIN account a ON a.id = s.account_id"
             f"  WHERE {visible} GROUP BY s.as_of) per_snapshot"
             " ORDER BY (as_of AT TIME ZONE 'UTC')::date DESC, as_of DESC"),
        vparams,
    ).all()
    return {"snapshots": [{"as_of": r[0].isoformat(), "scored": r[1]} for r in rows]}


@router.get("/queue/all")
def get_queue_all(
    as_of: datetime | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    tier: str | None = Query(default=None),
    driver: str | None = Query(default=None),
    q: str | None = Query(default=None),
    session: Session = Depends(get_session),
    principal: Principal = Depends(get_principal),
):
    """The same ranking as ``/queue`` without the capacity cut: paginated and filterable. ``rank`` is the account's
    position in the full ranking (so it is stable under filtering and paging); ``in_queue`` says whether it is inside
    this week's capacity."""
    if as_of is None:
        as_of = _latest_as_of(session)
        if as_of is None:
            return {"as_of": None, "rows": [], "total": 0, "offset": offset, "limit": limit, "capacity": 0}

    rows, capacity = _ranked(session, principal, as_of)
    ranked = [(rank, r) for rank, r in enumerate(rows, start=1)]
    if tier:
        ranked = [(k, r) for k, r in ranked if r["tier"] == tier]
    if driver:
        ranked = [(k, r) for k, r in ranked if r["dominant_driver"] == driver]
    if q:
        needle = q.strip().lower()
        ranked = [(k, r) for k, r in ranked if needle in (r["account_name"] or "").lower()]
    page = [{**_row(r), "rank": k, "in_queue": k <= capacity} for k, r in ranked[offset:offset + limit]]
    return {"as_of": as_of.isoformat(), "rows": page, "total": len(ranked), "offset": offset, "limit": limit,
            "capacity": capacity}


@router.get("/queue/low-confidence")
def get_low_confidence(
    as_of: datetime | None = Query(default=None),
    session: Session = Depends(get_session),
    principal: Principal = Depends(get_principal),
):
    """Accounts the system declined to score (SC-012): their own surface, with the
    machine-readable reason and a human remedy, never folded into the ranked queue."""
    if as_of is None:
        as_of = session.execute(text("SELECT max(as_of) FROM score")).scalar()
        if as_of is None:
            return {"as_of": None, "rows": []}
    visible, vparams = visible_clause(principal)
    rows = session.execute(
        text("SELECT s.account_id, a.name, s.abstain_reason, s.value_at_risk_cents"
             " FROM score s JOIN account a ON a.id = s.account_id"
             f" WHERE s.as_of = :as_of AND s.tier = 'abstain' AND {visible}"
             " ORDER BY s.value_at_risk_cents DESC NULLS LAST, a.name"),
        {"as_of": as_of, **vparams},
    ).mappings().all()
    return {"as_of": as_of.isoformat(), "rows": [
        {"account_id": str(r["account_id"]), "account_name": r["name"],
         "abstain_reason": r["abstain_reason"], "value_at_risk_cents": r["value_at_risk_cents"],
         "remedy": REMEDIES.get(r["abstain_reason"], "Review the account's data coverage.")}
        for r in rows]}
