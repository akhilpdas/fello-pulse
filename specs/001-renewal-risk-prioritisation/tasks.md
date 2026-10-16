---
description: "Task list for 001-renewal-risk-prioritisation"
---

# Tasks: Renewal-Risk Prioritisation for Customer Success

**Input**: `spec.md`, `plan.md`, `data-model.md`, `contracts/`

**Tests**: Required. The constitution makes five properties non-negotiable and each is
provable only by test; the test is part of the deliverable, not an optional extra.

**Organisation**: grouped by user story. US1, US2 and US3 are co-equal P1 and together
form the MVP — the queue is useless if untrustworthy (US2) or stale (US3).

## Format: `[ID] [P?] [Story] Description`

- **[P]** — parallelisable (different files, no dependency)
- Paths are as laid out in `plan.md`

---

## Phase 1: Setup

- [X] T001 Repository layout per plan.md: `backend/`, `generator/`, `frontend/`, `infra/`
- [X] T002 `backend/pyproject.toml` with pinned dependencies; `ruff` + `pytest` config
- [X] T003 [P] `infra/scripts/pg_bootstrap.sh` — local Postgres cluster, `pulse` owner, `pulse_app` NOBYPASSRLS role
- [~] T004 [P] `infra/docker-compose.yml` and `infra/Makefile` with the one-command path — **dropped**: Docker is unavailable where this was built; `infra/scripts/run_all.sh` is the one-command path (see README "Deliberately skipped")
- [X] T005 [P] `backend/pulse/config.py` — pydantic settings, injectable `Clock`, seeds

---

## Phase 2: Foundational (blocks every story)

**⚠️ Isolation and point-in-time posture must exist before any feature code. Both are
ruinous to retrofit.**

- [X] T006 `backend/pulse/db/base.py` — declarative base, `TenantScoped` mixin
- [X] T007 `backend/pulse/db/models.py` — all 16 entities from data-model.md
- [X] T008 Alembic env + initial migration creating every table and index
- [X] T009 Migration enabling `ROW LEVEL SECURITY` **and** `FORCE ROW LEVEL SECURITY` with tenant policies on all tenant-scoped tables; grants to `pulse_app`
- [X] T010 `backend/pulse/db/session.py` — request session issuing `SET LOCAL pulse.tenant_id` inside an explicit transaction, plus a separately named elevated session factory for cross-tenant work
- [X] T011 [P] `tests/isolation/test_tenant_isolation.py` — unfiltered `SELECT *` per tenant-scoped table under tenant A asserts zero tenant-B rows
- [X] T012 [P] `tests/isolation/test_pool_claim_bleed.py` — two tenant sessions over one pooled connection, assert no claim leaks
- [X] T013 [P] `tests/isolation/test_app_role_cannot_bypass.py` — assert `pulse_app` lacks BYPASSRLS and that policies apply to the owner under FORCE

**Checkpoint**: isolation provable on an empty schema.

---

## Phase 3: Generator (adversary for everything downstream)

Built before ingestion so ingestion is written against hostile data from line one.

- [X] T014 `generator/simulate.py` — latent mean-reverting health process per account with discrete shocks (champion departure, support failure, competitive eval, QBR, price rise)
- [X] T015 `generator/emit.py` — five emitters producing the contracts in `contracts/ingestion.md`, each observing the latent state with source-specific noise and lag
- [X] T016 `generator/pathologies.py` — lag distributions, out-of-order write order, duplicates, backfill burst, field rename, case drift, null rates, identity gaps, cold start, missing-source-per-tenant, weekday/holiday seasonality
- [X] T017 Churn-or-contraction decision drawn from the latent state with deliberate irreducible noise; plant the two named retrospective fixtures (slow support decline, fast champion collapse) per A7
- [X] T018 `generator/main.py` — seeded CLI writing `data/feeds/<tenant>/<source>.jsonl` plus a `data_version` manifest
- [X] T019 [P] `tests/unit/test_generator_realism.py` — assert positive-class rate in a plausible band, assert feeds are ordered by `received_at` and not by `occurred_at`, assert each pathology is present at its stated rate

**Checkpoint**: 3 tenants, ~5,000 accounts, ~220k events, reproducible from a seed.

---

## Phase 4: US3 — Ingestion and the unattended spine (Priority: P1)

**Goal**: records land correctly and idempotently, with watermarks, under no human
instruction.

**Independent Test**: replay every feed twice; event count unchanged, watermarks advanced once.

