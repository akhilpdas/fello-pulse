"""Proof of constitutional principle IV: tenant isolation below the application.

The queries here are *deliberately wrong*. Every one of them omits the tenant
filter that application code would normally carry. That is the point: this suite
asserts that forgetting the filter is survivable, because the database refuses
the rows rather than returning them.

A suite that tested correctly-written queries would prove nothing — correct
queries return the right rows whether or not RLS exists.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from pulse.db.session import elevated_session, tenant_session

pytestmark = pytest.mark.isolation


def test_unfiltered_select_returns_no_other_tenant_rows(two_tenants, scoped_tables):
    a, b = two_tenants
    with tenant_session(a["tenant_id"]) as s:
        for table in scoped_tables:
            rows = s.execute(text(f"SELECT tenant_id FROM {table}")).scalars().all()
            assert rows, f"{table} returned nothing for its own tenant — fixture gap"
            leaked = [r for r in rows if r is not None and str(r) != str(a["tenant_id"])]
            assert not leaked, f"{table} leaked rows from another tenant: {leaked[:3]}"


def test_every_scoped_table_is_visible_to_its_own_tenant(two_tenants, scoped_tables):
    """Isolation that hides a tenant's own data is a different bug, not a fix."""
    a, b = two_tenants
    for tenant in (a, b):
        with tenant_session(tenant["tenant_id"]) as s:
            for table in scoped_tables:
                n = s.execute(text(f"SELECT count(*) FROM {table}")).scalar()
                assert n >= 1, f"{tenant['slug']} cannot see its own {table}"


def test_targeting_another_tenants_primary_key_returns_nothing(two_tenants):
    """Knowing the exact id of another tenant's row must not help."""
    a, b = two_tenants
    with tenant_session(a["tenant_id"]) as s:
        for table, key in (
            ("account", b["account_id"]),
            ("score", b["score_id"]),
            ("feature_snapshot", b["snapshot_id"]),
            ("app_user", b["user_id"]),
            ("agent_run", b["run_id"]),
        ):
            got = s.execute(
                text(f"SELECT count(*) FROM {table} WHERE id = :i"), {"i": key}
            ).scalar()
            assert got == 0, f"{table}: tenant A read tenant B's row by id"


def test_join_across_tables_cannot_widen_visibility(two_tenants):
    """A join is the classic way a scope gets lost. It must not reach across."""
    a, b = two_tenants
    with tenant_session(a["tenant_id"]) as s:
        rows = s.execute(
            text(
                "SELECT s.id FROM score s"
                " JOIN account acc ON acc.id = s.account_id"
                " JOIN feature_snapshot f ON f.id = s.feature_snapshot_id"
            )
        ).scalars().all()
        assert len(rows) == 1 and str(rows[0]) == str(a["score_id"])


def test_cannot_write_a_row_belonging_to_another_tenant(two_tenants):
    """WITH CHECK, not just USING.

    Without a WITH CHECK clause a tenant could insert rows stamped with another
    tenant's id: invisible to the writer afterwards, but corrupting the victim's
    data. Read isolation alone is only half the control.
    """
    a, b = two_tenants
    with pytest.raises(Exception) as exc, tenant_session(a["tenant_id"]) as s:
        s.execute(
            text(
                "INSERT INTO suppression (id, tenant_id, account_id, reason, created_at)"
                " VALUES (gen_random_uuid(), :t, :acc, 'injected', now())"
            ),
            {"t": b["tenant_id"], "acc": b["account_id"]},
        )
    assert "policy" in str(exc.value).lower() or "violates" in str(exc.value).lower()


def test_cannot_update_another_tenants_row_even_unfiltered(two_tenants):
    """A blanket UPDATE must touch only the caller's own rows."""
    a, b = two_tenants
    with tenant_session(a["tenant_id"]) as s:
        result = s.execute(text("UPDATE account SET name = 'rewritten'"))
        assert result.rowcount == 1, "an unfiltered UPDATE reached beyond one tenant"
    with tenant_session(b["tenant_id"]) as s:
        name = s.execute(
            text("SELECT name FROM account WHERE id = :i"), {"i": b["account_id"]}
        ).scalar()
        assert name != "rewritten", "tenant B's row was modified by tenant A"


def test_cannot_delete_another_tenants_rows(two_tenants):
    a, b = two_tenants
    with tenant_session(a["tenant_id"]) as s:
        result = s.execute(text("DELETE FROM feedback"))
        assert result.rowcount == 1
    with tenant_session(b["tenant_id"]) as s:
        assert s.execute(text("SELECT count(*) FROM feedback")).scalar() == 1


def test_no_claim_means_no_rows(two_tenants, scoped_tables):
    """An unset claim must fail closed.

    This is why the policy wraps the setting in NULLIF before casting: unset and
    blank both become NULL, NULL comparison filters everything out, and a bug
    that forgets to set the claim shows up as an empty screen rather than as
    somebody else's data.
    """
    from sqlalchemy.orm import sessionmaker

    from pulse.db.session import _engine

    factory = sessionmaker(bind=_engine("app"), future=True)
    s = factory()
    try:
        s.begin()
        for table in scoped_tables:
            n = s.execute(text(f"SELECT count(*) FROM {table}")).scalar()
            assert n == 0, f"{table} returned rows with no tenant claim set"
    finally:
        s.rollback()
        s.close()


def test_elevated_session_can_read_across_tenants(two_tenants):
    """The deliberate escape hatch works — and is a separate role, by design.

    Training needs cross-tenant reads. The point of this test is not that the
    hatch exists but that it is reached only through a differently-named session
    backed by a different database role, so its use is visible at every call
    site rather than hidden behind a boolean.
    """
    a, b = two_tenants
    with elevated_session() as s:
        ids = {
            str(r) for r in s.execute(text("SELECT DISTINCT tenant_id FROM score")).scalars()
        }
    assert {str(a["tenant_id"]), str(b["tenant_id"])} <= ids
