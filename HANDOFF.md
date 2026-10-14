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

## Pushing to GitHub

The Claude session's GitHub connector is **repository-scoped**: it can read and write
repositories it was configured with, but it cannot create a new one, so `fello-pulse`
could not be created from the session. The mirrored copy on the Mac includes the full
`.git` history, so pushing is two commands in a normal Terminal where Akhil's own
credentials live:

```bash
cd ~/Documents/fello-pulse
# create the repo once, on github.com, named fello-pulse (private)
git remote add origin git@github.com:akhilpdas/fello-pulse.git   # or the https URL
git push -u origin main
```

After that exists, a later Claude session configured with that repository can push
directly and the tarball mirroring can be dropped.

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

- **T001–T003, T005** repo layout; `backend/pyproject.toml`; `infra/scripts/pg_bootstrap.sh`
  (native Postgres 16 — Docker is unavailable in the sandbox — creating the `pulse`
  owner and the `pulse_app` NOBYPASSRLS role); `pulse/config.py` with the `Clock`
  protocol and `FrozenClock`, so nothing reads the wall clock directly
- **T006** `pulse/db/base.py` — `TenantScoped` self-registers into
  `TENANT_SCOPED_TABLES` at class-definition time, so the RLS migration and the
  isolation test both iterate over the real schema and cannot drift from it
- **T007** `pulse/db/models.py` — all 16 entities; verified to import and produce
  13 tenant-scoped + 3 global tables with nothing unclassified

### PAUSED HERE at Akhil's request — awaiting confirmation before continuing

### Next (in order)
T004 `infra/docker-compose.yml` + `infra/Makefile`
T008 Alembic env + initial migration (tables and indexes)
T009 RLS migration: `ENABLE` **and** `FORCE ROW LEVEL SECURITY` + tenant policies,
     driven by `TENANT_SCOPED_TABLES`; grants to `pulse_app`
T010 `pulse/db/session.py` — request session issuing `SET LOCAL pulse.tenant_id` inside
     an explicit transaction, plus a separately named elevated session for cross-tenant work
T011–T013 **isolation tests: unfiltered SELECT per table, pooled-connection claim bleed,
     app role cannot bypass.** Do not start feature work before these pass — isolation and
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
