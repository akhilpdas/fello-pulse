# Implementation Plan: Renewal-Risk Prioritisation for Customer Success

**Branch**: `001-renewal-risk-prioritisation` | **Date**: 2026-10-15 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-renewal-risk-prioritisation/spec.md`

---

## Summary

Build a tenant-isolated system that, without being asked, keeps a calibrated 90-day
churn-or-contraction probability current for every account across five source
families, turns it into a capacity-bounded ranked work queue per CSM, explains every
number down to the source records that produced it, and prepares (but does not
unilaterally send) the first outreach.

The technical spine is a single idea carried consistently through every layer:
**everything is computed as-of a decision time from an append-only log keyed on both
when a thing happened and when we found out.** That one commitment is what makes the
backtest honest, the explanations stable, the late-arriving Zendesk ticket harmless,
and the agent's reasoning auditable. Most of the design decisions below are
consequences of it.

---

## Technical Context

**Language/Version**: Python 3.13 (backend, generator, ML), TypeScript 5.7 (frontend)

**Primary Dependencies**: FastAPI, SQLAlchemy 2.0, Alembic, Pydantic v2,
scikit-learn 1.9 (`HistGradientBoostingClassifier`, `IsotonicRegression`), SHAP 0.53,
NumPy, pandas; React 19 + Vite + TypeScript on the client. No message broker, no
feature-store product, no orchestration framework.

**Storage**: PostgreSQL 16. Row-level security for tenant isolation; JSONB for source
payloads, feature vectors and contributions; btree indexes on the `(tenant_id,
account_id, received_at)` access path that every feature query uses.

**Testing**: pytest with a real PostgreSQL instance for anything touching isolation or
SQL (RLS cannot be tested against SQLite), plus pure-unit tests for the IO-free domain
layer. Vitest for frontend logic.

**Target Platform**: Linux. Single API process, single worker process, one database.

**Project Type**: Multi-component web service — backend service, autonomous worker,
ML pipeline, data generator, React client.

**Performance Goals**: a full autonomous cycle over 5,000 accounts across all tenants
in under the 15-minute scheduling interval; queue endpoint p95 under 300 ms;
explanation endpoint p95 under 500 ms including SHAP attribution read from storage
(attribution is computed once at scoring time and persisted, never recomputed on
read).

**Constraints**: must run with no language model configured; must run on one machine
for the walkthrough; no step may require the operator to trigger it; nothing may call
the wall clock directly.

**Scale/Scope**: 3 tenants, ~5,000 accounts, ~220,000 source events over 3 years of
history, ~40 features, ~160,000 training snapshots.

---

## Constitution Check

*GATE: must pass before Phase 0. Re-checked after Phase 1 design.*

| Principle | How this plan satisfies it | Verification |
|---|---|---|
| **I. Point-in-time correctness** | `occurred_at` and `received_at` are separate non-null columns on `source_event`. The feature layer's only entry point takes `as_of` and every query it issues carries `received_at <= :as_of`. Training snapshots are generated at historical Mondays with labels from the following 90 days. A denylist of outcome-adjacent event types is applied inside the feature repository, not by convention. | `tests/leakage/` — future-event invariance, label permutation, denylist unreachability |
| **II. Fitted model ranks, LLM only writes** | `pulse.ml` and `pulse.domain.ranking` import no LLM client; the drafting module is the only consumer of one and sits downstream of a completed score. Drafter is behind an interface with a deterministic template implementation as the default. | `tests/test_no_llm_in_ranking.py` asserts by module-graph inspection that no LLM module is reachable from the ranking path; full pipeline test runs with LLM disabled |
| **III. Autonomy with a reviewed boundary** | A worker process with a tick loop claims `work_lease` rows with an expiry; each cycle writes an `agent_run` with per-stage counts and a `decisions_declined` array. Dispatch requires a `(tenant, play)` allowlist row; everything else lands in `pending_approval`. | `tests/test_worker_unattended.py`, `tests/test_lease_recovery.py`, `tests/test_dispatch_gate.py` |
| **IV. Tenant isolation below the application** | Every tenant-scoped table has `tenant_id NOT NULL`, `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY`, with policies keyed on `current_setting('pulse.tenant_id')`. The app connects as `pulse_app` (`NOBYPASSRLS`); migrations run as the owner. Each request opens a transaction and issues `SET LOCAL pulse.tenant_id`. Cross-tenant training uses a separately named elevated session factory. | `tests/test_tenant_isolation.py` runs an unfiltered `SELECT *` on every tenant-scoped table under tenant A and asserts zero tenant-B rows |
| **V. Nothing unexplained reaches a human** | `score` persists `model_version`, `features` (JSONB), `contributions` (JSONB), `ranking_math` (JSONB). `feature_snapshot.evidence` maps each feature group to the `source_event` ids behind it. A diff endpoint attributes score movement per feature. Confidence gating writes an explicit `abstain_reason`. | `tests/test_evidence_trail.py` asserts no score persists without resolvable evidence and that contributions reconcile to the model output |

**Result: PASS.** No violations to record in Complexity Tracking.

---

## Phase 0 — Research

Full detail in [research.md](./research.md). The decisions that shaped the build:

1. **Point-in-time features without a feature store.** Rejected Feast and similar:
   the hard part here is not serving infrastructure, it is the as-of semantics, and a
   feature store would still need us to get those right. Implemented as declarative
   feature specs over a windowed event query, so a feature is a named pure function
   with a declared window, source dependency and evidence rule. Backfill and serving
   use the same code path, which is the only reliable defence against train/serve skew.

2. **Missing data as information.** `HistGradientBoostingClassifier` learns a
   default direction for NaN at every split, so absence is a modelled signal. Features
   therefore return `None` rather than `0` when the underlying evidence does not exist,
   and the distinction is carried all the way to the model. This is the single most
   important modelling choice given a tenant with no Gmail and a tenth of accounts
   cold.

3. **Calibration is not optional.** The ranking multiplies probability by dollars.
   An uncalibrated boosted-tree score is not a probability, so the product of it and
   an ACV is not an expected loss, and a CSM quoting it would be quoting a fiction.
   Isotonic regression on a dedicated held-out time block, with reliability reported.

4. **Attribution computed once, at write time.** TreeSHAP is cheap per row but not
   free, and recomputing on read means an explanation can silently disagree with the
   score it explains if the artefact moved. Contributions are computed in the scoring
   step and persisted next to the score. Reads are JSONB lookups.

5. **Driver grouping for the human.** Forty feature-level SHAP values are not an
   explanation; they are a different kind of spreadsheet. Features are grouped into
   six named drivers in business language and contributions are summed within group,
   with the feature-level detail one expand away.

6. **Database queue over a broker.** Thousands of work units per cycle against a
   database that is already transactional and already deployed. Leases give crash
   recovery; `FOR UPDATE SKIP LOCKED` gives safe concurrent claiming.

7. **Postgres RLS as the isolation control.** Application filters fail open; RLS
   fails closed. Accepted costs — per-transaction claim setting, pooling discipline,
   an explicit elevated path for cross-tenant jobs — are each covered by a test.

8. **Latent-state data generation.** A generator that samples features and then
   assigns labels from them produces a dataset where the model's job is to invert a
   formula. A generator that simulates an unobserved health process and emits noisy
   lagged observations of it produces one where the model's job is inference, which is
   the job it will have in production. Noise is tuned so achievable AUC sits in a
   believable band rather than near 1.0.

---

## Phase 1 — Design

- **[data-model.md](./data-model.md)** — the fourteen entities, their keys, the RLS
  posture per table, and the indexes that the as-of query depends on.
- **[contracts/openapi.yaml](./contracts/openapi.yaml)** — HTTP surface.
- **[contracts/ingestion.md](./contracts/ingestion.md)** — the five source record
  contracts the generator emits and the adapters normalise, including the renamed
  field and the identity-mapping gap.
- **[contracts/features.md](./contracts/features.md)** — the feature registry: name,
  window, source dependency, absence semantics, driver group, denylist interaction.
- **[quickstart.md](./quickstart.md)** — empty database to running scored system.

### Project Structure

#### Documentation (this feature)

```text
specs/001-renewal-risk-prioritisation/
├── spec.md
├── clarifications.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── openapi.yaml
│   ├── ingestion.md
│   └── features.md
└── tasks.md
```

#### Source Code (repository root)

```text
backend/
├── pulse/
│   ├── config.py                 # settings, injectable clock, seeds
│   ├── domain/                   # pure, IO-free, unit-testable without a DB
│   │   ├── drivers.py            # feature -> business driver grouping
│   │   ├── ranking.py            # priority arithmetic, capacity cut, suppression
│   │   ├── tiers.py              # probability -> red/amber/green
│   │   ├── confidence.py         # abstain rules and reasons
│   │   └── change.py             # material-change detection between two scores
│   ├── db/
│   │   ├── base.py               # declarative base, tenant mixin
│   │   ├── models.py             # SQLAlchemy models for all entities
│   │   ├── session.py            # app session (RLS claim) + elevated session
│   │   └── migrations/           # Alembic, incl. RLS policy migration
│   ├── ingest/
│   │   ├── contracts.py          # pydantic models for the five source records
│   │   ├── adapters/             # one per source; schema-drift normalisation
│   │   ├── identity.py           # source id -> internal account resolution
│   │   └── service.py            # idempotent write, watermark advance
│   ├── features/
│   │   ├── registry.py           # declarative feature specs
│   │   ├── windows.py            # aligned-window helpers (weekday-safe)
│   │   ├── denylist.py           # outcome-adjacent event types
│   │   └── compute.py            # as-of computation + evidence capture
│   ├── ml/
│   │   ├── panel.py              # snapshot panel construction
│   │   ├── labels.py             # churn-or-contraction labelling
│   │   ├── train.py              # fit, calibrate, gate, register
│   │   ├── evaluate.py           # operating point, baselines, calibration, lead time
│   │   ├── explain.py            # TreeSHAP -> contributions -> drivers
│   │   └── registry.py           # versioned artefacts + model cards
│   ├── scoring/
│   │   └── service.py            # score an account as-of, persist with lineage
│   ├── agent/
│   │   ├── worker.py             # tick loop, lease claiming
│   │   ├── cycle.py              # the stages of one autonomous cycle
│   │   ├── plays.py              # play registry and eligibility rules
│   │   ├── policy.py             # allowlist, suppression, rate limits
│   │   ├── drafter.py            # template drafter + optional LLM, grounding check
│   │   └── transport.py          # outbound interface + recording implementation
│   └── api/
│       ├── app.py                # application factory, RLS middleware
│       ├── auth.py               # bearer token -> tenant + user claims
│       └── routers/              # queue, accounts, actions, runs, admin, model
└── tests/
    ├── unit/                     # domain layer, no database
    ├── integration/              # ingestion, features, scoring, worker
    ├── contract/                 # API shape
    ├── isolation/                # RLS proofs
    └── leakage/                  # point-in-time proofs

