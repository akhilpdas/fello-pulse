"""``infra/render/probe.sh``: can a hosting platform's database run this application? (spec 003, T020)

Render's documentation does not say whether its database user can create roles, and the migration needs two of them (one
with ``BYPASSRLS``, which normally needs a superuser). The probe answers in seconds against any URL, so the owner finds
out before building anything. Skipped where ``psql`` or a local Postgres is not available.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import text

from pulse.db.session import owner_session

PROBE = Path(__file__).resolve().parents[3] / "infra" / "render" / "probe.sh"
pytestmark = pytest.mark.skipif(shutil.which("psql") is None, reason="psql not installed")


def _url(user: str) -> str:
    return f"postgresql://{user}@/pulse_test?host=/tmp&port=5432"


def _probe(user: str):
    return subprocess.run(["bash", str(PROBE), _url(user)], capture_output=True, text=True, timeout=60)


@pytest.fixture
def roles():
    names = ("probe_createrole", "probe_plain")
    with owner_session() as s:
        for n in names:
            s.execute(text(f"DROP ROLE IF EXISTS {n}"))
        s.execute(text("CREATE ROLE probe_createrole LOGIN CREATEROLE NOSUPERUSER NOBYPASSRLS"))
        s.execute(text("CREATE ROLE probe_plain LOGIN NOSUPERUSER NOCREATEROLE NOBYPASSRLS"))
    yield
    with owner_session() as s:
        for n in names:
            s.execute(text(f"DROP ROLE IF EXISTS {n}"))


def test_a_superuser_database_works_as_it_is(roles):
    r = _probe("pulse")
    assert r.returncode == 0 and "GO" in r.stdout and "NEEDS-CHANGES" not in r.stdout, r.stdout + r.stderr


def test_a_user_that_can_create_roles_but_not_bypass_row_security_needs_changes(roles):
    r = _probe("probe_createrole")
    assert r.returncode == 2 and "NEEDS-CHANGES" in r.stdout, r.stdout + r.stderr


def test_a_user_that_cannot_create_roles_is_a_no_go_and_the_message_names_the_fallback(roles):
    r = _probe("probe_plain")
    assert r.returncode == 3 and "NO-GO" in r.stdout and "Railway" in r.stdout, r.stdout + r.stderr


def test_the_probe_leaves_nothing_behind(roles):
    _probe("pulse")
    with owner_session() as s:
        left = s.execute(text("SELECT count(*) FROM pg_roles WHERE rolname LIKE 'pulse_probe%'")).scalar()
    assert left == 0
