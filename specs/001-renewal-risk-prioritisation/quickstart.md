# Quickstart — empty database to a running, scored system (SC-014)

Prerequisites (macOS): Homebrew `postgresql@16`, Python 3.12+, Node 20+ (UI only).
Docker is not required.

## One command

```bash
bash infra/scripts/run_all.sh
```

Stages, each idempotent: Postgres cluster and roles → Python env → migrations
(tables, row-level security) → generate the simulated estate (seed 20261015) →
bootstrap tenants → ingest → train and gate on the heuristic baseline → one
autonomous cycle → print a tenant id and operator id per tenant.

Options: `PULSE_DB_NAME=other` builds a differently named database (the API then needs the matching `PULSE_DATABASE_URL_*`);
`FORCE_REGENERATE=1` rebuilds the feeds; `SERVE=1` serves the API when done.

## Open it (VS Code)

`Terminal ▸ Run Task…` — the tasks in `.vscode/tasks.json` are numbered:
**1. start Postgres** → **2. build demo data** → **3. run the demo (API + UI)**, then
**show demo tenant + user ids** and paste them into http://localhost:5173.
**RESET demo database** drops `pulse` if you want to start over.

**4. unattended worker** is the agent itself: `python3 -m pulse.cli serve --simulate-present`.
It ticks every 30 s and cycles each tenant when it is due (every 15 min), with nobody clicking
anything; watch new rows appear in the UI's **Run log**. (`--simulate-present` runs on the data's
present — its newest event — because the generated data is dated later than your wall clock.
Without the flag it uses the real clock, as a deployment would. To see it fire quickly:
`PULSE_CYCLE_INTERVAL_MINUTES=1`.) Or by hand:

```bash
# terminal 1 — API
cd backend && source .venv/bin/activate && uvicorn pulse.api.main:app --port 8000
# terminal 2 — UI
cd frontend && npm install && npm run dev        # http://localhost:5173
```

Paste a **tenant id** and **operator user id** (printed by `run_all.sh`) into the bar at
the top. Queue, Low confidence, Drafts (approve/reject/edit) and Run log are the four
views; click an account for drivers, evidence down to source payloads, and score diff.

## Two databases, on purpose

- **`pulse`** — the demo database. Built by `run_all.sh`; only the app and you touch it.
- **`pulse_test`** — used by the test suite, which seeds and deletes tenants and writes scores.
  Build it **once**: `PULSE_DB_NAME=pulse_test bash infra/scripts/run_all.sh`. The suite refuses to
  run (with that instruction) if it is missing, and ignores any database URL in your shell, so tests
  can never pollute the demo.

## Verify

```bash
cd backend && source .venv/bin/activate && python3 -m pytest -q      # backend (needs pulse_test, below)
cd frontend && npm test && npm run build                              # frontend
python3 -m pulse.openapi_export                                       # regenerate contracts/openapi.yaml
```

## Starting postgres by hand

`pg_ctl -D ~/.pgdata start` (or re-run `infra/scripts/pg_bootstrap.sh`). Set `PGTZ=UTC`
to silence the `TZ` warning noted in `HANDOFF.md`.
