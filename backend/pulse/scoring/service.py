"""The serving path: compute features, predict, calibrate, attribute, tier,
gate confidence, rank, persist -- with full lineage (constitution Principle V).

Uses the exact same ``features/compute.py`` function the training panel calls,
via the same ``features/repository.py`` adapter -- the train/serve parity
guarantee is structural, not tested-in after the fact.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from pulse.domain.confidence import assess_confidence
from pulse.domain.ranking import urgency_multiplier
from pulse.domain.tiers import health_score, tier_for
from pulse.features.compute import compute
from pulse.features.repository import (
    identity_unresolved_for_account,
    load_account_feature_input,
    load_events,
)
from pulse.ml.explain import contributions, dominant_driver, driver_contributions
from pulse.ml.train import TrainedModel, predict_proba, predict_proba_raw

FEATURE_SET_VERSION = "fs-1"


@dataclass(frozen=True, slots=True)
class ScoredAccount:
    account_id: uuid.UUID
    as_of: datetime
    feature_snapshot_id: uuid.UUID
    score_id: uuid.UUID
    probability: float
    tier: str
    confidence: str
    abstain_reason: str | None
    dominant_driver: str | None
    priority: float


def score_and_persist(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    account_id: uuid.UUID,
    model: TrainedModel,
    model_version: str,
    tenant_config: dict,
    as_of: datetime,
) -> ScoredAccount:
    events = load_events(session, account_id)
    account_input = load_account_feature_input(session, account_id)
    unresolved = identity_unresolved_for_account(session, account_id)

    result = compute(
        connected_sources=tenant_config["connected_sources"], account=account_input,
        events=events, as_of=as_of, identity_unresolved=unresolved,
    )

    conf = assess_confidence(
        result.values, tenant_config["min_days_history"], tenant_config["min_sources_with_data"],
    )

    probability = float(predict_proba(model, [result.values])[0])
    probability_raw = float(predict_proba_raw(model, [result.values])[0])
    # SC-012: thin evidence is never presented as a trustworthy tier, red,
    # amber or green -- "abstain" is a tier of its own, not a fallback to green.
    tier = "abstain" if conf.abstain else tier_for(
        probability, tenant_config["tier_red_at"], tenant_config["tier_amber_at"],
    )

    per_feature = contributions(model, result.values)
    driver_totals = driver_contributions(per_feature)
    dominant = dominant_driver(driver_totals)

    value_at_risk_cents = float(result.values.get("acv_cents") or 0.0)
    urgency = urgency_multiplier(result.values.get("days_to_renewal"))
    priority = 0.0 if conf.abstain else probability * value_at_risk_cents * urgency

    ranking_math = {
        "probability": probability,
        "value_at_risk_cents": value_at_risk_cents,
        "urgency_multiplier": urgency,
        "days_to_renewal": result.values.get("days_to_renewal"),
        "priority": priority,
    }

    snapshot_id = uuid.uuid4()
    session.execute(
        text(
            "INSERT INTO feature_snapshot (id, tenant_id, account_id, as_of, values,"
            " evidence, coverage, days_of_history, feature_set_version, computed_at)"
            " VALUES (:i, :t, :a, :ao, CAST(:v AS jsonb), CAST(:e AS jsonb),"
            " CAST(:c AS jsonb), :d, :fsv, now())"
            " ON CONFLICT (tenant_id, account_id, as_of, feature_set_version) DO UPDATE SET"
            "   values = EXCLUDED.values"
            " RETURNING id"
        ),
        {
            "i": snapshot_id, "t": tenant_id, "a": account_id, "ao": as_of,
            "v": json.dumps(result.values), "e": json.dumps(result.evidence),
            "c": json.dumps(result.coverage), "d": int(result.days_of_history),
            "fsv": FEATURE_SET_VERSION,
        },
    )
    actual_snapshot_id = session.execute(
        text(
            "SELECT id FROM feature_snapshot WHERE tenant_id = :t AND account_id = :a"
            " AND as_of = :ao AND feature_set_version = :fsv"
        ),
        {"t": tenant_id, "a": account_id, "ao": as_of, "fsv": FEATURE_SET_VERSION},
    ).scalar()

    score_id = uuid.uuid4()
    session.execute(
        text(
            "INSERT INTO score (id, tenant_id, account_id, as_of, model_version,"
            " feature_snapshot_id, probability, probability_raw, tier, health_score,"
            " confidence, abstain_reason, contributions, dominant_driver,"
            " value_at_risk_cents, urgency_multiplier, priority, ranking_math, created_at)"
            " VALUES (:i, :t, :a, :ao, :mv, :fs, :p, :pr, :tier, :hs, :conf, :reason,"
            " CAST(:co AS jsonb), :dom, :var, :urg, :pri, CAST(:rm AS jsonb), now())"
            " ON CONFLICT (tenant_id, account_id, as_of) DO NOTHING"
        ),
        {
            "i": score_id, "t": tenant_id, "a": account_id, "ao": as_of, "mv": model_version,
            "fs": actual_snapshot_id, "p": round(probability, 5), "pr": round(probability_raw, 5),
            "tier": tier, "hs": health_score(probability), "conf": conf.confidence,
            "reason": conf.reason, "co": json.dumps(per_feature), "dom": dominant,
            "var": int(value_at_risk_cents), "urg": urgency, "pri": priority,
            "rm": json.dumps(ranking_math),
        },
    )
    actual_score_id = session.execute(
        text("SELECT id FROM score WHERE tenant_id = :t AND account_id = :a AND as_of = :ao"),
        {"t": tenant_id, "a": account_id, "ao": as_of},
    ).scalar()

    return ScoredAccount(
        account_id=account_id, as_of=as_of, feature_snapshot_id=actual_snapshot_id,
        score_id=actual_score_id, probability=probability, tier=tier,
        confidence=conf.confidence, abstain_reason=conf.reason, dominant_driver=dominant,
        priority=priority,
    )
