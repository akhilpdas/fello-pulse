"""Sign in, who am I, sign out (FR-001, FR-007, FR-008).

Every failure -- wrong password, unknown email, unknown workspace, disabled user -- returns the same
401 body, and an unknown identity still pays for a password hash, so neither the response nor its
timing reveals which part was wrong.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from pulse.api.deps import SESSION_COOKIE, get_clock, get_principal, session_token
from pulse.auth import audit
from pulse.auth.limiter import LoginLimiter, PgLoginLimiter
from pulse.auth.passwords import verify_password
from pulse.auth.principal import Principal
from pulse.auth.sessions import create_session, revoke_session
from pulse.config import Clock, get_settings
from pulse.db.session import public_session, tenant_session

router = APIRouter()

_INVALID = HTTPException(status_code=401, detail="invalid credentials")
_limiter: LoginLimiter | PgLoginLimiter | None = None


def get_limiter() -> LoginLimiter | PgLoginLimiter:
    global _limiter
    if _limiter is None:
        s = get_settings()
        _limiter = PgLoginLimiter(s.login_max_failures, s.login_window_seconds)  # shared across API instances
    return _limiter


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str
    email: str
    password: str


@router.post("/auth/login")
def login(
    req: LoginRequest, request: Request, response: Response,
    clock: Clock = Depends(get_clock), limiter: LoginLimiter | PgLoginLimiter = Depends(get_limiter),
):
    now = clock.now()
    key = (request.client.host if request.client else "unknown", req.workspace.strip().lower(), req.email.strip().lower())
    if not limiter.allowed(key, now=now):
        raise HTTPException(status_code=429, detail="too many attempts; try again later")

    with public_session() as s:
        tenant = s.execute(
            text("SELECT id, slug FROM tenant WHERE lower(slug) = lower(:s)"), {"s": req.workspace.strip()}
        ).one_or_none()
    user = None
    if tenant is not None:
        with tenant_session(tenant.id) as s:
            user = s.execute(
                text("SELECT id, name, email, role, password_hash, disabled_at FROM app_user"
                     " WHERE lower(email) = lower(:e)"), {"e": req.email.strip()},
            ).one_or_none()
    usable = user is not None and user.disabled_at is None and user.password_hash is not None
    ok = verify_password(req.password, user.password_hash if usable else None)
    if not (ok and usable):
        limiter.record_failure(key, now=now)
        if tenant is not None:  # an unknown workspace has no tenant trail to write to
            audit.record_separately(tenant.id, "login_failed", actor_kind="anonymous",
                                    subject=req.email.strip())
        raise _INVALID
    limiter.record_success(key)

    settings = get_settings()
    ttl = timedelta(hours=settings.session_hours)
    token = create_session(tenant.id, user.id, now=now, ttl=ttl, user_agent=request.headers.get("user-agent"))
    audit.record_separately(tenant.id, "login_ok", actor_user_id=user.id, subject=user.email)
    response.set_cookie(
        SESSION_COOKIE, token, max_age=int(ttl.total_seconds()), httponly=True, samesite="strict",
        secure=settings.cookie_secure, path="/",
    )
    return {
        "user": {"id": str(user.id), "name": user.name, "role": user.role, "email": user.email},
        "tenant": {"id": str(tenant.id), "slug": tenant.slug},
    }


@router.get("/auth/me")
def me(principal: Principal = Depends(get_principal)):
    with tenant_session(principal.tenant_id) as s:
        user = s.execute(text("SELECT id, name, email, role FROM app_user WHERE id = :i"),
                         {"i": principal.user_id}).one()
    with public_session() as s:
        slug = s.execute(text("SELECT slug FROM tenant WHERE id = :i"), {"i": principal.tenant_id}).scalar()
    return {
        "user": {"id": str(user.id), "name": user.name, "role": user.role, "email": user.email},
        "tenant": {"id": str(principal.tenant_id), "slug": slug},
    }


@router.post("/auth/logout")
def logout(request: Request, response: Response, principal: Principal = Depends(get_principal)):
    token = session_token(request)
    if token:
        revoke_session(token)
    audit.record_separately(principal.tenant_id, "logout", actor_user_id=principal.user_id)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}
