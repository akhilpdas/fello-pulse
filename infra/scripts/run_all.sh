#!/usr/bin/env bash
# One command from an empty database to a running, scored, populated system (SC-014).
#
#   bash infra/scripts/run_all.sh            # build everything, print how to open the UI
#   SERVE=1 bash infra/scripts/run_all.sh    # ...then serve the API on :8000
#
# Stages: postgres -> python env -> migrate -> generate -> bootstrap tenants ->
# ingest -> train -> one autonomous cycle -> print the sign-in details for the UI.
# Every stage is idempotent, so re-running on a populated database is safe.
#
# Env: PULSE_DB_NAME (default pulse; use another name to build beside your data),
#      PGBIN (default: Homebrew postgresql@16, else /usr/lib/postgresql/16/bin),
#      FORCE_REGENERATE=1 to rebuild the simulated feeds.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
export PULSE_DB_NAME="${PULSE_DB_NAME:-pulse}"
export PGBIN="${PGBIN:-$( [ -d /opt/homebrew/opt/postgresql@16/bin ] && echo /opt/homebrew/opt/postgresql@16/bin || echo /usr/lib/postgresql/16/bin )}"
export PGTZ=UTC
export PULSE_DATABASE_URL_OWNER="postgresql+psycopg://pulse@/${PULSE_DB_NAME}?host=${PGSOCK:-/tmp}&port=${PGPORT:-5432}"
export PULSE_DATABASE_URL_APP="postgresql+psycopg://pulse_app:pulse_app@/${PULSE_DB_NAME}?host=${PGSOCK:-/tmp}&port=${PGPORT:-5432}"
step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
t0=$(date +%s)

step "1/8 postgres + roles + database '$PULSE_DB_NAME'"
bash infra/scripts/pg_bootstrap.sh

step "2/8 python environment"
cd backend
[ -d .venv ] || python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -e ".[dev]"

step "3/8 migrate (tables, row-level security, roles)"
python3 -m alembic -c alembic.ini upgrade head

step "4/8 generate the simulated estate (seed 20261015)"
cd "$ROOT"
if [ ! -f data/feeds/northwind/tenant.json ] || [ "${FORCE_REGENERATE:-0}" = 1 ]; then
  python3 generator/main.py --seed 20261015
else
  echo "feeds already present (FORCE_REGENERATE=1 to rebuild)"
fi

cd backend
step "5/8 bootstrap tenants, users and accounts"
# Demo sign-in password: generated once per database name, kept in a git-ignored local file (0600) so a
# rebuild reuses it, and never committed. Only users that have no password get it; set PULSE_DEMO_PASSWORD
# yourself to choose one.
CRED_FILE="$ROOT/.demo-credentials.$PULSE_DB_NAME"
if [ -z "${PULSE_DEMO_PASSWORD:-}" ]; then
  [ -f "$CRED_FILE" ] || { umask 077; python3 -c 'import secrets; print(secrets.token_urlsafe(12))' > "$CRED_FILE"; }
  PULSE_DEMO_PASSWORD="$(cat "$CRED_FILE")"
fi
export PULSE_DEMO_PASSWORD
python3 -m pulse.cli bootstrap

step "6/8 ingest"
python3 -m pulse.cli ingest

step "7/8 train, evaluate, gate on the baseline, promote"
python3 -m pulse.ml.pipeline | tail -4

step "8/8 one autonomous cycle (score -> detect -> draft -> record)"
python3 -m pulse.cli cycle

step "ready in $(( $(date +%s) - t0 ))s"
echo
echo "Sign in at http://localhost:5173  (workspace = the tenant name; the password is the same for every demo user)"
psql -h "${PGSOCK:-/tmp}" -p "${PGPORT:-5432}" -U pulse -d "$PULSE_DB_NAME" -Atc \
  "SELECT format('  workspace %-10s operator %s', t.slug, u.email)
   FROM tenant t JOIN app_user u ON u.tenant_id = t.id AND u.role = 'operator'
   WHERE EXISTS (SELECT 1 FROM ingestion_watermark w WHERE w.tenant_id = t.id) ORDER BY t.slug"
echo "  password: $PULSE_DEMO_PASSWORD      (kept in $CRED_FILE, which is git-ignored)"
echo "  CSMs sign in the same way, e.g. csm01@northwind.example.com (they see only their own accounts)."
cat <<MSG

API:       cd backend && source .venv/bin/activate && uvicorn pulse.api.main:app --port 8000
UI:        cd frontend && npm install && npm run dev      (http://localhost:5173)
Worker:    cd backend && python3 -m pulse.cli serve --simulate-present      (the unattended agent)
MSG