- [X] T020 [P] [US3] `backend/pulse/ingest/contracts.py` — pydantic envelope + per-source payload models
- [X] T021 [US3] `backend/pulse/ingest/adapters/` — one adapter per source; normalise event types, resolve both spellings of the renamed field and the case drift
- [X] T022 [US3] `backend/pulse/ingest/identity.py` — source ref → account resolution with method and confidence; unresolved is a persisted state, not an exception
- [X] T023 [US3] `backend/pulse/ingest/service.py` — batch write with `ON CONFLICT DO NOTHING` on `(tenant_id, source, source_event_id)`, watermark advanced only after commit
- [X] T024 [P] [US3] `tests/integration/test_ingest_idempotent.py` — double replay, assert no duplicate rows and single watermark advance — written after the code (Phase 4 predates the TDD mandate); mutation-verified, see docs/VERIFICATION.md
- [X] T025 [P] [US3] `tests/integration/test_ingest_out_of_order.py` — assert a late record is accepted and does not reorder history — written after the code (Phase 4 predates the TDD mandate); mutation-verified, see docs/VERIFICATION.md
- [X] T026 [P] [US3] `tests/integration/test_schema_drift.py` — both field spellings and both type casings normalise identically — written after the code (Phase 4 predates the TDD mandate); mutation-verified, see docs/VERIFICATION.md
- [X] T027 [P] [US3] `tests/integration/test_identity_unresolved.py` — an unmapped ref is stored unresolved and surfaced, and does not create a phantom account — written after the code (Phase 4 predates the TDD mandate); mutation-verified, see docs/VERIFICATION.md

---

## Phase 5: Features (blocks US1 and US2)

- [X] T028 `backend/pulse/features/denylist.py` — outcome-adjacent event types and account outcome columns
- [X] T029 `backend/pulse/features/windows.py` — weekday-aligned window helpers
- [X] T030 `backend/pulse/features/registry.py` — declarative specs per `contracts/features.md`: name, driver, window, readable types, absence rule
- [X] T031 `backend/pulse/features/compute.py` — `compute(tenant, account, as_of)` reading only `received_at <= as_of`, returning values + per-driver evidence ids + coverage
- [X] T032 [P] `tests/leakage/test_future_event_invariance.py` — insert an event after `as_of`, recompute, assert identical vector (SC-009)
- [X] T033 [P] `tests/leakage/test_denylist_unreachable.py` — assert feature code cannot read denylisted types or outcome columns
- [X] T034 [P] `tests/unit/test_absence_vs_zero.py` — no-gmail tenant yields `None`; silent customer yields `0.0`
- [X] T035 [P] `tests/unit/test_aligned_windows.py` — a weekend-heavy seasonal series does not produce a spurious week-over-week decline

---

## Phase 6: Model (blocks US1 and US6)

- [X] T036 `backend/pulse/ml/labels.py` — churn-or-contraction labelling from billing corroborated by CRM, per-tenant threshold
- [X] T037 `backend/pulse/ml/panel.py` — weekly snapshot panel; features as-of each historical Monday, label from the following horizon
- [X] T038 `backend/pulse/ml/train.py` — `HistGradientBoostingClassifier`, time-based split, isotonic calibration on a held-out block, seeded
- [X] T039 `backend/pulse/ml/evaluate.py` — PR-AUC, ROC-AUC, Brier, reliability; **precision@capacity and captured-ACV@capacity**; trivial and heuristic baselines; per-tenant and leave-one-tenant-out; lead-time distribution; retrospective fixture check
- [X] T040 `backend/pulse/ml/registry.py` — versioned artefact, model card, promotion gated on beating the heuristic baseline at the operating point (FR-020)
- [X] T041 `backend/pulse/ml/explain.py` — TreeSHAP contributions, summed into the six drivers
- [X] T042 [P] `tests/leakage/test_label_permutation.py` — permuted labels collapse skill to chance (SC-010)
- [X] T043 [P] `tests/unit/test_train_serve_parity.py` — panel-time and serve-time vectors for the same `(account, as_of)` are identical
- [X] T044 [P] `tests/unit/test_promotion_gate.py` — a model that loses to the baseline is not promoted
- [X] T045 [P] `tests/unit/test_performance_plausibility.py` — fail the build if test AUC exceeds the plausibility ceiling (a near-perfect score means a broken harness)

---

## Phase 7: US1 — The Monday queue (Priority: P1) 🎯 MVP

