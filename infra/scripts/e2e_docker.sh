#!/usr/bin/env bash
# The browser suite against the running container stack (docker compose up -d, then bootstrap-demo).
#   PULSE_E2E_PASSWORD=<the password bootstrap-demo printed> bash infra/scripts/e2e_docker.sh
# It WRITES to that stack's database (feedback, a suppression, an operator setting, a new user, approved drafts) --
# fine for a throwaway stack, not for one you care about.
set -euo pipefail
: "${PULSE_E2E_PASSWORD:?set PULSE_E2E_PASSWORD to the password bootstrap-demo printed}"
cd "$(dirname "${BASH_SOURCE[0]}")/../../frontend"
E2E_BASE_URL="${E2E_BASE_URL:-http://127.0.0.1:5173}" npx playwright test "$@"
