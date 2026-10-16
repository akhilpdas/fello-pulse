"""Operator-managed users and account ownership, within the operator's own tenant (FR-009).

Everything runs under the caller's tenant claim, so another tenant's users and accounts are simply not
visible (404). An operator cannot disable or demote themselves -- the simplest way to lock a tenant out of
its own administration -- and a password reset or a disable revokes that user's live sessions.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.orm import Session

from pulse.api.deps import get_principal, get_session, require_operator
from pulse.auth import audit
from pulse.auth.passwords import PasswordPolicyError, hash_password, validate_password
from pulse.auth.principal import Principal

router = APIRouter(prefix="/admin", dependencies=[Depends(require_operator)])

Role = Literal["csm", "operator"]


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str
    name: str
    role: Role
    password: str


class UserPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    role: Role | None = None
    disabled: bool | None = None
    password: str | None = None


class OwnerPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    owner_user_id: uuid.UUID | None


def _public(row) -> dict:
    return {"id": str(row["id"]), "email": row["email"], "name": row["name"], "role": row["role"],
            "disabled": row["disabled_at"] is not None}


def _check_password(password: str, email: str) -> str:
    try:
        validate_password(password, email)
    except PasswordPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return hash_password(password)


def _fetch(session: Session, user_id: uuid.UUID):
    row = session.execute(
        text("SELECT id, email, name, role, disabled_at FROM app_user WHERE id = :i"), {"i": user_id}
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="user not found")
    return row


@router.get("/users")
def list_users(session: Session = Depends(get_session)):
    rows = session.execute(
        text("SELECT id, email, name, role, disabled_at FROM app_user ORDER BY email")
    ).mappings().all()
    return [_public(r) for r in rows]


@router.post("/users", status_code=201)
def create_user(
    req: UserCreate, session: Session = Depends(get_session), principal: Principal = Depends(get_principal),
):
    email = req.email.strip()
    password_hash = _check_password(req.password, email)
    if session.execute(text("SELECT 1 FROM app_user WHERE lower(email) = lower(:e)"), {"e": email}).scalar():
        raise HTTPException(status_code=409, detail="a user with that email already exists")
    user_id = uuid.uuid4()
    session.execute(
        text(
            "INSERT INTO app_user (id, tenant_id, email, name, role, password_hash, password_changed_at)"
            " VALUES (:i, current_setting('pulse.tenant_id')::uuid, :e, :n, :r, :h, now())"
        ),
        {"i": user_id, "e": email, "n": req.name, "r": req.role, "h": password_hash},
    )
    audit.record(session, "user_created", actor_user_id=principal.user_id, subject=email,
                 detail={"role": req.role, "user_id": str(user_id)})
    return _public(_fetch(session, user_id))


@router.patch("/users/{user_id}")
def patch_user(
    user_id: uuid.UUID, req: UserPatch, session: Session = Depends(get_session),
    principal: Principal = Depends(get_principal),
):
    user = _fetch(session, user_id)
    if user_id == principal.user_id and (req.disabled is True or (req.role and req.role != "operator")):
        raise HTTPException(status_code=409, detail="you cannot disable or demote yourself")
    if req.name is not None:
        session.execute(text("UPDATE app_user SET name = :n WHERE id = :i"), {"n": req.name, "i": user_id})
    if req.role is not None and req.role != user["role"]:
        session.execute(text("UPDATE app_user SET role = :r WHERE id = :i"), {"r": req.role, "i": user_id})
        audit.record(session, "role_changed", actor_user_id=principal.user_id, subject=user["email"],
                     detail={"from": user["role"], "to": req.role})
    if req.disabled is not None and req.disabled != (user["disabled_at"] is not None):
        session.execute(
            text("UPDATE app_user SET disabled_at = CASE WHEN :d THEN now() END WHERE id = :i"),
            {"d": req.disabled, "i": user_id},
        )
        audit.record(session, "user_disabled" if req.disabled else "user_enabled",
                     actor_user_id=principal.user_id, subject=user["email"])
    revoke = req.disabled is True
    if req.password is not None:
        session.execute(
            text("UPDATE app_user SET password_hash = :h, password_changed_at = now() WHERE id = :i"),
            {"h": _check_password(req.password, user["email"]), "i": user_id},
        )
        audit.record(session, "password_reset", actor_user_id=principal.user_id, subject=user["email"])
        revoke = True
    if revoke:
        session.execute(
            text("UPDATE app_session SET revoked_at = now() WHERE user_id = :i AND revoked_at IS NULL"),
            {"i": user_id},
        )
    return _public(_fetch(session, user_id))


@router.get("/audit")
def get_audit(session: Session = Depends(get_session)):
    rows = session.execute(
        text("SELECT at, actor_kind, actor_user_id, event, subject, detail FROM audit_event"
             " ORDER BY at DESC, id LIMIT 200")
    ).mappings().all()
    return [{"at": r["at"].isoformat(), "actor_kind": r["actor_kind"],
             "actor_user_id": str(r["actor_user_id"]) if r["actor_user_id"] else None,
             "event": r["event"], "subject": r["subject"], "detail": r["detail"]} for r in rows]


@router.patch("/accounts/{account_id}")
def assign_owner(account_id: uuid.UUID, req: OwnerPatch, session: Session = Depends(get_session)):
    if session.execute(text("SELECT 1 FROM account WHERE id = :a"), {"a": account_id}).scalar() is None:
        raise HTTPException(status_code=404, detail="account not found")
    if req.owner_user_id is not None:
        _fetch(session, req.owner_user_id)  # 404 unless the user is in this tenant
    session.execute(
        text("UPDATE account SET owner_user_id = :o WHERE id = :a"), {"o": req.owner_user_id, "a": account_id}
    )
    return {"account_id": str(account_id), "owner_user_id": str(req.owner_user_id) if req.owner_user_id else None}
