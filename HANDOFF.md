# Handoff / Resume Notes

This file is the restart point if a session ends. It is updated at the end of every
phase. Read it first, then `specs/001-renewal-risk-prioritisation/tasks.md`.

## Where this lives

- **Durable copy**: `~/Documents/fello-pulse` on Akhil's MacBook (mirrored from the
  cloud sandbox after each phase).
- **Working copy**: `/home/claude/pulse` inside an ephemeral Anthropic cloud sandbox.
  This is reclaimed when the session ends — it is never the source of truth.
- GitHub is not linked to the Claude account, so nothing is pushed to a remote.

## Restarting the environment in a fresh session

```bash
# 1. deps
pip install --break-system-packages fastapi 'uvicorn[standard]' 'sqlalchemy>=2' alembic \
  'psycopg[binary]' 'pydantic>=2' pydantic-settings scikit-learn pandas numpy shap \
  pytest httpx orjson

# 2. postgres 16 (binaries are preinstalled at /usr/lib/postgresql/16/bin; docker is NOT available)
bash infra/scripts/pg_bootstrap.sh

# 3. verify
psql -h /tmp -p 5432 -U pulse -d pulse -c 'select 1'
```

Postgres facts for this sandbox:
- cluster data dir `/home/claude/.pgdata`, log `/home/claude/.pglog/pg.log`
- unix socket in `/tmp`, port 5432, trust auth
- owner/superuser role `pulse`; application role `pulse_app` (password `pulse_app`,
  **NOSUPERUSER NOBYPASSRLS** — this is load-bearing for the RLS isolation tests)
- database `pulse`

## Status

### Done
- Spec Kit scaffolded (`specify-cli` 1.2.1.dev0, `--integration claude`, sh scripts)
- `.specify/memory/constitution.md` — v1.0.0, five non-negotiables as enforceable
  principles with the test that proves each
- `specs/001-renewal-risk-prioritisation/spec.md` — problem restatement, six
  documented disagreements with the VP's request (D1–D6), eight open business
  questions with adopted assumptions (B1–B8), six user stories, edge cases, FR-001
  to FR-049, SC-001 to SC-014
- `.../clarifications.md` — Section A (open business questions, full reasoning),
  Section B (eleven resolved design decisions with rejected alternatives)
- `.../plan.md` — technical context, constitution gate (PASS), phase 0 research
  summary, project structure, sequencing, risk table
- `.../data-model.md` — 16 entities, keys, indexes, per-table RLS posture
- `.../contracts/ingestion.md` — five source contracts, normalised event vocabulary,
  twelve deliberate data pathologies mapped to the requirement each one tests
- `.../contracts/features.md` — ~40 features in six driver groups, absence rules,
  abstain rule
- `.../tasks.md` — 97 tasks, T001–T097, grouped by user story

### Next (in order)
T001–T005 repo layout, pyproject, pg bootstrap script, compose/Makefile, config+Clock
T006–T013 **Phase 2 foundation: models, migrations, RLS policies, session posture,
isolation tests.** Do not start feature work before these pass — isolation and
point-in-time posture are ruinous to retrofit.
T014–T019 generator (built before ingestion, deliberately: it is the adversary)
then Phases 4–14 per tasks.md.

### Decisions already locked (do not re-litigate without reading clarifications.md)
- Target: P(churn or ≥25% MRR contraction within 90 days of the decision date)
- `HistGradientBoostingClassifier` + isotonic calibration; chosen for **native NaN
  handling** because absence is informative in this estate
- Renewal proximity is a *ranking* multiplier, not the scoring mechanism
- One shared model across tenants, with per-tenant and leave-one-tenant-out reporting
- Tenant isolation via Postgres RLS + `FORCE ROW LEVEL SECURITY`, app role cannot
  bypass; application filters are defence in depth only
- Worker = tick loop + DB-backed leases with `FOR UPDATE SKIP LOCKED`; no broker
- Agent acts on **material change**, not on level
- Auto-send off by default per tenant per play; LLM drafts language only and never
  touches ranking; system fully functional with no LLM
