#!/usr/bin/env bash
# One command from an empty database to a running, scored, populated system (SC-014).
#
#   bash infra/scripts/run_all.sh            # build everything, print how to open the UI
#   SERVE=1 bash infra/scripts/run_all.sh    # ...then serve the API on :8000
#
# Stages: postgres -> python env -> migrate -> generate -> bootstrap tenants ->
# ingest -> train -> one autonomous cycle -> print tenant/operator ids for the UI.
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
python3 -m pulse.cli bootstrap

step "6/8 ingest"
python3 -m pulse.cli ingest

step "7/8 train, evaluate, gate on the baseline, promote"
python3 -m pulse.ml.pipeline | tail -4

step "8/8 one autonomous cycle (score -> detect -> draft -> record)"
python3 -m pulse.cli cycle

step "ready in $(( $(date +%s) - t0 ))s"
psql -h "${PGSOCK:-/tmp}" -p "${PGPORT:-5432}" -U pulse -d "$PULSE_DB_NAME" -Atc \
  "SELECT format('%-10s tenant id: %s   operator user id: %s', t.slug, t.id, u.id)
   FROM tenant t JOIN app_user u ON u.tenant_id = t.id AND u.role = 'operator'
   WHERE EXISTS (SELECT 1 FROM ingestion_watermark w WHERE w.tenant_id = t.id) ORDER BY t.slug"
cat <<MSG

API:       cd backend && source .venv/bin/activate && uvicorn pulse.api.main:app --port 8000
UI:        cd frontend && npm install && npm run dev      (http://localhost:5173)
In the UI, paste a tenant id and an operator user id from above.
MSG
if [ "${SERVE:-0}" = 1 ]; then
  exec uvicorn pulse.api.main:app --port 8000
fi
