#!/usr/bin/env bash
# Browser end-to-end tests: a scratch copy of the demo database, the real API, the real UI, a real Chrome.
#   bash infra/scripts/e2e.sh        (or: cd frontend && npm run e2e)
# Needs: Postgres running, the demo database built (run_all.sh), Google Chrome installed, the API/UI ports free.
# The demo database is never written to: the tests run against `pulse_e2e`, which is dropped afterwards.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PGBIN="${PGBIN:-/opt/homebrew/opt/postgresql@16/bin}"
PSQL=("$PGBIN/psql" -h "${PGSOCK:-/tmp}" -U pulse -d postgres -qAt)
cleanup() { "${PSQL[@]}" -c "DROP DATABASE IF EXISTS pulse_e2e WITH (FORCE)" >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup
"${PSQL[@]}" -c "CREATE DATABASE pulse_e2e TEMPLATE pulse"
export PULSE_DATABASE_URL_OWNER="postgresql+psycopg://pulse@/pulse_e2e?host=${PGSOCK:-/tmp}&port=${PGPORT:-5432}"
export PULSE_DATABASE_URL_APP="postgresql+psycopg://pulse_app:pulse_app@/pulse_e2e?host=${PGSOCK:-/tmp}&port=${PGPORT:-5432}"
export PULSE_E2E_PASSWORD="${PULSE_E2E_PASSWORD:-$(cat "$ROOT/.demo-credentials.pulse")}"
cd "$ROOT/frontend" && npx playwright test "$@"
