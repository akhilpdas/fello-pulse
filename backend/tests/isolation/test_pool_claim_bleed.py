"""The claim must not survive a connection's return to the pool.

This is the failure mode that makes an otherwise-correct RLS implementation leak:
the policy is right, the claim is set, but the claim was set at *session* scope,
so the pooled connection carries the previous request's tenant identity into the
next request. Under load, a request occasionally sees another tenant's data and
nothing in the logs looks wrong.

``set_config(..., is_local => true)`` ties the claim to the transaction, so the
connection is already clean when it goes back to the pool.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from pulse.db.session import _engine, current_claim, tenant_session

pytestmark = pytest.mark.isolation


def test_claim_does_not_persist_on_a_reused_connection(two_tenants):
    a, b = two_tenants
    engine = _engine("app")
    engine.dispose()  # force a small, reused pool for this test

    with tenant_session(a["tenant_id"]) as s:
        assert current_claim(s) == str(a["tenant_id"])
        assert s.execute(text("SELECT count(*) FROM account")).scalar() == 1

    # Same pooled connection, no claim set: must see nothing at all.
    factory = sessionmaker(bind=engine, future=True)
    s2 = factory()
    try:
        s2.begin()
        assert current_claim(s2) is None, "tenant A's claim survived into a new transaction"
        assert s2.execute(text("SELECT count(*) FROM account")).scalar() == 0
    finally:
        s2.rollback()
        s2.close()

    # And a second tenant on that same connection sees only its own.
    with tenant_session(b["tenant_id"]) as s3:
        rows = s3.execute(text("SELECT tenant_id FROM account")).scalars().all()
        assert [str(r) for r in rows] == [str(b["tenant_id"])]


def test_interleaved_tenant_sessions_do_not_contaminate(two_tenants):
    """Alternate tenants repeatedly; each must stay in its own world."""
    a, b = two_tenants
    for _ in range(6):
        for tenant in (a, b):
            with tenant_session(tenant["tenant_id"]) as s:
                rows = s.execute(text("SELECT tenant_id FROM score")).scalars().all()
                assert [str(r) for r in rows] == [str(tenant["tenant_id"])]


def test_claim_is_cleared_after_a_failed_transaction(two_tenants):
    """A rollback must not leave the claim behind either."""
    a, b = two_tenants
    with pytest.raises(Exception), tenant_session(a["tenant_id"]) as s:
        s.execute(text("SELECT 1 FROM does_not_exist"))

    factory = sessionmaker(bind=_engine("app"), future=True)
    s2 = factory()
    try:
        s2.begin()
        assert current_claim(s2) is None
    finally:
        s2.rollback()
        s2.close()
