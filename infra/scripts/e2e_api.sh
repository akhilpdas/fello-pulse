#!/usr/bin/env bash
# The API as the browser tests see it (started by Playwright; the database URLs come from e2e.sh's environment).
cd "$(dirname "${BASH_SOURCE[0]}")/../../backend" && source .venv/bin/activate
PGTZ=UTC exec uvicorn pulse.api.main:app --host 127.0.0.1 --port "${PULSE_E2E_API_PORT:-8100}"
