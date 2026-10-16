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

from pulse.api.deps import get_session
from pulse.domain.confidence import REMEDIES

router = APIRouter()

_QUEUE_SQL = text(
    """
    WITH scored AS (
        SELECT
            s.account_id, s.as_of, s.tier, s.health_score, s.probability,
            s.value_at_risk_cents, s.dominant_driver, s.priority, s.confidence,
            s.abstain_reason, (s.ranking_math->>'days_to_renewal')::float AS days_to_renewal,
            LAG(s.probability) OVER (PARTITION BY s.account_id ORDER BY s.as_of) AS prev_probability
        FROM score s
        WHERE s.tenant_id = :tenant_id
    )
    SELECT scored.*, a.name AS account_name
    FROM scored
    JOIN account a ON a.id = scored.account_id
    WHERE scored.as_of = :as_of
      AND scored.tier <> 'abstain'
      AND scored.account_id NOT IN (
          SELECT account_id FROM suppression
          WHERE tenant_id = :tenant_id AND (expires_at IS NULL OR expires_at > now())
      )
    ORDER BY scored.priority DESC
    """
)


@router.get("/queue")
def get_queue(
    as_of: datetime | None = Query(default=None),
    session: Session = Depends(get_session),
):
    if as_of is None:
        as_of = session.execute(text("SELECT max(as_of) FROM score")).scalar()
        if as_of is None:
            return {"as_of": None, "rows": [], "below_cut": 0}

    tenant_row_id = session.execute(text("SELECT current_setting('pulse.tenant_id')::uuid")).scalar()
    capacity = session.execute(
        text("SELECT weekly_capacity FROM tenant_config WHERE tenant_id = :t"), {"t": tenant_row_id}
    ).scalar() or 10

    rows = session.execute(_QUEUE_SQL, {"tenant_id": tenant_row_id, "as_of": as_of}).mappings().all()

    out_rows = []
    for r in rows[:capacity]:
        delta = None
        if r["prev_probability"] is not None:
            delta = float(r["probability"]) - float(r["prev_probability"])
        out_rows.append({
            "account_id": str(r["account_id"]),
            "account_name": r["account_name"],
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
        })

    below_cut = max(0, len(rows) - capacity)
    return {"as_of": as_of.isoformat(), "rows": out_rows, "below_cut": below_cut}


@router.get("/queue/low-confidence")
def get_low_confidence(
    as_of: datetime | None = Query(default=None),
    session: Session = Depends(get_session),
):
    """Accounts the system declined to score (SC-012): their own surface, with the
    machine-readable reason and a human remedy, never folded into the ranked queue."""
    if as_of is None:
        as_of = session.execute(text("SELECT max(as_of) FROM score")).scalar()
        if as_of is None:
            return {"as_of": None, "rows": []}
    rows = session.execute(
        text("SELECT s.account_id, a.name, s.abstain_reason, s.value_at_risk_cents"
             " FROM score s JOIN account a ON a.id = s.account_id"
             " WHERE s.as_of = :as_of AND s.tier = 'abstain'"
             " ORDER BY s.value_at_risk_cents DESC NULLS LAST, a.name"),
        {"as_of": as_of},
    ).mappings().all()
    return {"as_of": as_of.isoformat(), "rows": [
        {"account_id": str(r["account_id"]), "account_name": r["name"],
         "abstain_reason": r["abstain_reason"], "value_at_risk_cents": r["value_at_risk_cents"],
         "remedy": REMEDIES.get(r["abstain_reason"], "Review the account's data coverage.")}
        for r in rows]}
