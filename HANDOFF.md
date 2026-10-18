# Handoff / Resume Notes

This file is the restart point if a session ends. It is updated at the end of every
phase. Read it first, then `specs/001-renewal-risk-prioritisation/tasks.md` and
`specs/002-production-readiness/tasks.md`.

> **To run or present it, read `docs/DEMO_GUIDE.md`** (start commands, sign-ins, guided tour, which model is used, real vs stand-in).
>
> **Current state is the section titled "CLOSED OUT" near the bottom** (and `README.md`'s "What was verified" / "Gaps").
> Everything above it is dated history, kept because it explains *why* things are as they are — some of it
> (e.g. "no authentication", "header identity", "0.33") was true then and is not now.

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

---

## Status as of 2026-10-15 (continued session, same day) — Phases 5–8 complete (T028–T060)

**This Mac has its own local Postgres now.** The cloud sandbox from earlier in
this doc is gone; this and all future sessions on `~/Documents/fello-pulse` run
natively on macOS. Setup, once:
```
brew install postgresql@16
PGBIN="/opt/homebrew/opt/postgresql@16/bin" bash infra/scripts/pg_bootstrap.sh
cd backend && python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
```
Cluster lives at `~/.pgdata` (owner role `pulse`, app role `pulse_app`, both
created by the bootstrap script; `pulse_trainer` BYPASSRLS is created by
migration `0002_rls`). Postgres must be started (`pg_ctl -D ~/.pgdata start` or
re-run the bootstrap script, which is idempotent) before running tests.

**Strict TDD from this point on** — see `AGENTS.md` (new file, read first). Every
task below was written test-first: watched fail, then implemented, then the
*full* suite re-run, not just the new file. Phases 1–4 above were not done this
way; that was flagged by Akhil mid-session and corrected going forward.

**Data regenerated and re-ingested locally** (the sandbox's dataset never made
it to this Mac — `data/feeds/` is gitignored): `python3 generator/main.py --seed
20261015` reproduced the documented 349,870 events exactly
(`dv-20261015-54c3fb70f81a`); `pulse.cli bootstrap` + `pulse.cli ingest`
(no `--until`, full history) landed 347,740 rows, consistent with the ~0.6%
duplicate-suppression rate reported before.

**Done and verified — Phase 5 (features, T028–T035).**
`features/denylist.py` makes the denylist a type guarantee, not a convention:
`AccountFeatureInput` is a frozen dataclass built by a whitelist constructor,
so `lifecycle_state`/`churned_at`/`churn_kind` have no attribute path into
feature code at all. `features/windows.py` anchors every window to `as_of` in
whole multiples of 7 days rather than calendar boundaries — the fix for the
partial-current-week bug the generator's seasonality is designed to expose.
`features/registry.py` declares all 38 features from `contracts/features.md`
across the six driver groups; `features/compute.py` computes all of them as a
pure function over an in-memory event list, with an `assert` at import time
that the registry and the computation dispatch table can never drift apart.
All four required leakage/absence/alignment tests pass, plus supporting unit
tests for denylist/windows/registry (97 assertions total in Phase 5).
One real design correction made while implementing, not just reported: the
original task briefing assumed `AccountFeatureInput` would carry `seats`/
`acv_cents`/`renewal_date` directly from the account dimension row. That would
have violated `ingest/dimension.py`'s own explicit warning against reading
current state for a point-in-time feature. Fixed: `AccountFeatureInput` carries
only `signup_date` (genuinely time-invariant); every other commercial
attribute is derived inside `compute.py` from the latest `crm.account_updated`
event as-of, the same as every other feature family.

**Done and verified — Phase 6 (model, T036–T045).** `ml/labels.py` draws the
churn-or-contraction label from billing, requiring a contraction to survive one
full billing cycle (~35 days) before counting — a blip that reverts is noise.
`ml/panel.py` builds the weekly account-level snapshot panel, excluding any
Monday whose full horizon isn't observable before `dataset_end` (no silently
mislabelling a right-censored row as a confirmed negative). `ml/train.py` fits
`HistGradientBoostingClassifier` with a time-based 60/15/15/10 split and
isotonic calibration on the held-out block; it also hardens against a real
edge case found while testing — a feature with zero observed values in a given
training block crashes sklearn's binning step, so such columns are now dropped
per-model, transparently, rather than letting an unlucky split take down
training. `ml/evaluate.py`, `ml/registry.py` (promotion gate) and
`ml/explain.py` (TreeSHAP summed into the six drivers) are all built and
tested; SHAP additivity was verified empirically (it holds in log-odds space
for this model, not probability space) before writing the reconciliation test.
Full end-to-end run against the real ingested data (`pulse.ml.pipeline`):
130,853 panel rows, 3.63% positive rate, ROC-AUC 0.69 on the test block, beats
both the trivial and heuristic baselines, passes the plausibility-ceiling gate,
and is promoted (precision@100 0.30 vs. heuristic baseline 0.02).
**Known, honestly-reported gap** (see clarifications.md B-15): the model's
real-world AUC (0.69) is below the Phase 3 design note's "low-to-mid 0.8s"
expectation, and the two planted retrospective fixtures are **not** flagged at
any point in their history (SC-005, SC-006 not currently satisfied) — their
individual features do show real decline, but ticket-volume features dominate
over response-time features in the current attribution for the
slow-support-decline fixture specifically, and the time budget didn't allow
for principled feature re-engineering with proper held-out validation. Not
hand-tuned against the two fixtures directly, which would be its own kind of
overfitting.