- [X] T046 [P] [US1] `backend/pulse/domain/tiers.py` — probability → red/amber/green from tenant thresholds; 0–100 display transform
- [X] T047 [P] [US1] `backend/pulse/domain/confidence.py` — abstain rules with machine-readable reasons
- [X] T048 [P] [US1] `backend/pulse/domain/ranking.py` — `priority = p × value_at_risk × urgency`, suppression, capacity cut, below-the-cut count; emits `ranking_math`
- [X] T049 [P] [US1] `backend/pulse/domain/change.py` — material change: tier crossing, probability delta, dominant-driver switch
- [X] T050 [US1] `backend/pulse/scoring/service.py` — compute features, predict, calibrate, attribute, tier, gate confidence, rank, persist with full lineage
- [X] T051 [US1] `backend/pulse/api/routers/queue.py` — `GET /queue` bounded, ordered, with per-row reason, value at risk, renewal distance and delta
- [X] T052 [P] [US1] `tests/unit/test_ranking_math.py` — nearer renewal outranks equal probability; suppression removes; cut is respected and counted
- [X] T053 [P] [US1] `tests/integration/test_queue_endpoint.py` — bounded ordered queue with all required row fields
- [X] T054 [P] [US1] `tests/unit/test_abstain_never_green.py` — a thin-evidence account is never presented as green (SC-012)

**Checkpoint**: US1 independently demonstrable.

---

## Phase 8: US2 — Evidence trail (Priority: P1)

- [X] T055 [US2] `backend/pulse/api/routers/accounts.py` — account detail with drivers, feature values, evidence ids
- [X] T056 [US2] Evidence resolution endpoint returning source records with original payloads
- [X] T057 [US2] `GET /accounts/{id}/score-diff` — feature-level diff between two scores with per-feature contribution change (FR-027)
- [X] T058 [P] [US2] `tests/integration/test_evidence_trail.py` — no score persists without resolvable evidence; contributions reconcile to model output
- [X] T059 [P] [US2] `tests/integration/test_score_diff.py` — a known feature movement is correctly attributed
- [X] T060 [P] [US2] `tests/unit/test_data_quality_attribution.py` — risk driven by a data outage is labelled as data quality, not customer behaviour

---

## Phase 9: US3 — The autonomous cycle (Priority: P1)

- [X] T061 [US3] `backend/pulse/agent/plays.py` — play registry with eligibility by dominant driver, value tier, renewal proximity, confidence
- [X] T062 [US3] `backend/pulse/agent/policy.py` — allowlist, suppression window, per-tenant rate limit; every declined decision returns a reason
- [X] T063 [US3] `backend/pulse/agent/drafter.py` — deterministic template drafter; optional LLM behind the same interface; grounding validation rejecting unsupported claims before a human sees them
- [X] T064 [US3] `backend/pulse/agent/transport.py` — outbound interface with a recording implementation
- [X] T065 [US3] `backend/pulse/agent/cycle.py` — the stages, writing `agent_run` with stage counts and `decisions_declined`
- [X] T066 [US3] `backend/pulse/agent/worker.py` — tick loop, `FOR UPDATE SKIP LOCKED` lease claiming, expiry reclaim, no overlapping cycles
- [X] T067 [P] [US3] `tests/integration/test_worker_unattended.py` — one full cycle with zero human input advances every stage and writes a run record
- [X] T068 [P] [US3] `tests/integration/test_lease_recovery.py` — killed mid-unit work is reclaimed after expiry and not double-processed
- [X] T069 [P] [US3] `tests/integration/test_concurrent_claim.py` — two workers claim each unit exactly once
- [X] T070 [P] [US3] `tests/integration/test_dispatch_gate.py` — un-allowlisted play cannot self-send; withholding is recorded with its reason
- [X] T071 [P] [US3] `tests/integration/test_suppression_and_rate_limit.py` — repeated cycles respect both, and record each suppression
- [X] T072 [P] [US3] `tests/unit/test_no_llm_in_ranking.py` — module-graph assertion that no LLM module is reachable from the ranking path (FR-013)
- [X] T073 [P] [US3] `tests/integration/test_runs_without_llm.py` — full pipeline with LLM disabled (SC-013)
- [X] T074 [P] [US3] `tests/unit/test_grounding_validation.py` — an unsupported claim is rejected

**Checkpoint**: US1+US2+US3 = the MVP. The brief's five non-negotiables are all demonstrable here.