generator/
├── simulate.py                   # latent health process per account
├── emit.py                       # five source emitters with lag/noise/duplicates
├── pathologies.py                # drift, dupes, identity gaps, cold start
└── main.py                       # CLI: seed -> source feeds on disk

frontend/
├── src/
│   ├── api/                      # typed client
│   ├── pages/                    # Queue, Account, Runs
│   ├── components/               # EvidenceTrail, DriverBar, ScoreDiff, DraftReview
│   └── lib/
└── vite.config.ts

infra/
├── docker-compose.yml
├── Makefile
└── scripts/                      # local postgres bootstrap, seed, run-all
```

**Structure Decision**: separate `backend/`, `generator/` and `frontend/` trees. The
generator is deliberately *not* inside `backend/pulse/` — it is a simulator that plays
the role of five external systems, and if it shared a module tree with the application
it would be far too easy for application code to reach into it, or for a reviewer to
suspect it had. It communicates only through the on-disk source feeds defined in
`contracts/ingestion.md`, which is the same interface a real integration would use.

Within the backend, `domain/` holds pure logic with no database or network imports, so
the ranking arithmetic, tier thresholds, abstain rules and change detection are
testable in milliseconds and arguable in isolation. Everything else is an adapter
around it.

---

## Implementation Sequencing

Ordered so that each step produces something verifiable, and so that the properties
that are expensive to retrofit are in place first.

1. **Foundation** — settings and injectable clock, SQLAlchemy models for all entities,
   the initial migration, and the RLS policy migration. Isolation tests pass before
   any feature code exists, because retrofitting isolation is how isolation bugs
   happen.
2. **Generator** — latent simulation and the five emitters with their pathologies.
   Built before ingestion so ingestion is written against adversarial data from the
   first line rather than against clean data plus later patching.
3. **Ingestion** — adapters, identity resolution, idempotent write, watermarks.
   Verified by replaying the generated feeds twice and asserting the event count is
   unchanged.
4. **Features** — registry, aligned windows, denylist, as-of computation with evidence
   capture. Leakage tests pass here.
5. **ML** — panel construction, labelling, train/calibrate/gate, evaluation with the
   operating point and baselines, TreeSHAP attribution.
6. **Scoring** — score with lineage, contributions, drivers, confidence gating.
7. **Domain ranking** — priority arithmetic, capacity cut, suppression, tiers, change
   detection.
8. **Agent** — cycle stages, plays, policy gates, drafter, transport, run records,
   lease handling.
9. **API** — queue, account evidence, score diff, actions, runs, admin, model report.
10. **Frontend** — queue, account evidence trail, draft review, run log.
11. **Hardening** — the full test matrix, the one-command bootstrap, documentation.

---

## Risks and Mitigations

| Risk | Consequence | Mitigation |
|---|---|---|
| Train/serve skew between backfilled and live features | Model performs well in backtest and badly in production; the classic silent failure | One code path for both, taking `as_of` as a parameter; a test asserts panel-time and serve-time vectors for the same `(account, as_of)` are byte-identical |
| Label definition wrong (open question A1) | Every downstream number is meaningless | Definition is configuration, not code; positive-class rate reported per tenant so a bad definition is visible immediately |
| Generator too kind, model looks unrealistically good | The whole submission loses credibility | Irreducible noise injected by construction; a test fails the build if test-block AUC exceeds a plausibility ceiling |
| Generator too harsh, model looks useless | Cannot demonstrate the product works | Lift over the heuristic baseline is the gate, not absolute AUC |
| RLS claim leaking across pooled connections | Cross-tenant read — the worst possible bug | `SET LOCAL` inside an explicit transaction per request; a test that reuses a pooled connection across two tenant sessions and asserts no bleed |
| Agent floods customers after a model change | Reputational damage at the customer's customers | Dispatch allowlist off by default, per-account suppression, per-tenant rate limit, and material-change gating rather than level gating |
| Thin-data accounts scored confidently | The exact failure that precedes "nobody saw it coming" | Explicit confidence gate with reasons, surfaced as its own bucket, tested as reachable |
| Cycle exceeds the scheduling interval at scale | Queues go stale silently | Change-driven recomputation rather than full rescoring; lease prevents overlapping cycles; cycle duration recorded per run and surfaced in the run log |

---

## Complexity Tracking

> No constitutional violations. Table intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |
