#!/usr/bin/env bash
# Bring up a local PostgreSQL 16 cluster for Pulse.
#
# Docker is not available in the sandbox this was built in, so this script runs
# Postgres natively from the distribution binaries. docker-compose.yml is the
# equivalent for environments that do have Docker.
#
# The two roles matter and are not interchangeable:
#   pulse      - owner/superuser, runs migrations, owns the tables
#   pulse_app  - the application role: NOSUPERUSER NOBYPASSRLS
#
# If the application connected as the owner, row-level security would be
# silently bypassed and the isolation tests would pass for the wrong reason.
# FORCE ROW LEVEL SECURITY in migration 0002 closes that door as well, but the
# separate role is the primary control.
set -euo pipefail

PGBIN="${PGBIN:-/usr/lib/postgresql/16/bin}"
PGDATA="${PGDATA:-$HOME/.pgdata}"
PGLOG="${PGLOG:-$HOME/.pglog/pg.log}"
PGPORT="${PGPORT:-5432}"
PGSOCK="${PGSOCK:-/tmp}"

mkdir -p "$(dirname "$PGLOG")"

if [ ! -s "$PGDATA/PG_VERSION" ]; then
  echo "==> initdb $PGDATA"
  mkdir -p "$PGDATA"
  "$PGBIN/initdb" -D "$PGDATA" -U pulse --auth=trust -E UTF8 >/dev/null
fi

if ! "$PGBIN/pg_ctl" -D "$PGDATA" status >/dev/null 2>&1; then
  echo "==> starting postgres on :$PGPORT"
  "$PGBIN/pg_ctl" -D "$PGDATA" -l "$PGLOG" -o "-p $PGPORT -k $PGSOCK" start
  sleep 2
else
  echo "==> postgres already running"
fi

echo "==> ensuring roles and database"
psql -h "$PGSOCK" -p "$PGPORT" -U pulse -d postgres -v ON_ERROR_STOP=1 <<'SQL'
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pulse_app') THEN
    CREATE ROLE pulse_app LOGIN PASSWORD 'pulse_app'
      NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
  END IF;
END $$;
SQL

if ! psql -h "$PGSOCK" -p "$PGPORT" -U pulse -d postgres -tAc \
     "SELECT 1 FROM pg_database WHERE datname='pulse'" | grep -q 1; then
  psql -h "$PGSOCK" -p "$PGPORT" -U pulse -d postgres -v ON_ERROR_STOP=1 \
       -c "CREATE DATABASE pulse OWNER pulse"
fi

psql -h "$PGSOCK" -p "$PGPORT" -U pulse -d pulse -v ON_ERROR_STOP=1 <<'SQL'
GRANT USAGE ON SCHEMA public TO pulse_app;
ALTER DEFAULT PRIVILEGES FOR ROLE pulse IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO pulse_app;
ALTER DEFAULT PRIVILEGES FOR ROLE pulse IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO pulse_app;
SQL

echo "==> ready"
psql -h "$PGSOCK" -p "$PGPORT" -U pulse -d pulse -tAc "select 'pulse db ok: ' || version()"
