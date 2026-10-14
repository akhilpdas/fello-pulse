"""The posture itself: roles, flags and policies.

These assertions are about the configuration rather than about behaviour. They
exist because every behavioural isolation test above would still pass if someone
later ran the application as the owner, or added a table and forgot its policy —
the tests would simply not be exercising the new surface. This file fails
loudly in both cases.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from pulse.db.models import TENANT_SCOPED_TABLES
from pulse.db.session import owner_session

pytestmark = pytest.mark.isolation


def test_application_role_cannot_bypass_rls():
    """If pulse_app ever gains BYPASSRLS, every other test here becomes theatre."""
    with owner_session() as s:
        row = s.execute(
            text("SELECT rolbypassrls, rolsuper FROM pg_roles WHERE rolname = 'pulse_app'")
        ).one()
    assert row.rolbypassrls is False, "pulse_app can bypass row-level security"
    assert row.rolsuper is False, "pulse_app is a superuser"


def test_elevated_role_is_the_only_one_that_bypasses():
    with owner_session() as s:
        rows = s.execute(
            text(
                "SELECT rolname FROM pg_roles"
                " WHERE rolbypassrls AND rolname LIKE 'pulse%'"
            )
        ).scalars().all()
    assert set(rows) == {"pulse", "pulse_trainer"}, (
        f"unexpected set of bypass-capable roles: {rows}"
    )


def test_every_tenant_scoped_table_has_rls_enabled_and_forced():
    """FORCE matters as much as ENABLE.

    Without FORCE the table owner is exempt from its own policies. A test suite
    run as the owner would then pass while proving nothing, which is a worse
    outcome than having no test at all.
    """
    with owner_session() as s:
        rows = s.execute(
            text(
                "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class"
                " WHERE relkind = 'r' AND relnamespace = 'public'::regnamespace"
            )
        ).all()
    by_name = {r.relname: r for r in rows}
    for table in TENANT_SCOPED_TABLES:
        assert table in by_name, f"{table} is missing from the database"
        assert by_name[table].relrowsecurity, f"{table} has RLS disabled"
        assert by_name[table].relforcerowsecurity, f"{table} does not FORCE RLS"


def test_no_tenant_scoped_table_lacks_a_policy():
    """Drift guard.

    A new table carrying tenant data but no policy is the realistic way this
    control decays: the migration that adds the table is reviewed, the policy is
    forgotten, and nothing fails until a customer notices.
    """
    with owner_session() as s:
        policied = set(
            s.execute(
                text("SELECT DISTINCT tablename FROM pg_policies WHERE schemaname = 'public'")
            ).scalars()
        )
    missing = set(TENANT_SCOPED_TABLES) - policied
    assert not missing, f"tenant-scoped tables with no RLS policy: {sorted(missing)}"


def test_no_unclassified_table_exists():
    """Every table is either tenant-scoped or deliberately global.

    Forces a decision at the moment a table is added rather than leaving the
    question open until someone wonders why a table has no policy.
    """
    from pulse.db.models import GLOBAL_TABLES

    with owner_session() as s:
        tables = set(
            s.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                    " AND tablename <> 'alembic_version'"
                )
            ).scalars()
        )
    unclassified = tables - set(TENANT_SCOPED_TABLES) - set(GLOBAL_TABLES)
    assert not unclassified, (
        f"tables classified as neither tenant-scoped nor global: {sorted(unclassified)}"
    )
