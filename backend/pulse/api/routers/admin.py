"""Per-tenant configuration and play allowlist management (T078, operator
role only). Both are tenant-scoped through the RLS session, so an operator
can only ever change their own tenant's behaviour; enabling auto-send records
the operator who did it (constitution Principle III).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.orm import Session

from pulse.agent.plays import PLAYS
from pulse.api.deps import get_session

router = APIRouter(prefix="/admin")

CONFIG_FIELDS = (
    "horizon_days", "contraction_threshold", "weekly_capacity", "tier_red_at", "tier_amber_at",
    "min_days_history", "min_sources_with_data", "suppression_days", "max_sends_per_cycle",
    "material_delta",
)


class ConfigPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    horizon_days: int | None = None
    contraction_threshold: float | None = None
    weekly_capacity: int | None = None
    tier_red_at: float | None = None
    tier_amber_at: float | None = None
    min_days_history: int | None = None
    min_sources_with_data: int | None = None
    suppression_days: int | None = None
    max_sends_per_cycle: int | None = None
    material_delta: float | None = None


class AllowlistPut(BaseModel):
    auto_send: bool


def require_operator(
    x_user_id: str = Header(...), session: Session = Depends(get_session)
) -> uuid.UUID:
    user_id = uuid.UUID(x_user_id)
    role = session.execute(text("SELECT role FROM app_user WHERE id = :i"), {"i": user_id}).scalar()
    if role != "operator":
        raise HTTPException(status_code=403, detail="operator role required")
    return user_id


def _config(session: Session) -> dict:
    row = session.execute(
        text(f"SELECT {', '.join(CONFIG_FIELDS)}, connected_sources FROM tenant_config")
    ).mappings().first()
    return {k: (float(v) if k in ("contraction_threshold", "tier_red_at", "tier_amber_at",
                                   "material_delta") else v) for k, v in row.items()}


@router.get("/config")
def get_config(_: uuid.UUID = Depends(require_operator), session: Session = Depends(get_session)):
    return _config(session)


@router.patch("/config")
def patch_config(
    patch: ConfigPatch,
    _: uuid.UUID = Depends(require_operator),
    session: Session = Depends(get_session),
):
    changes = patch.model_dump(exclude_none=True)
    if changes:
        sets = ", ".join(f"{k} = :{k}" for k in changes)
        session.execute(text(f"UPDATE tenant_config SET {sets}"), changes)
    return _config(session)


@router.get("/allowlist")
def get_allowlist(_: uuid.UUID = Depends(require_operator), session: Session = Depends(get_session)):
    rows = session.execute(
        text("SELECT play_key, auto_send, enabled_by_user_id FROM play_allowlist ORDER BY play_key")
    ).mappings().all()
    return [{"play_key": r["play_key"], "auto_send": r["auto_send"],
             "enabled_by_user_id": str(r["enabled_by_user_id"]) if r["enabled_by_user_id"] else None}
            for r in rows]


@router.put("/allowlist/{play_key}")
def put_allowlist(
    play_key: str,
    body: AllowlistPut,
    operator_id: uuid.UUID = Depends(require_operator),
    session: Session = Depends(get_session),
):
    if play_key not in PLAYS:
        raise HTTPException(status_code=404, detail="unknown play")
    session.execute(
        text(
            "INSERT INTO play_allowlist (id, tenant_id, play_key, auto_send, enabled_by_user_id,"
            " enabled_at) VALUES (:i, current_setting('pulse.tenant_id')::uuid, :p, :a, :u, now())"
            " ON CONFLICT (tenant_id, play_key) DO UPDATE SET auto_send = :a,"
            " enabled_by_user_id = :u, enabled_at = now()"
        ),
        {"i": uuid.uuid4(), "p": play_key, "a": body.auto_send, "u": operator_id},
    )
    return {"play_key": play_key, "auto_send": body.auto_send, "enabled_by_user_id": str(operator_id)}


ALL_SOURCES = ("salesforce", "gmail", "zendesk", "product", "stripe")


@router.get("/coverage")
def get_coverage(_: uuid.UUID = Depends(require_operator), session: Session = Depends(get_session)):
    """FR-012: per source, whether it is connected and what has actually landed.
    A source that is not connected reports zero events and no timestamp -- it is
    absent, which is different from connected-and-silent."""
    connected = set(session.execute(text("SELECT connected_sources FROM tenant_config")).scalar())
    landed = {
        r["source"]: r for r in session.execute(
            text("SELECT source, count(*) AS events, max(received_at) AS last_received_at,"
                 " count(*) FILTER (WHERE account_id IS NULL) AS unresolved"
                 " FROM source_event GROUP BY source")
        ).mappings()
    }
    out = []
    for source in ALL_SOURCES:
        row = landed.get(source)
        out.append({
            "source": source,
            "connected": source in connected,
            "events": row["events"] if row else 0,
            "unresolved_events": row["unresolved"] if row else 0,
            "last_received_at": row["last_received_at"].isoformat() if row else None,
        })
    return out
