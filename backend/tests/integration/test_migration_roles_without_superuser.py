"""T023: Pulse must migrate and load its seed on a managed Postgres whose login can create roles but is neither a
superuser nor allowed ``BYPASSRLS`` (Render's free database: "Only roles with the BYPASSRLS attribute may create roles
with the BYPASSRLS attribute").

Roles live in the *cluster*, not the database, and the shared test cluster already has ``pulse_app``/``pulse_trainer``,
so this runs a throwaway Postgres of its own. Names the production changes that make it fail: migrations 0002/0005
skipping the trainer role when the owner cannot create it, and ``pulse.seed.rls_lifted`` for the load.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import psycopg
import pytest

BACKEND = Path(__file__).resolve().parents[2]
BIN_CANDIDATES = ["/opt/homebrew/opt/postgresql@16/bin", "/usr/lib/postgresql/16/bin", "/usr/lib/postgresql/15/bin",
                  "/usr/lib/postgresql/17/bin"]


def _bin(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for d in BIN_CANDIDATES:
        if (Path(d) / name).exists():
            return str(Path(d) / name)
    return None


@pytest.fixture(scope="module")
def managed_pg():
    initdb, pg_ctl = _bin("initdb"), _bin("pg_ctl")
    if not (initdb and pg_ctl):
        pytest.skip("initdb/pg_ctl are not installed; cannot start a throwaway cluster")
    root = Path(tempfile.mkdtemp(prefix="pgm", dir="/tmp"))
    data = root / "data"
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    subprocess.run([initdb, "-D", str(data), "-U", "postgres", "--auth=trust", "-E", "UTF8"], check=True,
                   capture_output=True)
    subprocess.run([pg_ctl, "-D", str(data), "-w", "-l", str(root / "log"), "-o",
                    f"-p {port} -c listen_addresses=127.0.0.1 -c unix_socket_directories={root}", "start"],
                   check=True, capture_output=True)
    try:
        with psycopg.connect(f"postgresql://postgres@127.0.0.1:{port}/postgres", autocommit=True) as c:
            c.execute("CREATE ROLE render_user LOGIN PASSWORD 'x' CREATEROLE NOSUPERUSER NOBYPASSRLS")
            c.execute("CREATE DATABASE pulse OWNER render_user")
        yield {"port": port, "owner_url": f"postgresql+psycopg://render_user:x@127.0.0.1:{port}/pulse",
               "libpq": f"postgresql://render_user:x@127.0.0.1:{port}/pulse",
               "admin": f"postgresql://postgres@127.0.0.1:{port}/pulse"}
    finally:
        subprocess.run([pg_ctl, "-D", str(data), "-m", "immediate", "stop"], capture_output=True)
        shutil.rmtree(root, ignore_errors=True)


@pytest.fixture(scope="module")
def migrated(managed_pg):
    env = {**os.environ, "PULSE_DATABASE_URL_OWNER": managed_pg["owner_url"]}
    run = subprocess.run([sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"], cwd=BACKEND,
                         env=env, capture_output=True, text=True)
    return run


def test_migrations_run_for_a_login_that_cannot_create_a_bypassrls_role(migrated):
    assert migrated.returncode == 0, migrated.stderr[-1500:]


def test_the_request_role_still_cannot_bypass_row_level_security_and_the_trainer_role_is_simply_absent(managed_pg, migrated):
    assert migrated.returncode == 0, migrated.stderr[-600:]
    with psycopg.connect(managed_pg["admin"]) as c:
        roles = dict(c.execute("SELECT rolname, rolbypassrls FROM pg_roles WHERE rolname IN ('pulse_app','pulse_trainer')").fetchall())
        assert roles == {"pulse_app": False}
        forced = c.execute("SELECT count(*) FROM pg_class WHERE relname = 'account' AND relforcerowsecurity").fetchone()[0]
        assert forced == 1                                            # isolation is not weakened to make the migration pass
        c.execute("SET ROLE pulse_app")
        assert c.execute("SELECT count(*) FROM account").fetchone()[0] == 0   # has SELECT, sees nothing without a tenant claim


def test_the_loader_can_see_and_write_tenant_rows_only_while_row_level_security_is_lifted_and_restores_it(managed_pg, migrated):
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    from pulse.seed import needs_rls_lift, rls_lifted

    assert migrated.returncode == 0
    engine = create_engine(managed_pg["owner_url"])
    session = sessionmaker(bind=engine, future=True)()
    try:
        assert needs_rls_lift(session) is True                        # not a superuser, no BYPASSRLS
        session.commit()
        with psycopg.connect(managed_pg["admin"], autocommit=True) as admin:
            admin.execute("INSERT INTO tenant (id, slug, name) VALUES ('11111111-1111-1111-1111-111111111111', 't1', 'T1')")
            admin.execute("INSERT INTO account (id, tenant_id, external_ref, name, signup_date) VALUES "
                          "('22222222-2222-2222-2222-222222222222', '11111111-1111-1111-1111-111111111111', 'a1', 'A1', '2024-01-01')")
        assert session.execute(text("SELECT count(*) FROM account")).scalar() == 0        # forced RLS hides it from the owner
        session.commit()
        with rls_lifted(session):
            assert session.execute(text("SELECT count(*) FROM account")).scalar() == 1
            session.commit()
        assert session.execute(text("SELECT count(*) FROM account")).scalar() == 0        # restored
        with psycopg.connect(managed_pg["admin"]) as admin:
            assert admin.execute("SELECT count(*) FROM pg_class WHERE relrowsecurity AND NOT relforcerowsecurity "
                                 "AND relname IN ('account','action','score')").fetchone()[0] == 0
    finally:
        session.close()
        engine.dispose()
