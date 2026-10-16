"""Request-scoped dependencies. Tenant, user and role come from a verified session
(``get_principal``) and nowhere else; the tenant claim that row-level security enforces is
derived from it. Nothing a caller asserts in a header, query or body is trusted for identity.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from pulse.agent.transport import Transport, select_transport
from pulse.auth import audit
from pulse.auth.principal import Principal
from pulse.auth.sessions import resolve_session
from pulse.config import Clock, SystemClock, get_settings
from pulse.db.session import tenant_session

SESSION_COOKIE = "pulse_session"


def get_clock() -> Clock:
    return SystemClock()


def session_token(request: Request) -> str | None:
    """The credential, from a bearer header (API clients) or the session cookie (the web app)."""
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return request.cookies.get(SESSION_COOKIE) or None


def _authenticated_by_cookie(request: Request) -> bool:
    header = request.headers.get("authorization", "")
    return not header.lower().startswith("bearer ") and bool(request.cookies.get(SESSION_COOKIE))


def get_principal(request: Request, clock: Clock = Depends(get_clock)) -> Principal:
    """Who is calling, from a verified session only. 401 otherwise."""
    token = session_token(request)
    principal = resolve_session(token, now=clock.now()) if token else None
    if principal is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    # CSRF (R-5): the browser sends the cookie on any request to our origin, so a state-changing request
    # that relies on it alone must also carry a header a cross-site form cannot set. Bearer clients and
    # safe methods are exempt.
    if (
        request.method not in ("GET", "HEAD", "OPTIONS")
        and _authenticated_by_cookie(request)
        and not request.headers.get("x-requested-with")
    ):
        raise HTTPException(status_code=403, detail="missing X-Requested-With header")
    _flag_asserted_identity(request, principal)
    return principal


def _flag_asserted_identity(request: Request, principal: Principal) -> None:
    """Identity headers are never read for identity (FR-002). If a caller sends them anyway and they
    disagree with the session, that is worth knowing -- record it, in the caller's own tenant."""
    claimed_tenant = request.headers.get("x-tenant-id")
    claimed_user = request.headers.get("x-user-id")
    if (claimed_tenant and claimed_tenant != str(principal.tenant_id)) or (
        claimed_user and claimed_user != str(principal.user_id)
    ):
        audit.record_separately(
            principal.tenant_id, "tenant_mismatch", actor_user_id=principal.user_id,
            subject=f"{request.method} {request.url.path}",
            detail={"asserted_tenant": claimed_tenant, "asserted_user": claimed_user},
        )


def require_operator(request: Request, principal: Principal = Depends(get_principal)) -> uuid.UUID:
    """Operator-only routes (FR-004): enforced here, on the server, from the verified role."""
    if not principal.is_operator:
        audit.record_separately(
            principal.tenant_id, "forbidden", actor_user_id=principal.user_id,
            subject=f"{request.method} {request.url.path}",
        )
        raise HTTPException(status_code=403, detail="operator role required")
    return principal.user_id


def get_session(principal: Principal = Depends(get_principal)) -> Iterator[Session]:
    """The request's tenant-scoped, RLS-enforced transaction. The claim comes from the verified
    session and nothing else: a tenant id sent in a header, query or body is never read."""
    with tenant_session(principal.tenant_id) as s:
        yield s


def get_transport() -> Transport:
    """The deployment's mail transport (see ``select_transport``). Tests override this."""
    return select_transport(get_settings())


def get_artifacts_dir() -> Path:
    """Where the training pipeline writes model cards (pipeline.run's default)."""
    return Path("../artifacts")