---

## Phase 10: US4 — Draft review (Priority: P2)

- [X] T075 [US4] `backend/pulse/api/routers/actions.py` — list, approve, reject, edit; actor and timestamp recorded
- [X] T076 [US4] Send-on-approve path through the transport, with bounded retry and surfacing on final failure
- [X] T077 [P] [US4] `tests/integration/test_action_lifecycle.py` — state transitions, actor recorded, no send without approval or allowlist (SC-011)

---

## Phase 11: US5 — Multi-tenant behaviour (Priority: P2)

- [X] T078 [US5] `backend/pulse/api/routers/admin.py` — per-tenant config and play allowlist management, operator role only
- [X] T079 [US5] Coverage reporting per tenant per source (FR-012)
- [X] T080 [P] [US5] `tests/integration/test_tenant_config_isolation.py` — a config change in one tenant alters only that tenant's behaviour
- [X] T081 [P] [US5] `tests/integration/test_missing_source_tenant.py` — the no-Gmail tenant scores with absent, not zero, email features

---

## Phase 12: US6 — Model report (Priority: P3)

- [X] T082 [US6] `backend/pulse/api/routers/model.py` — serve the promoted model card
- [X] T083 [P] [US6] `tests/contract/test_model_report.py` — report contains operating point, both baselines, calibration, per-tenant slices, lead time, seed and version

---

## Phase 13: Frontend

- [X] T084 Vite + React 19 + TS scaffold, typed API client generated against the OpenAPI schema
- [X] T085 [P] Queue page — ranked rows, tier, value at risk, days to renewal, dominant driver, delta since last cycle, below-the-cut count
- [X] T086 [P] Account page — driver bars, expandable feature values, evidence trail down to source payloads
- [X] T087 [P] Score-diff view — what moved and by how much
- [X] T088 [P] Draft review — draft beside its grounding evidence, approve/reject/edit
- [X] T089 [P] Run log — cycles with stage counts, declined decisions and durations
- [X] T090 [P] Low-confidence bucket as its own surface with reasons and remedies

---

## Phase 14: Hardening and delivery

- [X] T091 `infra/scripts/run_all.sh` — empty database → migrated → generated → ingested → trained → scored → serving (SC-014)
- [X] T092 Generate `contracts/openapi.yaml` from the application and commit it
- [X] T093 `quickstart.md` verified by running it from a clean state
- [X] T094 `README.md` — decisions, deliberately skipped, what breaks first at 10x
- [X] T095 Solution brief (one page) and the short deck — `docs/SOLUTION_BRIEF.md`, `docs/DECK.md` (markdown outline; no .pptx rendered)
- [X] T096 Loom walkthrough script — `docs/LOOM_SCRIPT.md` (script only; the recording itself is not done)
- [X] T097 Full suite green; record cycle duration over 5,000 accounts against SC-007

---

## Dependencies & Execution Order

- **Phase 1 → 2**: setup then foundation.
- **Phase 2 blocks everything.** Isolation and the session posture are correctness
  properties of the schema, not features layered on top.
- **Phase 3 before Phase 4** by deliberate choice: the generator is the adversary, and
  ingestion written against clean data and patched later is ingestion with latent bugs.
- **Phases 5, 6 before 7, 8**: features before model before ranking before display.
- **Phase 9** needs 5–8 complete, since the cycle orchestrates all of them.
- **Phases 10–12** are independent of each other once 9 lands.
- **Phase 13** needs the API surface stable (T092 ideally before T084).

### Parallel opportunities

- All of T011–T013 together once T010 lands.
- All of T032–T035 together once T031 lands.
- All of T042–T045 together once T038–T041 land.
- Frontend pages T085–T090 are independent files.
- Delivery documents T094–T096 are independent of code once the system runs.

---

## Implementation Strategy

**MVP = US1 + US2 + US3.** All three are P1 because the brief's failure modes map onto
them exactly: a queue nobody trusts (US2 missing), a queue nobody refreshes (US3
missing), or no queue at all (US1 missing) each reduce the system to the spreadsheet it
replaces. Stop and validate after Phase 9; everything after it is compounding value on
a foundation that already solves the stated problem.

**Deliberate ordering choice**: the test phases are not at the end. The five
constitutional properties — point-in-time correctness, fitted ranking, bounded
autonomy, tenant isolation, traceability — are each proven in the phase that creates
them, because a property tested later is a property that was never designed in.
