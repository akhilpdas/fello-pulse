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

## Keeping the mirror in sync

The cloud sandbox is the working copy; `~/Documents/fello-pulse` on the Mac is the
durable one. To sync from a session:

1. In the sandbox: `bash /home/claude/sync.sh` — writes `pulse.bundle` (git history)
   and `pulse-worktree.tar.gz` to the outputs directory.
2. Commit it to `~/Documents/fello-pulse/pulse-sync.bundle` on the device.
3. On the device: `bash infra/scripts/mirror_apply.sh` — fetches from the bundle and
   hard-resets the mirror to it. Idempotent; safe to re-run.

Gotcha worth knowing: committing a file to a device path that already holds a file of
that name can land a stale copy. Verify after every sync with
`git bundle list-heads pulse-sync.bundle` on the device and check the hash is the
commit you expect; if it is stale, commit under a fresh filename.

A git bundle rather than a tar of `.git`, because git objects are immutable and stored
read-only, so a tar overwrite fails on every object that already exists while a bundle
fetch simply transfers what is new.

`pulse-sync.bundle` lives in the mirror folder and is gitignored. Delete permission for
that folder was granted in this session, which git needs anyway: git removes its own
`.lock` files, and without that permission a single fetch leaves a lock behind and every
later git command — including Akhil's own — fails with "File exists".

## Pushing to GitHub

The GitHub connector is linked (`gh api user` returns `akhilpdas`) but is
**repository-scoped**: the session can act on repositories it was configured with and
cannot create a new one. `POST /user/repos` returns 403 "sessions are bound to their
configured repositories", and the GraphQL path `gh repo create` uses is blocked
outright. So `fello-pulse` could not be created from the session. The mirrored copy on the Mac includes the full
`.git` history, so pushing is two commands in a normal Terminal where Akhil's own
credentials live:

```bash
cd ~/Documents/fello-pulse
# create the repo once, on github.com, named fello-pulse (private)
git remote add origin https://github.com/akhilpdas/fello-pulse.git
git push -u origin main
```

After that exists, a later Claude session configured with that repository can push
directly and the tarball mirroring can be dropped.

## Status

### Done — Phases 1–4 of 14 (T001–T027 complete, 38 tests green)
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



---

## Status as of the pause (2026-10-15)

**Done and verified**

- **Phase 1–2 — foundation.** Postgres 16 + Alembic (4 migrations, 16 tables).
  Row-level security on all 13 tenant-scoped tables, `ENABLE` **and** `FORCE`,
  `USING` + `WITH CHECK`, three roles (`pulse` owner / `pulse_app` NOBYPASSRLS /
  `pulse_trainer` BYPASSRLS for cross-tenant training only). Tenant claim set with
  `set_config(..., is_local => true)` so it dies with the transaction and a pooled
  connection cannot carry one tenant's identity into the next request.
  **17 isolation tests**, mutation-verified (see `docs/VERIFICATION.md`).
- **Phase 3 — generator.** 5,000 accounts, **349,870 events**, 3 tenants, 96s,
  reproducible from seed 20261015 (`data_version: dv-20261015-54c3fb70f81a`).
  Latent mean-reverting health process with six shock types; all five sources
  emit noisy lagged observations of it; churn drawn from it. Three deliberate
  noise sources cap achievable AUC in the low-to-mid 0.8s.
  **21 realism tests** that read the feeds as data rather than importing the
  generator.
- **Phase 4 — ingestion.** Five adapters absorbing the mid-history field rename
  and event-type recasing; identity resolution where unresolved is a persisted,
  reportable state and **never** creates a phantom account; idempotent batch
  write on the natural key; watermarks advanced only after the batch commits.
  Account dimension folded from CRM + billing, kept strictly separate from the
  point-in-time feature path.
  Verified: **329,096 events ingested in 39s**, ~0.6% duplicates suppressed by
  the unique constraint, 656 unresolved identities surfaced,
  **a second identical run inserted 0 rows**.

**Bug found and fixed during verification** — the Stripe emitter only emitted
`subscription.updated` when the 30-day invoice grid happened to land on the exact
MRR-change date, so most contractions never reached the feed. Contraction is half
the label, so the model would have been trained on cancellations alone. Now fires
on the day the change happens; 152 material MRR drops in the feed against 150
contractions in the ground truth.

**Next, in order**

- T028–T035 **Phase 5 features**: `denylist.py`, weekday-aligned `windows.py`,
  declarative `registry.py` (~40 features, six driver groups per
  `contracts/features.md`), `compute.py` taking `(tenant, account, as_of)` and
  reading only `received_at <= as_of`. Then the leakage tests: future-event
  invariance, denylist unreachability, absence-vs-zero, aligned windows.
  **Design note already settled:** `compute` must be a pure function over an
  in-memory event list so the panel builder and the serving path share one code
  path — that is the only reliable defence against train/serve skew, and panel
  construction cannot afford a database round trip per snapshot (~195k snapshots).
- T036–T045 Phase 6 model, T046–T054 Phase 7 queue, T055–T060 Phase 8 evidence,
  T061–T074 Phase 9 agent, then API, frontend, delivery docs.

**Environment quirks worth knowing**

- `TZ` is set to something Postgres rejects (`unknown PostgreSQL timezone: 'ASIA0'`);
  harmless, it falls back to UTC, but set `PGTZ=UTC` to silence it.
- Re-running ingestion is always safe; truncate with `TRUNCATE tenant CASCADE`
  to start clean.