**Done and verified — Phase 7 (US1, the Monday queue — MVP, T046–T054).**
`domain/tiers.py`, `confidence.py` (the three-reason abstain rule, checked in
the contract's stated order), `ranking.py` (`priority = p × value_at_risk ×
urgency`, urgency a deliberate multiplier per clarifications B-2, never a
model feature) and `change.py` (material change, not level — B-9) are all
pure, DB-free, and unit tested. `scoring/service.py` is the one place that
calls `features/compute.py` via the same `features/repository.py` loader the
panel builder uses — train/serve parity is structural. It persists
`FeatureSnapshot` + `Score` with `ON CONFLICT DO NOTHING`/`DO UPDATE`
idempotency on `(tenant_id, account_id, as_of)`. `GET /queue`
(`api/routers/queue.py`, new `api/main.py` FastAPI app) returns the
suppression-filtered, capacity-bound, priority-ordered queue with a per-row
delta computed via a `LAG() OVER (PARTITION BY account_id ORDER BY as_of)`
against the account's own score history. SC-012 (never green on thin evidence)
is enforced structurally: `tier` is `"abstain"`, a fourth value, never a
silent fallback to `"green"`.

**Done and verified — Phase 8 (US2, evidence trail, T055–T060).**
`api/routers/accounts.py`: account detail (drivers, feature values, evidence
ids), an evidence-resolution endpoint scoped to the account (so one account's
evidence ids can't be used to pull another account's source records), and
`GET /accounts/{id}/score-diff` (feature-level diff between two `as_of`
values, sorted by `|contribution_delta|`, FR-027). Verified against the real
ingested data: every evidence id resolves to a real `source_event` row, and
SHAP contributions reconcile exactly (< 1e-4) to the base model's own raw
logit output — not just a plausible-looking number.

**Full suite: 121 passed, 0 skipped, 0 failed** (run twice to check for
flakiness — stable both times). `git status` after this session: nothing
committed (per instruction — only commit when the user asks); new/modified
files are untracked/modified in the working tree, including this file,
`AGENTS.md`, `clarifications.md`, `tasks.md`, and everything under
`backend/pulse/{features,ml,domain,scoring,api}/` and `backend/tests/`.

**Next, in order**

- T061–T074 **Phase 9, US3 — the autonomous cycle**: `agent/plays.py`,
  `policy.py` (allowlist/suppression/rate-limit), `drafter.py` (template +
  optional LLM behind one interface, grounding validation), `transport.py`,
  `cycle.py` (writes `agent_run` with `decisions_declined`), `worker.py`
  (`FOR UPDATE SKIP LOCKED` leasing). Then the seven integration/unit tests
  for unattended operation, lease recovery, concurrent claim, dispatch gating,
  suppression/rate-limit, no-LLM-in-ranking, and grounding validation.
- Before Phase 9, worth a short pass on the Phase 6 gap above if time allows:
  the response-time-vs-ticket-volume imbalance in support feature attribution
  is a concrete, specific lead, not a vague "tune the model" note.
- After Phase 9: Phase 10 (draft review, T075–T077), Phase 11 (multi-tenant
  behaviour, T078–T08x), Phase 12 (model report, US6), Phase 13 (frontend),
  Phase 14 (hardening/delivery docs).

---

## Status as of the pause (2026-10-16, Phases 9–10)

**Done and verified — Phase 9 (US3, the autonomous cycle, T061–T074).**
`agent/plays.py` (five plays, one play per driver group except `data_quality`;
`commercial_review` alone gates on renewal proximity — B-16),
`agent/policy.py` (suppression → cooldown window → allowlist → rate limit,
in that order; every withholding carries a reason, never a bare flag — see
the policy fix below), `agent/drafter.py` (deterministic templates; an LLM
path exists behind the identical `draft()` interface but is never imported
except lazily inside the `llm_enabled` branch, so it is unreachable, not just
unused, when disabled — the default), `agent/transport.py` (`Transport`
protocol + `RecordingTransport`, no real network call anywhere in this
deliverable), `agent/cycle.py` (score → material-change gate → play
selection → policy → draft → grounding validation → persist, with every
non-action recorded in `decisions_declined` and every withheld auto-send
recorded on the `Action` row itself — B-17), `agent/worker.py` +
`agent/lease.py` (`FOR UPDATE SKIP LOCKED` claim/release against
`work_lease`, managed through `owner_session` rather than a new DB role —
B-18).

**One real bug found and fixed during this phase**: `_previous_score`
(`agent/cycle.py`) read `score.probability` via raw SQL and handed the
resulting `Decimal` straight to `material_change`'s float arithmetic —
`TypeError` on the very first cycle that had a predecessor score to compare
against. Caught by `test_dispatch_gate.py`, not by inspection. Fixed by
casting to `float` at the query boundary.

**A second, more structural bug found and fixed**: the first versions of
`test_dispatch_gate.py` and `test_runs_without_llm.py` ran against the real
`northwind` tenant and asserted "at least one account drafts this run" —
true in isolation, but false once another cycle-level test had already run
against the same tenant and left `score` rows behind (`material_change`'s
"no previous score" branch no longer fired). Running the full suite twice
in a row surfaced two different results for the same code — the actual
signal that something was order-dependent. Fixed by giving every cycle-level
test its own freshly seeded tenant (`tests/integration/_agent_fixtures.py`)
with deterministic ticket volume. Full notes: clarifications.md B-20.

**TDD provenance, stated plainly rather than implied.** T061–T064 (plays,
policy, drafter, transport) were genuinely test-first: each test was written,
run, watched to fail with `ModuleNotFoundError`, then implemented. `cycle.py`
and `worker.py`/`lease.py` (T065–T066) could not practically be driven the
same way — they're one coupled orchestration unit with too many interacting
branches to get any single test green incrementally — so they were built
together and proven first by `test_worker_unattended.py` (T067), written and
confirmed RED before the implementation existed. The *remaining* Phase 9
tests (T068–T074) were then written as regression/behaviour tests against
that already-working implementation, not test-first in the strict sense —
and two of them (the Decimal bug, the tenant-isolation bug above) still
caught real defects despite being written after the code, which is the
honest argument for writing them at all even post-hoc.

**Done and verified — Phase 10 (US4, draft review, T075–T077).**
`api/routers/actions.py`: `GET /actions` (optional `state` filter),
`POST /actions/{id}/approve` (records `decided_by_user_id`/`decided_at`,
then attempts send via `agent/transport.py`'s new `send_with_retry` — 3
attempts, stop on first success, `state` becomes `sent` or the distinct,
queryable `send_failed` with the last error as `state_reason` — B-17's same
surfaced-not-swallowed principle, applied to the human-approved path),
`POST /actions/{id}/reject`, `PATCH /actions/{id}` (edit only while
`state == 'drafted'`; records the same actor/timestamp columns a decision
uses but does not change `state` — B-19). All four endpoints are rejected
with 409 once a decision has already been made — the row becomes immutable
history.

**Full suite: 162 passed, 0 skipped, 0 failed** — run twice in direct
succession specifically to check for the order-dependency class of bug found
above; stable both times. `ruff check` on every new/modified file: only
cosmetic `E501` (line length) remains, consistent with the convention
established in Phases 5–8; the one real finding (`SIM115`, an unclosed file
handle in a test) was fixed. `git status`: still nothing committed —
untracked/modified files only, now also including `backend/pulse/agent/`,
`backend/pulse/api/routers/actions.py`, and the new agent test files under
`backend/tests/{unit,integration}/`.

**Next, in order**

- T078–T081 **Phase 11, US5 — multi-tenant behaviour**: `api/routers/admin.py`
  (per-tenant config + allowlist management, operator-only), per-tenant
  per-source coverage reporting (FR-012), then the two isolation/coverage
  tests.
- After Phase 11: Phase 12 (model report, US6, T082+), Phase 13 (frontend),
  Phase 14 (hardening/delivery docs). The Phase 6 model-skill gap (B-15) and
  the TDD-provenance note above are both still open items worth a deliberate
  pass before calling the MVP done, not just moving on.

---

## Status as of 2026-10-16 (Phases 11–12)

**Done and verified — Phase 11 (US5, T078–T081).** `api/routers/admin.py`:
`GET/PATCH /admin/config` (unknown fields rejected, 422), `GET /admin/allowlist`,
`PUT /admin/allowlist/{play_key}` (records the enabling operator; unknown play 404),
`GET /admin/coverage` (per source: connected, events landed, unresolved events, last
received — FR-012). Operator-only via `X-User-Id` resolving to `app_user.role =
'operator'` (403 otherwise); all writes go through the RLS session, so an operator can
only touch their own tenant. **TDD provenance:** T078–T080 test-first (watched fail on
404). **T081 tests passed on first run** — they pin behaviour that already existed
(absent-vs-zero in `features/compute.py`), so they are regression tests, not test-first.

**Done and verified — Phase 12 (US6, T082–T083).** `api/routers/model.py`: `GET /model`
serves the latest *promoted* card from `../artifacts/*.json` (404 if none), shaped as
operating point, both baselines, calibration, per-tenant slices, seed, version. Sections
the pipeline did not produce are reported `{"available": false, "reason": ...}`, never
omitted. `ml/pipeline.py` now also records `operating_point` and the reliability curve.
**Bug found against the real card, not by the synthetic tests:** tenant slices with no
positives have NaN PR-AUC, which made `/model` 500; now served as `null` (test-first).
**Deliberately dropped:** lead-time distribution — the panel carries no outcome dates, so
the report states it unavailable (should be recorded in clarifications.md).

**Open issue found:** `pulse.ml.pipeline` trains on *every* tenant in the database,
including the leftover `agent-test-*` tenants the integration tests create. The newest
promoted card (`m-20261016075744-dv-local-s7`) therefore includes test tenants in its
per-tenant slices and training data. Needs a fix (restrict to real tenants / clean up
test tenants) and a retrain before the model numbers are quoted anywhere.

**Full suite: 174 passed** (run twice before the final test was added: stable).

**Next:** see the delivery section below.

---

## Status as of 2026-10-16 (Phases 13–14 — delivery)

**Phase 13 — frontend (T084–T090).** `frontend/`: React 19 + Vite + TypeScript. Queue, Account
(driver bars, lazily-resolved evidence trail down to source payloads, score diff), Draft review
(draft beside its grounding; edit/approve/reject), Run log, Low confidence. Types for paths and
request bodies are generated from `contracts/openapi.yaml` (`npm run gen:api`); response bodies are
hand-typed in `src/api/types.ts` because the routes return plain dicts. 13 vitest tests (formatting,
API client incl. repeated array params and surfaced error detail); `npm run build` type-checks clean.
Smoke-tested against real data through the Vite proxy for every endpoint the UI calls — but **not
driven in a browser**; no interaction (clicks, approve, edit) has been exercised by a human or a browser test.
New backend surface, all test-first: `GET /runs`, `GET /queue/low-confidence` (reason + remedy),
`grounding` on actions, `GET /admin/*`, `GET /model`.

**Phase 14 — delivery (T091–T097).** `infra/scripts/run_all.sh` (SC-014): ran against an *empty*
scratch database (`PULSE_DB_NAME=pulse_verify`, feeds regenerated) → exit 0 in 208 s, 347,740 events
ingested, model promoted, one cycle over 3 tenants. `contracts/openapi.yaml` generated and guarded by a
drift test. README, quickstart, solution brief, deck outline, Loom script written. **T095 deck is a
markdown outline, T096 is a script — neither rendered/recorded.** T097: full cycle over ~4,540 accounts
= ~104 s against a 15-minute interval (SC-007).

**Bugs found and fixed this pass (each with a failing test first, except where noted):**
- Pipeline trained on test-seeded tenants → now only tenants with an ingestion watermark (B-23).
- `/model` 500 on NaN per-tenant metrics → served as null.
- Precision@capacity depended on DB row order via tied scores (0.30 vs 0.24, same AUC) → tie-aware (B-22); real figure 0.326 vs 0.021.
- `agent_run.duration_ms` was hardcoded 0 → real wall-clock duration.
- Vite proxy `localhost` → IPv6 ECONNREFUSED against uvicorn on IPv4 → `127.0.0.1` (found by smoke test, not covered by an automated test).
- `tasks.md` T001–T027 were never ticked in the earlier sandbox session; ticked now **except** T004 (docker-compose, dropped) and T024–T027, which had **no test files at all** — written now, post-hoc, mutation-verified (docs/VERIFICATION.md).

**Known open items.** SC-005/SC-006 not met (B-15, B-21); older tests (`test_scoring_service`,
`test_queue_endpoint`) still write toy scores into the real `northwind` tenant of a dev DB, which makes
"delta since last cycle" misleading there (a `run_all.sh` database is clean) (B-23); `ruff` shows
pre-existing E501/E702 style findings; nothing in this session is committed.

**Databases (changed at the end of the delivery pass).** `pulse` = demo only, rebuilt clean with
`run_all.sh` (it had accumulated 375 tenants of test debris). `pulse_test` = what pytest uses
(`tests/conftest.py` forces it, ignoring shell env; build once with `PULSE_DB_NAME=pulse_test bash
infra/scripts/run_all.sh`). Verified: a full 196-test run left `pulse` unchanged. This resolves the
"tests write toy scores into northwind" item in B-23 for the demo database. VS Code tasks: `.vscode/tasks.json`.

---

## Status as of 2026-10-16 (validation against the exercise sheet, then submission)

Validated the build against the exercise brief point by point (data volumes/sources/messiness, the five
non-negotiables, the deliverables). Findings and what was done:

**Fixed (test-first, `tests/integration/test_worker_serve.py`, each test watched failing for its stated
reason; full suite 201 passed):** the "runs without a human" non-negotiable was weaker than claimed.
`worker.serve` had no entry point, no test, and nothing started it (B-24). While making it real: one
failing tenant killed the worker; a failed cycle left no run record; "is it due?" compared wall-clock
`started_at` to the injected clock. Now: `pulse serve [--simulate-present]` + VS Code task 4; failures
are recorded as `failed` runs and isolated per tenant; recency is judged on `as_of`. `OffsetClock` added.
**Live proof** (scratch copy of the demo DB, `PULSE_CYCLE_INTERVAL_MINUTES=1`, discarded afterwards): the
worker, with nobody triggering anything, wrote a new `succeeded` run for each of the 3 tenants one interval
after the previous ones (as_of 16:45:31 → 16:46:31; scored 1535/493/2512; 0 drafted, correctly — no new
data, nothing changed). The demo DB was not touched (3 runs / 4,540 scores).

**Deck:** `docs/Pulse_deck.pptx` (11 slides, built by `docs/build_deck.py` from `docs/DECK.md`; the queue slide
carries the live top of the northwind queue). Only slide 1 was visually inspected (macOS Quick Look renders
the first slide only); slides 2–11 are text and one table — open it and check the layout.

**Data vs the sheet:** 5,000 accounts (3 tenants), **347,740** events (sheet says roughly 200,000 — 1.7× over, on
purpose: three years of weekly usage rollups dominate), five sources, 9,252 events received >1 day after they
occurred, 10,930 (3%) with an unresolved identity, 94 accounts with <5 events. The generated data's present
(2026-11-10) is later than the machine's wall clock (2026-10-16); that is why the worker has `--simulate-present`.

**Still not done, and not hidden:** SC-005/SC-006 (AUC 0.69; the two planted accounts are not flagged; no lead
time); no real-browser run of the UI; the Loom is a script, not a recording; no hosted/"live" URL — it runs locally;
no auth layer; nothing pushed to GitHub until the owner says so.

---

## Status as of 2026-10-16 (spec 002 — Phase 0, Phase 1 and Phase 2 / US1 complete: the MVP checkpoint)

Specification, plan, research, data model, contracts, quickstart and 104 tasks are in `specs/002-production-readiness/`.
Work is strictly test-first; `tasks.md` is ticked as it goes. **Backend 301 passed, frontend 21 passed, build clean.**

**Done**
- **Phase 0 — gaps spec 001 promised and never built** (found by `/speckit-analyze`): false-positive feedback
  (`POST /accounts/{id}/feedback`), suppress-with-expiry (`POST/DELETE /accounts/{id}/suppress`), leave-one-tenant-out in
  the model card and `GET /model`, UI actions on the account page. 001's `tasks.md` corrected (T039, T096, Phase 15).
- **Bugs found on the way, fixed with tests:** per-tenant model metrics were attributed to the wrong tenants
  (every card said northwind = 13,086 rows); the LLM key printed in `repr(Settings)`; a dead hard-coded `auth_secret`.
- **Phase 1 — schema:** migration `0005` (credentials, contacts, outbound settings, delivery/provenance columns, `app_session`,
  `audit_event` (append-only), `contact_opt_out`) with FORCEd RLS; isolation suite seeds and covers the new tables; mutation-checked.
- **Phase 2 — identity (US1):** scrypt passwords + policy; opaque revocable sessions (`<tenant>.<secret>`, looked up *under* RLS, no
  `SECURITY DEFINER`); login limiter; `/auth/login|me|logout`; **headers are no longer trusted anywhere**; every route requires a
  session (swept from the OpenAPI schema); operator-only routes enforced server-side; CSMs see only their own accounts (404 otherwise);
  the approver is the session user, never the body; disabled/demoted users lose access on the next request; operator user and
  ownership management; audit trail; worker actions attributed to the system; CSRF header for cookie writes; sign-in screen replaces
  the paste-ids bar; demo users have passwords (generated, `.demo-credentials.pulse`, git-ignored, mode 600). Mutation-verified (3).
  Smoke-tested with curl against the real demo database.

**Corrected numbers.** The README/brief/deck figure of precision@100 0.33 / AUC 0.69 was stale; the reproducible figure is
**0.196 vs 0.021 (~9×), AUC 0.684** (clarifications B-25). Cold-start (leave-one-tenant-out): globex AUC 0.72, northwind 0.67,
**initech 0.575 / precision 0.06** — the shared model barely helps a small new tenant.

**Not done yet (Phases 3–6):** real email (SMTP transport, send gate, demo-mode redirect, opt-out), live LLM drafting with grounding
validation, container files (unverified — Docker is not installed), re-quoting every metric after the contact-field data change, README
"skipped" split, re-run `/speckit-analyze`. **Not verified:** the new sign-in screen and account-action buttons have not been driven in
a browser; there is no operator UI (user/audit/outbound management is API only); login rate limiting is per-process.
Nothing from this session is committed.


---

## Status as of 2026-10-16 (spec 002 — Phase 3 / US2, real email, complete)

Backend **371 passed**, frontend **29 passed**, build clean. Tasks T249–T273 done (see `specs/002-production-readiness/tasks.md`).

- **Data:** the simulated CRM now carries a primary customer contact per account (~90%; the rest realistically none). Derived
  from a hash of the account reference, **not** the main random stream — so all 349,870 existing records are byte-identical
  (fingerprint checked before and after) and no earlier metric moves. Ingestion stores the latest CRM contact on the account.
- **Delivery:** `SmtpTransport` (stdlib), a pure send gate (`domain/send_gate.py`), and one shared `agent/delivery.py` used by both a
  human approval and the unattended cycle. Safe by default: nothing sends unless the tenant has outbound on, a verified sender,
  a provider, a known contact and no opt-out; each failure is its own state with zero network traffic. **Demo mode is the default**:
  mail goes only to a test inbox, or is captured without any delivery. Approve is atomic and idempotent; an *ambiguous* outcome
  becomes `send_unconfirmed` and is never auto-retried.
- **Found and fixed on the way:** the unattended cycle was calling the transport directly with a placeholder address and no
  gate (now routed through the same delivery code); SMTP misconfiguration was retried as "transient" (now permanent).
- **Operator controls (API only):** `GET/PATCH /admin/outbound` (cannot enable without a verified sender; changing the sender
  revokes verification), `/admin/opt-outs`, opt-out footer on every message, audit events.
- **UI:** the Drafts page explains each state in plain words and allows re-approval only where the message definitely did not leave.
- **Mutation-verified (3):** gate bypass, demo-mode bypass, retry-on-ambiguous — each caught (docs/VERIFICATION.md).

**Not verified:** no real email has ever been sent by this system — only to an in-process fake SMTP server. Bounces, replies
and complaints are not processed. The operator pages (outbound settings, opt-outs, users, audit) exist only as API routes. The
demo database has not been rebuilt, so it does not yet contain customer contacts (rebuild with the "RESET" then "build demo data" tasks).

---

## Containers (spec 002 Phase 5) — superseded: now VERIFIED on arm64 (see the end of this file)

`docker-compose.yml`, `infra/docker/{backend,frontend}.Dockerfile`, `entrypoint.sh`, `nginx.conf`, `.dockerignore` are written and
statically checked (`tests/unit/test_container_files.py`). **They have never been built or run: Docker is not installed on this
machine.** First run on a machine with Docker: `docker compose up --build`, then
`docker compose run --rm api python3 -m pulse.cli bootstrap-demo`; record the result here and remove the "unverified" labels.

---

## Status as of 2026-10-16 (end of the session: spec 002 complete except the items listed under "Open")

**Test counts:** backend 430 · frontend 34 · browser (real Chrome) 9 — all passing at the last commit. Commits this session, newest first:
`72e86f3` honest README + verified numbers · `856ef9f` browser tests, operator pages, shared limiter · `a861d62` containers (unverified),
`bootstrap-demo`, deterministic panel order · `98bf9c8` language-model drafting · `27e56e8` real email · `033ddeb` authentication + spec-001 gaps.
**Nothing has been pushed since `c59312a`** — `git push origin main` publishes five new commits.

**Resuming:** read `README.md` ("What was verified", "Decisions", "Gaps"), then `specs/002-production-readiness/tasks.md` (ticked as done), then `docs/VERIFICATION.md`.
Run the demo: VS Code tasks 1 → 3 → "show demo sign-ins". Tests: `cd backend && source .venv/bin/activate && export PGTZ=UTC && python3 -m pytest -q`;
browser: `cd frontend && npm run e2e` (needs Chrome and a built `pulse` database).

**Corrections to earlier claims (all recorded in `clarifications.md`):** the "0.33 / 0.69" headline was stale and order-sensitive — the reproducible figure is
precision@100 **0.289** vs 0.023 (range 0.22–0.33 by row order), ROC-AUC **0.690** (B-25, B-27); per-tenant model metrics had been attributed to the wrong tenants;
the unattended worker could not be started and the cycle sent to a placeholder address with no gate; leave-one-tenant-out, feedback and suppression were promised in spec 001
and never built. All fixed test-first.

**Open (not done — see README "Gaps"):** real email and real LLM calls never exercised against a real provider; containers never built (Docker not installed); SSO/MFA; bounce handling;
lead time and SC-005/006 unmet; the Loom is a script, not a recording; no hosted URL. The `.pptx` deck is rebuilt from `docs/DECK.md` by `docs/build_deck.py` (run it with the API up to
embed the live queue).

---

## CLOSED OUT (2026-10-17)

The "resume here" items are done: the failing reconcile test was a rounding/ordering problem in the test, not a defect (fixed and explained in `docs/VERIFICATION.md`); address-wide login limiting added; spec 002 reworded where
it overclaimed; deck rebuilt with the signed-in queue; browser suite stable (3 runs). **Backend 436 · frontend 34 · browser 9, all passing.** All tasks in `specs/002-production-readiness/tasks.md` are ticked.

**What is still not done or not verified** is listed in `README.md` ("What was verified", "Gaps"): no real email or LLM provider call has ever been made; containers never built (no Docker here); no SSO/MFA; bounces and replies unprocessed;
lead time and SC-005/006 (model quality) unmet; Loom is a script not a recording; no hosted URL; account names are not unique and drafts for CRM-less accounts greet by reference.
**Unpushed:** seven commits ahead of `origin/main` — pushing is the owner's call.


---

## Containers verified (2026-10-17) — supersedes every earlier "unverified" note above

Installed Colima + the Docker CLI with Homebrew (no admin password, no GUI) and ran the stack for real. **Findings and results:**
- images built first time (api/worker 882 MB, web 92 MB), non-root, no secrets or data baked in; all four services healthy; migrations applied by the api;
- **one real bug, found only by running it:** the worker exited when no model existed (always the case on a fresh stack), so the runtime restarted it forever. Fixed test-first —
  `worker.serve` now re-resolves its runtimes each tick and waits; the simulated clock tolerates an empty database (`LazyOffsetClock`);
- `bootstrap-demo` in the container reproduced the host's numbers exactly (ROC-AUC 0.690, precision@100 0.289, 347,740 events);
- the worker started scoring on its own as soon as the model existed, with the lease system preventing double-processing; right after `bootstrap-demo` the queue can briefly look empty
  while it finishes (the command now says so);
- the 9 browser scenarios pass against the containers (`infra/scripts/e2e_docker.sh`); data persists across `down`/`up`.
**Not covered:** amd64, vulnerability scanning, the SC-012 ten-minute timing, a real SMTP provider or model key inside the stack.
Colima is still installed and may be running (`colima status`; `colima stop` to free its 8 GB / 4 CPUs; `docker compose down -v` also deletes the stack's data volumes).


---

## Browse, history and week picker (2026-10-17, after close-out)

Found by running the demo by hand: the queue showed "2490 more below the cut" with no way to open them, no way to see an earlier week, and "since last cycle" / **What moved** had nothing to compare (one snapshot per tenant).
All three built test-first (`superpowers:test-driven-development`):

- `GET /queue/all` (paged, filter by tier/driver, name search, absolute `rank`, `in_queue`), `GET /queue/snapshots`; `pulse.scoring.backfill` + `pulse backfill --weeks N` (scores only, in-sample caveat). openapi.yaml and `schema.d.ts` regenerated.
- UI: *All accounts* page (`/browse`), Week picker on both pages (shared through `?as_of=`), "Browse all accounts →" link. Pure helpers in `lib/browse.ts`.
- **Counts:** backend 479 · frontend 39 · browser 11 (two new scenarios; watched RED first for the missing link/picker). Browser suite run twice, stable.
- **Not test-first, said so in the tests:** the tie-order guard and the "earlier snapshot shows deltas" test passed on first run (behaviour already existed); the tie-order one is mutation-checked. Two of my own browser assertions raced the 250 ms search debounce; fixed in the test, not the product.
- **Demo database `pulse` was backfilled** (9 snapshots per tenant, actions 505 / runs 3 unchanged). Containers and fresh `run_all.sh` builds are not.
- **Open:** `.vscode/tasks.json` has a stray edit (`/opt/h omebrew/...`, a space inside the Postgres path) that is not part of this work.


---

## Email verified locally, "What moved" fixed, walkthrough written (2026-10-17, later)

- **Email against a real SMTP server (Mailpit, `brew install mailpit`):** send-test, human approve (demo redirect, `[DEMO → …]` subject, footer, no double send), opt-out, demo-off delivery, reject, no-recipient, and an **unattended cycle that sent 30 messages with the play allowlisted** — all verified on a scratch copy of the demo DB (since dropped). Still **not** a real provider (no STARTTLS/auth/bounces) and **no live LLM call** (needs a key). New VS Code tasks: *mail inbox (Mailpit)*, *API with local mail*, *3b. run the demo with local mail*. clarifications B-29 addendum.
- **Bug found by reading code while writing the guide, fixed test-first:** "What moved" matched an exact stored timestamp but offered a minute-precision date picker, so every comparison from the UI was a 404. Now a dropdown of weeks that exist, sending the stored timestamp untouched. Browser scenario added (watched RED, then green).
- **Finding, not fixed (design decision) — clarifications B-30:** "now" is `max(received_at)` over all sources; stray Salesforce events set it to 2026-11-10 while product/support/billing/email end 10-12…10-19, so the newest snapshot sees weeks of silence everywhere (Northwind: 144 red vs 15 the week before). The headline queue is partly an artifact. Options (a)/(b)/(c) are written up there.
- **e2e no longer collides with a running demo:** own ports (API 8100, UI 8173, `PULSE_E2E_*_PORT`), and it copies the DB with dump/restore (a template copy is refused while the demo is connected). 12 browser scenarios pass alongside a live demo.
- **`docs/TEST_WALKTHROUGH.md`** — the step-by-step manual test guide (parts A–G + a checklist). Claims in it were checked against the code (rate limit: 5 failures then 429 verified live).
- **Not committed.** Files changed since the last commit: browse/history/week-picker work (previous entry) plus this entry.


---

## B-30 fixed, free-model drafting, screenshot walkthrough (2026-10-17, evening)

- **B-30 fixed, test-first** (`tests/integration/test_data_present.py`, 9 tests): "now" for a simulated-present run = the earliest, across sources, of each source's newest `received_at` (`pulse.ingest.present.data_present`), used by `pulse cycle`, `pulse serve --simulate-present` and the demo build. On this data that is 2026-10-12 = the generator manifest's `dataset_end`. **The demo database was rebuilt and re-backfilled**: 9 weekly snapshots 17 Aug → 12 Oct; the newest Northwind snapshot now has 7 red accounts and mean risk 0.039 (it was 144 and 0.082). The 6 drafts approved earlier were lost in the rebuild; sign-in password unchanged.
- **Second LLM provider, test-first** (`test_openai_compatible_client.py`, `test_llm_provider_selection.py`; clarifications B-31): `PULSE_LLM_PROVIDER=openai_compatible` + `PULSE_LLM_BASE_URL`; stdlib only; key optional for local models. **Run for real** against Ollama + `qwen2.5:7b`: direct calls 2–4 s; one full cycle = 20 model-written drafts, 20 accepted, 0 fallbacks, 148 s for three workspaces. Anthropic provider unchanged and still never run against the real API. Ollama and Mailpit are installed with Homebrew (`brew services` not enabled; start with `ollama serve`, `mailpit`).
- **UX bug found by the screenshot run, fixed test-first:** approving a draft with outbound off made it silently vanish from the "drafted" list (the reason was visible only under another filter). The Drafts page now shows a notice with the outcome right after Approve/Reject/Save (`.draft-notice`). Browser scenario added.
- **`docs/Pulse_Test_Walkthrough.docx` (+ `.pdf`)**: the step-by-step guide with 26 screenshots (red outlines show what to click). Source: `docs/walkthrough/Pulse_Test_Walkthrough.md`; screenshots: `docs/walkthrough/capture.mjs` (+ `capture-llm.mjs`) run against a **scratch copy** of the data; build: `bash docs/walkthrough/build.sh` (pandoc + LibreOffice). `docs/TEST_WALKTHROUGH.md` is now a pointer.
- **Counts:** backend 488+ (see the run below), frontend 39, browser 13 (own ports 8100/8173; run alongside a live demo).
- **Hosting research (nothing deployed):** AWS new accounts get $100–$200 credits on a Free Plan that ends after 6 months or when credits are spent (then the account closes); a 4 GB Graviton server (t4g.medium) is ~$25–30/month, so credits cover a short review. Cloudflare quick tunnel from the Mac is free but ephemeral. Oracle's free ARM tier was reportedly halved. Render free does not fit (sleeps; no free worker; DB expires in 30 days).
- **Observation to decide on:** the weekly queue's top 12 are mostly green/amber large renewals (priority = risk × value × urgency; only ~7 accounts clear the red threshold 0.32). By design, but it reads oddly in a demo about "red accounts".
- **Not committed.**


---

## Demo polish: tier cut-offs, disambiguator, packaging (2026-10-18)

- **Committed and pushed earlier today:** browse/history/B-30/LLM-provider/e2e/docs (4 commits to `c20bd76`).
- **Cut-offs fixed (clarifications B-32):** red ≥ 0.145, amber ≥ 0.098 for all tenants (generator + the demo DB `tenant_config`); newest week now Northwind 52 red/196 amber, Globex 46/131, Initech 4/14. All nine weeks were re-labelled by one SQL UPDATE from the stored probabilities (scores are immutable, so neither the cycle nor `backfill` re-tiers; the cycle was also "not due") from the stored probabilities (the cycle was "not due"), so **drafts for the newly red accounts appear at the worker's next cycle**. Guard test added.
- **`external_ref` on queue rows** (test-first) and shown beside the name in Queue and All accounts.
- **Packaging:** `docs/DECK.md` and `docs/LOOM_SCRIPT.md` corrected (they still said no real email/model call had been made); `docs/HOSTING.md` (tunnel from the Mac, or a small AWS server — not deployed); compose header no longer says "unverified".
- **Counts:** backend 509 passed / 1 skipped, frontend 39. Browser suite re-run: see the next line.
- **Still open:** model quality (B-15: planted accounts missed, no lead time, AUC 0.69) — deliberately deferred pending the owner's go-ahead; Loom not recorded; nothing hosted.


---

## Model quality: the ceiling, four fixes, lead time (2026-10-18) — clarifications B-33

- **Finding that changed the plan:** an oracle handed each account's hidden health (replaying the generator: `generator/oracle_ceiling.py`) scores ROC-AUC 0.65-0.70 per out-of-sample fold. The "low 0.8s" ceiling in the generator docstring was never measured and is wrong (docstring corrected). The old 0.69 / precision@100 0.29 headline was one ~3-week block; the same model scored mean 0.61 on a rolling backtest. Feature engineering was **not** done: existing features already reconstruct the hidden health (R² 0.78) and adding the true health gained nothing.
- **Built test-first:** `labels.next_outcome_at` + `PanelRow.outcome_at`; `evaluate.lead_time_report`; `ml/backtest.py` (`rolling_origin_scores`, `backtest_report`); `pipeline.lowest_tier_cutoffs` and the backtest in `pipeline.run` (card keys `rolling_backtest`, `lead_time_days`; `GET /model` serves both); regularised trees; fit on train+val; sigmoid calibration (isotonic gave 100% scores). Mutation-checked the regularisation test.
- **Numbers (final, deterministic across rebuilds):** rolling AUC 0.624/0.625/0.689/0.706 (mean 0.661; oracle 0.673; was 0.609); hold-out block AUC 0.727, PR-AUC 0.185, precision@100 0.50 (noisy); lead time at amber ≥0.10: 32% of 390 losses flagged, median 72 days, 29% ≥4 weeks; red ≥0.20: 14%.
- **Cut-offs:** amber 0.10 / red 0.20 for every tenant (supersedes B-32's 0.145/0.098). Newest week: Northwind 52 red / 151 amber, Globex 49 / 88, Initech 0 / 1.
- **Demo database rebuilt from scratch** with the final config (`run_all.sh` + `backfill --weeks 8`); the sign-in password is unchanged. Restart the API/UI tasks.
- **SC-006 withdrawn:** both planted accounts are flawed fixtures (one forced to churn by a non-health rule; the other churned a year before its planted collapse and has no billing identity). Not flagged out of sample; the in-sample scores are not claimed.
- **Not done:** containers not rebuilt with the new model; hyperparameters/calibration chosen on the data later reported (mild optimism, stated); cold-start tenant unchanged; nothing committed.

---

## Containers re-verified with the new model (2026-10-18)

- Rebuilt the images from the current source (Colima, arm64; own project name and port 5273 so the host demo was untouched), `bootstrap-demo` inside the container: hold-out ROC-AUC 0.7267 / PR-AUC 0.1848, rolling folds 0.624 / 0.625 / 0.689 / 0.706, lead time identical to the host build; top of the Northwind queue identical (Castlegate Estates 67.2%, 2,254 below the cut). `backfill --weeks 8` also ran in the container. Torn down afterwards; Colima stopped (it was not running before).
- **Found by running it, fixed test-first:** the unattended worker writes a new snapshot every 15 minutes, so a day holds many and the Week picker listed near-duplicates (the browser scenario "earlier weeks" failed because "the previous week" was the same date). `GET /queue/snapshots` now returns one entry per UTC day, the day's last snapshot (`test_several_cycles_on_one_day_are_one_entry_the_latest_of_that_day`). All 13 browser scenarios then passed against the containers.
- **Open observation, not changed:** with the worker running, the queue's "Since last cycle" column compares with the previous *cycle* (minutes earlier, so mostly flat), while "What moved" and the picker compare across days. Fine for production semantics, but a demo with the worker on shows little movement in that column; the host demo (worker off) shows the backfilled weekly movement.


---

## Reviewer-style dry run in Docker (2026-10-18)

- **Clean clone from GitHub** (`bd9decd`), README steps only, own project name and port 5273 (your host demo untouched): stack up in 17 s (images cached from my earlier build, so a first-ever build is slower and was not timed), `bootstrap-demo` 7 min 37 s, `backfill --weeks 8` **46 min** (it took ~10 min earlier the same day in a container; the stack's own worker was cycling at the same time and I was running other work, but the spread is a real reviewer-experience risk). Then: 13/13 browser scenarios pass through nginx, all three workspaces sign in, `/model` reports AUC 0.7267 and the same four folds. With the worker running, the newest snapshot drifts (top account differed from the screenshots: Lakeshore Collective vs Castlegate Estates) — expected for `--simulate-present`, worth one sentence to a reviewer.
- **Gap found and fixed (test-first, `test_compose_llm_settings.py`):** `docker-compose.yml` passed only `PULSE_LLM_ENABLED` and the key, so a free model could not be selected in Docker. It now passes provider, base URL and model (defaults: off / anthropic / claude-sonnet-5-5). `.env.example` (new) has one block per option; `.env` is now git-ignored (it was not). Verified: a container read the settings and got a reply from Ollama on the host (needs `OLLAMA_HOST=0.0.0.0`).
- Cleaned up: dry-run stack and the leftover 2026-10-17 `fello-pulse` containers/volumes removed; Colima stopped; Ollama stopped.
- **Not committed.**


---

## Spec 003 — hosted demo and reviewer experience: built and verified in Docker (2026-10-18)

Run through the spec-kit flow: `specs/003-hosted-demo/` (spec, plan, 32 tasks), three clarification questions answered (B-34). Strict TDD: every module below has tests written first and watched failing.

- **What "10 to 40 minutes" meant:** a reviewer following the README waits 7 min 37 s for `bootstrap-demo` (inside 002's SC-012 target of 10 minutes) and then, to get the history that makes the Week picker and "What moved" worth opening, 10 to **46 minutes** for `backfill --weeks 8` (the range is real: the same step took 10 minutes on a quiet machine and 46 when the stack's own worker and other work shared the CPU). The history step is what a reviewer abandons at minute 15.
- **Seed (US1):** `pulse export-seed` / `load-seed` (`pulse/seed.py`): data-only `pg_dump` (51 MB) + manifest (schema revision, sha256, row counts, draft provenance) + the promoted model archive (62 KB — the model is files, not rows). Excludes sessions, login attempts, leases; **replaces every password hash** with one for the person loading; refuses to export if outbound email is on; refuses a non-empty database without `--overwrite` (which is also the reset). **Measured in Docker: load in 15 s; 13/13 browser scenarios; same top account, nine snapshots, model report; worker starts "model ready".** Found by running it: Debian's `pg_restore` 17 emits `SET transaction_timeout`, which a 16 server rejects → the restore streams through a filter into `psql` (`strip_unsupported_settings`); Colima only shares `$HOME` with containers.
- **Hosted image (US2):** `infra/docker/hosted.Dockerfile`, `pulse.api.hosted` (`/api/*` → the app, everything else the UI with SPA fallback), `pulse.hosted_boot` (translate `DATABASE_URL`, migrate, load the seed into an empty database, serve on `$PORT`). **Measured: empty database to serving in 17 s with the seed downloaded over HTTPS; 13/13 scenarios; 237 MB RAM after the suite (Render free allows 512).** `render.yaml` written, **not validated by Render**. `infra/render/probe.sh` answers GO / NEEDS-CHANGES / NO-GO in seconds (4 tests). Cold-start message in the sign-in page (7 tests).
- **Groq (US3):** `pulse llm-check` (`pulse/llm_check.py`, 13 tests): one real call, latency, and the rate-limit headers the provider actually sent. Run for real against local Ollama (3.3 s); **not yet run against Groq: needs the owner's free key.** `docker-compose.yml` now passes provider/base URL/model (found by the dry run), `.env.example`, `.env` git-ignored.
- **Image size:** 882 MB → 966 MB (`postgresql-client` for `pg_dump`/`pg_restore`).
- **Owner steps left (they need accounts or a key):** T014 publish the seed as a GitHub Release asset (`gh` is not installed; web upload works); T022 Render (probe first); T024 Railway if Render says NEEDS-CHANGES/NO-GO; T028 free Groq key → T029 one real cycle with `llm_calls_per_cycle` lowered → T030 re-export the seed so it holds model-written, labelled drafts; T015 stopwatch from a clean clone with the published seed.
- **Written down as not done:** a hosted worker; custom request-role passwords (the migration's development defaults remain — restrict the database's network access); T023 (the no-superuser path) is conditional on the probe.


---

## Seed published, cold stopwatch, submission kit (2026-10-18, later)

- **gh** installed and authenticated (`akhilpdas`). **Release `seed-v1`** created with the three seed files (template drafts, sha256 in the notes). **The repository is still PRIVATE**: making it public was blocked by the permission classifier (it is hard to undo, so it needs the owner's own command: `gh repo edit akhilpdas/fello-pulse --visibility public --accept-visibility-change-consequences`; revert with `--visibility private`). A pre-flight scan found no secrets in files or history; the history does carry the author email `agilpdas@gmail.com` (8 commits) and the laptop hostname (33). Until it is public, `load-seed --url` and the hosted service cannot download the seed anonymously.
- **SC-001 stopwatch:** fresh clone, empty Docker image cache, Apple silicon, Colima 4 CPU / 8 GB: **76 s** cold build and start + **14 s** seed load = **90 s** to a signed-in demo (seed from a local file; the 51 MB download adds seconds, not yet measured). 13/13 browser scenarios pass against it. Compare: 7 min 37 s to build + 10-46 min of backfill.
- **Submission kit (git-ignored, local):** `.submission-email.local.md` (draft with the workspaces, logins and password) and `.submission-attachments/Pulse_demo_credentials.txt`. Decision: the hosted URL and the credentials go only in the email, never in the repository or README.
- **Deck** (12 slides) and **Loom script** updated for the seed path. **Still open:** Groq (needs the owner's free key in `.env`), Render probe (needs a free Render Postgres URL in `.env`), hosted deploy, re-export of the seed with Groq-written drafts, final deck/Loom/email once the hosted URL and Groq facts exist.

- **Repository is now PUBLIC** (owner ran the command). Verified anonymously: `git clone`, and all three seed assets download with the right sha256. **End-to-end reviewer path from public GitHub, empty cache, `load-seed --url`: 73 s build + 244 s download/verify/load = 5 min 17 s** (download-bound on this connection; the load itself is ~14 s); under the 10-minute target. `.env` created (git-ignored, mode 600) with two `FILL_ME` values: the Groq key and the Render database URL.


---

## Render first deploy: found a real privilege gap, fixed test-first (2026-10-18)

- **What Render did:** the Blueprint created `pulse-db` and the `pulse` service; the service failed in `alembic upgrade head` at migration 0002: `permission denied to create role … Only roles with the BYPASSRLS attribute may create roles with the BYPASSRLS attribute` (the managed login has CREATEROLE but is not a superuser and has no BYPASSRLS).
- **Fix (T023, test first, RED reproduced Render's exact error):** migrations 0002/0005 create `pulse_trainer` and grant to it only when the login may (superuser or BYPASSRLS), so the request role `pulse_app` is created as before (NOBYPASSRLS) and FORCE ROW LEVEL SECURITY is untouched; `pulse.seed.needs_rls_lift` / `rls_lifted` lift FORCE on the forced tables for the length of a seed load and restore it (committed both sides; ENABLE stays on, so `pulse_app` is never unprotected); `load_seed(lift_rls=)` wraps truncate, restore, password reset and count check, and restores even when the restore fails; a refused load lifts nothing. A superuser login (every local path) is unchanged.
- **Tests:** `test_migration_roles_without_superuser.py` (3; starts its own throwaway Postgres because roles are cluster-wide), 3 new in `test_seed_load.py`. **Verified by hand:** the real 51 MB seed loaded on a CREATEROLE-only cluster (5,000 accounts, 36,953 scores), FORCE restored on 16/16 tables, sign-in and queue through `pulse_app`.
- **Consequence to state:** on Render there is no `pulse_trainer`, so model training cannot run there (nothing hosted trains; the model ships in the seed).


---

## Render is live; Groq run for real; seed rebuilt with model-written drafts (2026-10-18, evening)

- **Render:** the redeploy after T023 worked. the hosted service (URL kept out of the repo on purpose; it is in the submission email only) serves the UI and `/api`; sign-in and queue verified over HTTPS (top account Castlegate Estates 67.2%, 2,254 below the cut). **9 of the 13 browser scenarios pass against the live URL** in real Chrome (sign-in form, wrong password, operator queue + Admin, browse/page/filter, Week picker, What moved, CSM scoping + admin API refused, sign-out). The other 4 (approve a draft, confirm/suppress an account, admin outbound setup, demo-mode approval) write data and pass locally; they were not run on the live demo so the reviewer does not meet a changed demo. Free-tier DB created 2026-10-18, expires about 2026-11-17 (+14 days grace). Cold start not yet timed.
- **Groq (US3), first real call, two defects found and fixed test-first:** (1) Cloudflare returned HTTP 403 (error 1010) to Python's default User-Agent: a good key looked rejected; both request paths now send `fello-pulse/1.0`; (2) `llama-3.3-70b-versatile` is retired (404); default is now `qwen/qwen3.8-27b`. Observed limits: 1,000 requests/day, 8,000 tokens/minute. (3) The tokens/minute cap makes a batch hit 429s, so `OpenAICompatibleClient` honours `Retry-After` (3 retries, at most 30 s each), test first.
- **Real cycle (scratch copy of the demo DB, old drafts cleared):** 740 s; 106 drafts: **91 model-written, 15 template** (12 call cap, 2 unsupported number, 1 malformed). No key: the same 106 as templates (166 s). Fewer drafts than the old demo's 336 because the retrained model leaves fewer accounts in tiers with an eligible play (`no_eligible_play`); the old 336 came from the earlier model.
- **Seed:** re-exported (91 llm / 15 template), loaded on a non-superuser cluster, and the `seed-v1` release assets replaced in place (same URLs; sha256 `15455293d505f802…` verified from an anonymous download).
- **Still to do:** (a) reset the Render DB to this seed: needs the DB's External URL in `.env` (`RENDER_DB_URL`), then `load-seed --overwrite` from this machine; (b) run the 4 write scenarios once on a throwaway copy if wanted; (c) time the cold start; (d) Loom + submission email.
