"""The autonomous cycle (T065): score every active account, detect material
change, select an eligible play, apply policy, draft, validate grounding,
persist the action, and write an ``agent_run`` with full stage counts and
every declined decision.

Scope note: ingestion itself (``pulse.cli ingest``) is a separate, already
unattended pipeline stage (Phase 4) run on its own schedule; this cycle picks
up from already-ingested data and covers score -> detect -> select -> draft
-> dispatch. Nothing here re-implements ingestion -- wiring the two under one
scheduler is an operational concern, not a behavioural one, and is out of
this deliverable's scope.

Constitution Principle III: "a run that produced nothing must still say so."
Every account that doesn't end in a drafted or sent action ends up in
exactly one of ``stage_counts`` or ``decisions_declined`` with a reason --
there is no code path that silently does nothing.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from pulse.agent.drafter import draft as draft_fn
from pulse.agent.drafter import validate_grounding
from pulse.agent.plays import eligible_plays
from pulse.agent.policy import decide as policy_decide
from pulse.agent.transport import Transport
from pulse.auth import audit
from pulse.domain.change import material_change
from pulse.ml.train import TrainedModel
from pulse.scoring.service import score_and_persist


@dataclass(frozen=True, slots=True)
class CycleResult:
    run_id: uuid.UUID
    stage_counts: dict
    decisions_declined: list[dict]


def _previous_score(session: Session, account_id, before: datetime) -> dict | None:
    row = session.execute(
        text(
            "SELECT probability, tier, dominant_driver FROM score"
            " WHERE account_id = :a AND as_of < :before ORDER BY as_of DESC LIMIT 1"
        ),
        {"a": account_id, "before": before},
    ).mappings().first()
    if row is None:
        return None
    # probability is NUMERIC in Postgres -- psycopg hands back Decimal, and
    # material_change does float arithmetic on it.
    return {"probability": float(row["probability"]), "tier": row["tier"],
            "dominant_driver": row["dominant_driver"]}


def _days_to_renewal(session: Session, score_id) -> float | None:
    return session.execute(
        text("SELECT (ranking_math->>'days_to_renewal')::float FROM score WHERE id = :i"),
        {"i": score_id},
    ).scalar()


def _is_suppressed(session: Session, account_id, as_of: datetime) -> bool:
    return bool(session.execute(
        text(
            "SELECT 1 FROM suppression WHERE account_id = :a"
            " AND (expires_at IS NULL OR expires_at > :ao) LIMIT 1"
        ),
        {"a": account_id, "ao": as_of},
    ).scalar())


def _last_action_at(session: Session, account_id) -> datetime | None:
    return session.execute(
        text("SELECT max(created_at) FROM action WHERE account_id = :a"),
        {"a": account_id},
    ).scalar()


def _auto_send_allowlisted(session: Session, play_key: str) -> bool:
    return bool(session.execute(
        text("SELECT auto_send FROM play_allowlist WHERE play_key = :p"),
        {"p": play_key},
    ).scalar())


def _evidence_drivers_for_snapshot(session: Session, snapshot_id) -> set[str]:
    evidence = session.execute(
        text("SELECT evidence FROM feature_snapshot WHERE id = :i"), {"i": snapshot_id},
    ).scalar()
    return {k for k, v in (evidence or {}).items() if v}


def run_cycle(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    model: TrainedModel,
    model_version: str,
    tenant_config: dict,
    as_of: datetime,
    transport: Transport,
    trigger: str = "schedule",
    csm_name: str = "Your CSM",
    llm_enabled: bool = False,
    llm_api_key: str | None = None,
) -> CycleResult:
    run_id = uuid.uuid4()
    session.execute(
        text(
            "INSERT INTO agent_run (id, tenant_id, trigger, started_at, status, as_of,"
            " stage_counts, decisions_declined, errors)"
            " VALUES (:i, :t, :trg, now(), 'running', :ao, '{}'::jsonb, '[]'::jsonb, '[]'::jsonb)"
        ),
        {"i": run_id, "t": tenant_id, "trg": trigger, "ao": as_of},
    )

    account_ids = [
        r[0] for r in session.execute(
            text("SELECT id FROM account WHERE tenant_id = :t AND lifecycle_state = 'active'"),
            {"t": tenant_id},
        ).all()
    ]

    stage_counts = {
        "scored": 0, "material_change": 0, "drafted": 0, "sent": 0, "declined": 0,
    }
    declined: list[dict] = []
    sends_this_cycle = 0

    for account_id in account_ids:
        scored = score_and_persist(
            session, tenant_id=tenant_id, account_id=account_id, model=model,
            model_version=model_version, tenant_config=tenant_config, as_of=as_of,
        )
        stage_counts["scored"] += 1

        previous = _previous_score(session, account_id, as_of)
        changed, _reason = material_change(
            previous=previous, probability=scored.probability, tier=scored.tier,
            dominant_driver=scored.dominant_driver, material_delta=tenant_config["material_delta"],
        )
        if not changed:
            continue
        stage_counts["material_change"] += 1

        days_to_renewal = _days_to_renewal(session, scored.score_id)
        plays = eligible_plays(
            dominant_driver=scored.dominant_driver, tier=scored.tier,
            confidence=scored.confidence, days_to_renewal=days_to_renewal,
        )
        if not plays:
            declined.append({"account_id": str(account_id), "reason": "no_eligible_play"})
            stage_counts["declined"] += 1
            continue
        play = plays[0]

        human_suppressed = _is_suppressed(session, account_id, as_of)
        last_action_at = _last_action_at(session, account_id)
        auto_send_allowlisted = _auto_send_allowlisted(session, play.key)

        policy = policy_decide(
            human_suppressed=human_suppressed, last_action_at=last_action_at, now=as_of,
            suppression_days=tenant_config["suppression_days"],
            auto_send_allowlisted=auto_send_allowlisted, sends_this_cycle=sends_this_cycle,
            max_sends_per_cycle=tenant_config["max_sends_per_cycle"],
        )
        if not policy.allow_draft:
            declined.append({"account_id": str(account_id), "play": play.key, "reason": policy.reason})
            stage_counts["declined"] += 1
            continue

        account_name = session.execute(
            text("SELECT name FROM account WHERE id = :i"), {"i": account_id},
        ).scalar()
        d = draft_fn(
            play.key, account_name=account_name, csm_name=csm_name,
            llm_enabled=llm_enabled, llm_api_key=llm_api_key,
        )

        evidence_drivers = _evidence_drivers_for_snapshot(session, scored.feature_snapshot_id)
        ok, reason = validate_grounding(d, evidence_drivers)
        if not ok:
            declined.append({"account_id": str(account_id), "play": play.key, "reason": reason})
            stage_counts["declined"] += 1
            continue

        state = "drafted"
        sent_at = None
        attempts = 0
        # Every withholding of auto-send carries its reason onto the Action
        # row itself (T070) -- "not_allowlisted_for_auto_send" is the normal,
        # safe default and is not a run-level decline; a failed send attempt
        # is both (declined at the run level, and visible on the row for
        # T076's retry/surfacing path).
        state_reason = policy.reason
        if policy.allow_auto_send:
            attempts = 1
            result = transport.send(to=f"csm+{account_id}@example.test", subject=d.subject, body=d.body)
            if result.ok:
                state = "sent"
                sent_at = as_of
                sends_this_cycle += 1
                state_reason = None
            else:
                state_reason = f"send_failed:{result.error}"
                declined.append({
                    "account_id": str(account_id), "play": play.key, "reason": state_reason,
                })

        action_id = uuid.uuid4()
        session.execute(
            text(
                "INSERT INTO action (id, tenant_id, account_id, score_id, agent_run_id, play_key,"
                " state, state_reason, channel, subject, body, draft_source, grounding, created_at,"
                " sent_at, attempts)"
                " VALUES (:i, :t, :a, :s, :r, :pk, :st, :sr, :ch, :subj, :body, :ds, CAST(:g AS jsonb),"
                " now(), :sa, :att)"
            ),
            {
                "i": action_id, "t": tenant_id, "a": account_id, "s": scored.score_id,
                "r": run_id, "pk": play.key, "st": state, "sr": state_reason, "ch": play.channel,
                "subj": d.subject, "body": d.body, "ds": d.draft_source,
                "g": json.dumps({"evidence_drivers": sorted(evidence_drivers)}),
                "sa": sent_at, "att": attempts,
            },
        )
        stage_counts["drafted"] += 1
        if state == "sent":
            stage_counts["sent"] += 1

    session.execute(
        text(
            "UPDATE agent_run SET status = 'succeeded', finished_at = clock_timestamp(),"
            " duration_ms = GREATEST(1, (extract(epoch FROM clock_timestamp() - started_at) * 1000)::int),"
            " stage_counts = CAST(:sc AS jsonb),"
            " decisions_declined = CAST(:dd AS jsonb) WHERE id = :i"
        ),
        {"sc": json.dumps(stage_counts), "dd": json.dumps(declined), "i": run_id},
    )

    # The worker acts as the system, never as a person (FR-010): the cycle is attributed accordingly.
    audit.record(session, "cycle_run", actor_kind="system", subject=str(run_id), detail=stage_counts)

    return CycleResult(run_id=run_id, stage_counts=stage_counts, decisions_declined=declined)
