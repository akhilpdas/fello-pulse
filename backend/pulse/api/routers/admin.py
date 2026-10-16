"""Per-tenant configuration and play allowlist management (T078, operator
role only). Both are tenant-scoped through the RLS session, so an operator
can only ever change their own tenant's behaviour; enabling auto-send records
the operator who did it (constitution Principle III).
"""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from pulse.agent.plays import PLAYS
from pulse.api.deps import get_session, require_operator
from pulse.auth import audit
from pulse.config import get_settings

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


# --------------------------------------------------------------------------- #
# Outbound email (002 / FR-014): whether and how this tenant sends
# --------------------------------------------------------------------------- #

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_OUTBOUND_FIELDS = ("outbound_enabled", "sender_address", "sender_verified", "demo_mode", "test_inbox")


def _valid_email(v: str | None) -> str | None:
    if v is not None and not _EMAIL.match(v.strip()):
        raise ValueError("must be an email address")
    return v.strip() if v is not None else None


class OutboundPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outbound_enabled: bool | None = None
    sender_address: str | None = None
    sender_verified: bool | None = None
    demo_mode: bool | None = None
    test_inbox: str | None = None

    _check_sender = field_validator("sender_address")(_valid_email)
    _check_inbox = field_validator("test_inbox")(_valid_email)


def _outbound(session: Session) -> dict:
    row = session.execute(text(f"SELECT {', '.join(_OUTBOUND_FIELDS)} FROM tenant_config")).mappings().one()
    return {**row, "smtp_configured": bool(get_settings().smtp_host)}


@router.get("/outbound")
def get_outbound(_: uuid.UUID = Depends(require_operator), session: Session = Depends(get_session)):
    return _outbound(session)


@router.patch("/outbound")
def patch_outbound(
    req: OutboundPatch, operator: uuid.UUID = Depends(require_operator), session: Session = Depends(get_session),
):
    current = _outbound(session)
    new = {k: current[k] for k in _OUTBOUND_FIELDS}
    given = req.model_dump(exclude_unset=True)

    # A new sender address has not been proven to be ours to send from: verification is revoked and
    # sending is switched off until an operator verifies it again. Flags sent in the *same* request win,
    # so one deliberate PATCH can set the address, verify it and enable sending.
    if "sender_address" in given and (given["sender_address"] or "").lower() != (current["sender_address"] or "").lower():
        new["sender_verified"], new["outbound_enabled"] = False, False
    new.update(given)

    if new["sender_verified"] and not new["sender_address"]:
        raise HTTPException(status_code=409, detail="cannot verify a sender: no sender address is set")
    if new["outbound_enabled"] and not (new["sender_address"] and new["sender_verified"]):
        raise HTTPException(status_code=409, detail="outbound email needs a verified sender address first")

    changed = {k: [current[k], new[k]] for k in _OUTBOUND_FIELDS if new[k] != current[k]}
    if changed:
        session.execute(
            text("UPDATE tenant_config SET outbound_enabled = :outbound_enabled, sender_address = :sender_address,"
                 " sender_verified = :sender_verified, demo_mode = :demo_mode, test_inbox = :test_inbox"),
            new,
        )
        audit.record(session, "outbound_changed", actor_user_id=operator, detail={"changes": changed})
    return _outbound(session)


# --------------------------------------------------------------------------- #
# Opt-outs (002 / FR-016): recipients we must not email again
# --------------------------------------------------------------------------- #


class OptOutCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    reason: str | None = None

    _check = field_validator("email")(lambda v: _valid_email(v).lower())


@router.get("/opt-outs")
def list_opt_outs(_: uuid.UUID = Depends(require_operator), session: Session = Depends(get_session)):
    rows = session.execute(text("SELECT id, email, reason, created_at FROM contact_opt_out ORDER BY email")).mappings().all()
    return [{"id": str(r["id"]), "email": r["email"], "reason": r["reason"], "created_at": r["created_at"].isoformat()}
            for r in rows]


@router.post("/opt-outs", status_code=201)
def add_opt_out(
    req: OptOutCreate, operator: uuid.UUID = Depends(require_operator), session: Session = Depends(get_session),
):
    session.execute(
        text("INSERT INTO contact_opt_out (id, tenant_id, email, reason, created_by_user_id)"
             " VALUES (:i, current_setting('pulse.tenant_id')::uuid, :e, :r, :u)"
             " ON CONFLICT (tenant_id, email) DO NOTHING"),
        {"i": uuid.uuid4(), "e": req.email, "r": req.reason, "u": operator},
    )
    row = session.execute(text("SELECT id FROM contact_opt_out WHERE email = :e"), {"e": req.email}).one()
    audit.record(session, "opt_out_added", actor_user_id=operator, subject=req.email)
    return {"id": str(row[0]), "email": req.email}


@router.delete("/opt-outs/{opt_out_id}")
def remove_opt_out(
    opt_out_id: uuid.UUID, operator: uuid.UUID = Depends(require_operator), session: Session = Depends(get_session),
):
    email = session.execute(text("DELETE FROM contact_opt_out WHERE id = :i RETURNING email"), {"i": opt_out_id}).scalar()
    if email is None:
        raise HTTPException(status_code=404, detail="opt-out not found")
    audit.record(session, "opt_out_removed", actor_user_id=operator, subject=email)
    return {"removed": email}
