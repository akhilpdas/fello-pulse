"""Database sessions, and the tenant claim that row-level security reads.

Three entry points, and which one you use is a security decision:

``tenant_session(tenant_id)``
    The normal path. Connects as ``pulse_app`` (NOBYPASSRLS), opens a
    transaction, and sets the tenant claim with ``set_config(..., is_local =>
    true)`` so the claim lives and dies with that transaction. Everything a
    request touches goes through here.

``elevated_session()``
    Connects as ``pulse_trainer`` (BYPASSRLS). Cross-tenant model training only.
    A separate *database role* rather than a flag, so "this code reads across
    tenants" is visible in the connection string and greppable at review time.

``owner_session()``
    The schema owner. Migrations and test fixtures. Never serves a request.

Two implementation details worth stating:

*Why ``set_config`` and not ``SET LOCAL``.* PostgreSQL's ``SET`` takes a literal,
not a bind parameter, so ``SET LOCAL pulse.tenant_id = '{tenant_id}'`` would mean
interpolating a value into SQL — and the one value you least want to interpolate
is the one the entire isolation model depends on. ``set_config(key, value,
true)`` is an ordinary function call that takes a real bind parameter.

*Why transaction-scoped and not session-scoped.* ``is_local => true`` ties the
claim to the transaction. When the connection returns to the pool the claim is
already gone, so the next request cannot inherit the previous tenant's identity.
A session-scoped ``SET`` would survive on the pooled connection, which is how a
cross-tenant read happens in a system that otherwise looks correct.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from pulse.config import get_settings

_engines: dict[str, Engine] = {}

TENANT_CLAIM = "pulse.tenant_id"


def _engine(role: str) -> Engine:
    if role not in _engines:
        s = get_settings()
        url = {
            "app": s.database_url_app,
            "owner": s.database_url_owner,
            "trainer": s.database_url_app.replace(
                "pulse_app:pulse_app", "pulse_trainer:pulse_trainer"
            ),
        }[role]
        _engines[role] = create_engine(
            url, echo=s.echo_sql, pool_pre_ping=True, pool_size=s.pool_size, future=True
        )
    return _engines[role]


def dispose_engines() -> None:
    for e in _engines.values():
        e.dispose()
    _engines.clear()


@contextmanager
def tenant_session(tenant_id: uuid.UUID | str) -> Iterator[Session]:
    """A transaction scoped to one tenant. The only path that serves requests."""
    factory = sessionmaker(bind=_engine("app"), expire_on_commit=False, future=True)
    session = factory()
    try:
        session.begin()
        session.execute(
            text("SELECT set_config(:k, :v, true)"),
            {"k": TENANT_CLAIM, "v": str(tenant_id)},
        )
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def public_session() -> Iterator[Session]:
    """The application role with **no** tenant claim: it can read only the global ``tenant`` table
    (workspace slug -> id, needed before anyone is signed in). Every tenant-scoped table returns zero
    rows to it, because the row-level-security claim is NULL -- it fails closed."""
    factory = sessionmaker(bind=_engine("app"), expire_on_commit=False, future=True)
    session = factory()
    try:
        session.begin()
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def elevated_session() -> Iterator[Session]:
    """Cross-tenant reads. Model training only — never a request.

    Named for what it does rather than what it connects as, so that a reviewer
    seeing this call site knows immediately that tenant boundaries do not apply
    here and can ask whether that is justified.
    """
    factory = sessionmaker(bind=_engine("trainer"), expire_on_commit=False, future=True)
    session = factory()
    try:
        session.begin()
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def owner_session() -> Iterator[Session]:
    """Schema owner. Migrations and test fixtures, plus worker infrastructure
    (``work_lease``) that is schema-global and -- like migrations and
    fixtures -- never serves a request. See ``pulse/agent/lease.py``."""
    factory = sessionmaker(bind=_engine("owner"), expire_on_commit=False, future=True)
    session = factory()
    try:
        session.begin()
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def current_claim(session: Session) -> str | None:
    """What tenant does the database think this transaction is? For diagnostics."""
    return session.execute(
        text("SELECT NULLIF(current_setting(:k, true), '')"), {"k": TENANT_CLAIM}
    ).scalar()
