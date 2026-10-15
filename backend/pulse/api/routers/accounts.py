"""Account detail, evidence resolution, and score-diff -- User Story 2, the
evidence trail. Constitution Principle V: anything a CSM sees must be
traceable to the records the system actually read.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from pulse.api.deps import get_session
from pulse.ml.explain import driver_contributions

router = APIRouter()


def _latest_as_of_for_account(session: Session, account_id: uuid.UUID) -> datetime | None:
    return session.execute(
        text("SELECT max(as_of) FROM score WHERE account_id = :a"), {"a": account_id}
    ).scalar()


def _score_row(session: Session, account_id: uuid.UUID, as_of: datetime):
    return session.execute(
        text(
            "SELECT s.id, s.as_of, s.tier, s.health_score, s.probability, s.probability_raw,"
            " s.confidence, s.abstain_reason, s.dominant_driver, s.contributions,"
            " s.value_at_risk_cents, s.priority, s.ranking_math, s.feature_snapshot_id,"
            " fs.values AS feature_values, fs.evidence, fs.coverage, fs.days_of_history"
            " FROM score s JOIN feature_snapshot fs ON fs.id = s.feature_snapshot_id"
            " WHERE s.account_id = :a AND s.as_of = :ao"
        ),
        {"a": account_id, "ao": as_of},
    ).mappings().one_or_none()


@router.get("/accounts/{account_id}")
def get_account(
    account_id: uuid.UUID,
    as_of: datetime | None = Query(default=None),
    session: Session = Depends(get_session),
):
    if as_of is None:
        as_of = _latest_as_of_for_account(session, account_id)
        if as_of is None:
            raise HTTPException(404, "no score for this account")

    row = _score_row(session, account_id, as_of)
    if row is None:
        raise HTTPException(404, "no score for this account at that as_of")

    account_name = session.execute(
        text("SELECT name FROM account WHERE id = :a"), {"a": account_id}
    ).scalar()

    driver_totals = driver_contributions(row["contributions"]) if row["contributions"] else {}

    return {
        "account_id": str(account_id),
        "account_name": account_name,
        "as_of": row["as_of"].isoformat(),
        "tier": row["tier"],
        "health_score": row["health_score"],
        "probability": float(row["probability"]),
        "confidence": row["confidence"],
        "abstain_reason": row["abstain_reason"],
        "dominant_driver": row["dominant_driver"],
        "driver_totals": driver_totals,
        "value_at_risk_cents": row["value_at_risk_cents"],
        "priority": float(row["priority"]),
        "ranking_math": row["ranking_math"],
        "feature_values": row["feature_values"],
        "evidence": row["evidence"],
        "coverage": row["coverage"],
        "days_of_history": row["days_of_history"],
    }


@router.get("/accounts/{account_id}/evidence")
def get_evidence(
    account_id: uuid.UUID,
    event_ids: list[int] = Query(...),
    session: Session = Depends(get_session),
):
    """Resolve evidence ids to the original source records. Scoped to the
    account so one account's evidence can never be used to pull another's."""
    rows = session.execute(
        text(
            "SELECT id, source, event_type, occurred_at, received_at, payload"
            " FROM source_event WHERE account_id = :a AND id = ANY(:ids)"
            " ORDER BY received_at"
        ),
        {"a": account_id, "ids": event_ids},
    ).mappings().all()
    return {
        "events": [
            {
                "id": r["id"], "source": r["source"], "event_type": r["event_type"],
                "occurred_at": r["occurred_at"].isoformat(), "received_at": r["received_at"].isoformat(),
                "payload": r["payload"],
            }
            for r in rows
        ]
    }


@router.get("/accounts/{account_id}/score-diff")
def score_diff(
    account_id: uuid.UUID,
    from_as_of: datetime = Query(...),
    to_as_of: datetime = Query(...),
    session: Session = Depends(get_session),
):
    """Feature-level diff between two scores, with the per-feature
    contribution change -- "why did this move," answerable without a data
    pull (FR-027)."""
    from_row = _score_row(session, account_id, from_as_of)
    to_row = _score_row(session, account_id, to_as_of)
    if from_row is None or to_row is None:
        raise HTTPException(404, "no score for this account at one of the requested as_of values")

    from_values, to_values = from_row["feature_values"], to_row["feature_values"]
    from_contrib, to_contrib = from_row["contributions"] or {}, to_row["contributions"] or {}
    all_names = sorted(set(from_values) | set(to_values))

    feature_diffs = []
    for name in all_names:
        fv, tv = from_values.get(name), to_values.get(name)
        fc, tc = from_contrib.get(name, 0.0), to_contrib.get(name, 0.0)
        value_delta = (tv - fv) if isinstance(fv, (int, float)) and isinstance(tv, (int, float)) else None
        feature_diffs.append({
            "feature": name, "from_value": fv, "to_value": tv, "value_delta": value_delta,
            "from_contribution": fc, "to_contribution": tc, "contribution_delta": tc - fc,
        })
    feature_diffs.sort(key=lambda d: -abs(d["contribution_delta"]))

    return {
        "account_id": str(account_id),
        "from": {"as_of": from_row["as_of"].isoformat(), "probability": float(from_row["probability"]),
                  "tier": from_row["tier"], "dominant_driver": from_row["dominant_driver"]},
        "to": {"as_of": to_row["as_of"].isoformat(), "probability": float(to_row["probability"]),
               "tier": to_row["tier"], "dominant_driver": to_row["dominant_driver"]},
        "probability_delta": float(to_row["probability"]) - float(from_row["probability"]),
        "feature_diffs": feature_diffs,
    }
