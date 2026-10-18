---
description: "Tasks: Hosted Demo and Reviewer Experience"
---

# Tasks: Hosted Demo and Reviewer Experience

**Input**: `specs/003-hosted-demo/spec.md`, `plan.md` · **Method**: strict TDD from AGENTS.md — every implementation task is preceded by a test task that is run and watched failing for the right reason; the full suite runs before a task group is called done.
**Format**: `- [ ] T### [P?] [US?] description with file path`. `[OWNER]` marks a step only the repository owner can do (account, key, upload); `[CONDITIONAL]` marks work done only if an earlier probe says it is needed.

## Phase 1: Setup

- [X] T001 Add `postgresql-client` to the backend image in `infra/docker/backend.Dockerfile`; verify `pg_dump --version` and `pg_restore --version` run inside the built `api` image (record the image-size change)
- [X] T002 [P] Record the three clarification decisions (seed as release asset; writable hosted demo with owner reset; Groq-written labelled seed drafts) as B-34 in `specs/001-renewal-risk-prioritisation/clarifications.md`

## Phase 2: Foundational

- [X] T003 Test first: `backend/tests/unit/test_seed_manifest.py` — the manifest (schema revision, per-table row counts, sha256, draft model name/date/source counts) round-trips to JSON, and a changed file fails the sha256 check
- [X] T004 Implement the manifest and checksum in `backend/pulse/seed.py` (stdlib only)

## Phase 3: User Story 1 — populated demo in under 10 minutes (P1)

**Goal**: clean clone → `up` → one load command → signed in with nine weeks of history, no backfill. **Independent test**: stopwatch run (T015).

- [X] T005 [US1] Test first: `backend/tests/integration/test_seed_guards.py` — loading is refused when tenants already exist (message names `--overwrite`), refused when the database's schema revision differs from the manifest's, refused on a sha256 mismatch; nothing is modified in any refusal
- [X] T006 [US1] Implement the guards in `backend/pulse/seed.py` (`check_loadable(session, manifest, file)`)
- [X] T007 [P] [US1] Test first: `backend/tests/unit/test_seed_export.py` — `export_seed` runs `pg_dump -Fc --no-owner` excluding `alembic_version` and writes the sidecar manifest (runner injected, no database needed)
- [X] T008 [US1] Implement `export_seed` in `backend/pulse/seed.py`
- [X] T009 [P] [US1] Test first: `backend/tests/unit/test_seed_load.py` — `load_seed` runs `pg_restore --data-only --no-owner`, then compares restored row counts with the manifest and raises on any mismatch; `--overwrite` empties tenant data first, never schema or roles (runner and counts injected)
- [X] T010 [US1] Implement `load_seed` (download-or-file, verify, optional overwrite, restore, verify counts) in `backend/pulse/seed.py`
- [X] T011 [US1] Test first (`backend/tests/unit/test_cli_seed.py`: arguments parse, `--overwrite` required wording) then wire `export-seed` and `load-seed` in `backend/pulse/cli.py`
- [X] T012 [US1] Docker acceptance (done 2026-10-18: seed loads in **15 s**; 13/13 browser scenarios pass; old password rejected; worker starts with 'model ready'): export from the demo database; fresh stack; migrate; `load-seed`; compare queue top rows, `/queue/snapshots` (≥ 9 days) and row counts with the source; run the 13 browser scenarios against it; then `load-seed --overwrite` after a change and confirm the reset
- [X] T013 [P] [US1] Write `docs/SEED_RELEASE.md` (how the seed is built, release-notes template with model/date/counts, how to attach it) and the quick path in `README.md` and `docs/DEMO_GUIDE.md` (Docker: `up` → `load-seed`; building from scratch stays documented)
- [X] T014 [US1] [OWNER] Publish the seed as a GitHub Release asset — **done 2026-10-18: release `seed-v1` exists on the (still private) repository; it downloads anonymously only once the repository is public (waiting on the owner's go-ahead)**; URL in README/DEMO_GUIDE/SEED_RELEASE, sha256 in the release notes
- [X] T015 [US1] Stopwatch (**measured 2026-10-18: fresh clone, empty Docker image cache, Apple silicon, Colima 4 CPU / 8 GB, seed loaded from a local file: 76 s cold build + start, 14 s load = 90 s to a signed-in demo; 13/13 browser scenarios pass.** Repeated 2026-10-18 from the PUBLIC repository, anonymous clone, empty cache, `load-seed --url`: **73 s** build + start, **244 s** download + verify + load (the 51 MB download dominated on this connection; the load itself is ~14 s) = **317 s (5 min 17 s)**; sign-in and the queue verified) a clean clone following only the documented seed path; record the measured time and conditions in `HANDOFF.md` and `docs/DEMO_GUIDE.md` (SC-001)

## Phase 4: User Story 2 — free hosted URL (P1)

**Goal**: the same demo at a free URL, limits stated. **Independent test**: the 13 browser scenarios against the URL (T022).

- [X] T016 [US2] Test first: `backend/tests/unit/test_hosted_app.py` — `/api/queue` is handled by the existing app with the prefix stripped (401 without a session, JSON); any other path serves the built UI, and an unknown non-API path falls back to `index.html`; an unknown `/api/…` path stays a JSON 404, never HTML
- [X] T017 [US2] Implement the wrapper in `backend/pulse/api/hosted.py`
- [X] T018 [US2] `infra/docker/hosted.Dockerfile` (multi-stage: build UI, then the Python image serving `pulse.api.hosted:app` on `$PORT`) and `infra/docker/hosted-entrypoint.sh` (migrate; if no tenants and `PULSE_SEED_URL` is set, load the seed); build it and record the image size
- [X] T019 [US2] Docker acceptance (done 2026-10-18: empty database to serving with the seed downloaded over HTTPS in **17 s**; 13/13 scenarios; 237 MB after the suite): run the hosted image beside the database locally, load the seed, run the 13 browser scenarios against its single port
- [X] T020 [P] [US2] `infra/render/probe.sh <DATABASE_URL>`: reports in under 10 seconds whether the database user can `CREATE ROLE` and `CREATE ROLE … BYPASSRLS` (cleaning up after itself); test it against the local database as a superuser and as a non-superuser CREATEROLE role
- [X] T021 [P] [US2] `render.yaml` (web service from the hosted Dockerfile + free Postgres; secrets as dashboard settings, not in the file) and the Render and Railway steps in `docs/HOSTING.md`, each step labelled verified or unverified
- [ ] T022 [US2] [OWNER] Create the Render database, run the probe, deploy the blueprint, load the seed, run the 13 scenarios against the URL; record the result and the cold-start time in `HANDOFF.md` (SC-002)
- [X] T023 [US2] [CONDITIONAL] **(done 2026-10-18: Render's first deploy failed with `permission denied to create role … Only roles with the BYPASSRLS attribute may create roles with the BYPASSRLS attribute`; migrations 0002/0005 now skip only the trainer role, `pulse.seed.rls_lifted` lifts FORCE for the load and restores it, 3+3 tests, verified with the real 5,000-account seed on a CREATEROLE-only cluster)** If the probe says `NEEDS-CHANGES` (roles can be created but not `BYPASSRLS`, and the user is not a superuser): the loader must also lift row-level security's FORCE on the tenant tables for the duration of the load transaction and restore it after (an owner is exempt from non-forced RLS), and migration 0002 must skip only the trainer role; test first (`backend/tests/integration/test_migration_roles_without_superuser.py`, a non-superuser CREATEROLE role runs the role step and the request role still comes out NOBYPASSRLS), then make migration 0002 skip only the trainer role
- [ ] T024 [US2] [CONDITIONAL] If Render cannot host it: repeat T022 on Railway (Hobby, $5) with the same image; record the monthly cost and credit burn observed
- [X] T025 [P] [US2] Cold-start UI: test first (`frontend/src/lib/coldStart.test.ts`: a slow or 502/503/504 first response is classified as "waking up", other errors are not) then show a "waking the demo, about a minute" state in `frontend/src/pages/Login.tsx` and `frontend/src/lib/useApi.ts`

## Phase 5: User Story 3 — free model, Anthropic by settings (P2)

**Goal**: one real Groq call and cycle; templates with no key; Anthropic is three variables. **Independent test**: T029.

- [X] T026 [US3] Test first: `backend/tests/unit/test_llm_check.py` against a local fake OpenAI-style server — success (prints model, latency, rate-limit headers when present), 401, timeout, and no key for a provider that needs one; exit codes distinguish them
- [X] T027 [US3] Implement `pulse llm-check` in `backend/pulse/llm_check.py` and `backend/pulse/cli.py`
- [ ] T028 [US3] [OWNER] Create a free Groq key and export it (`PULSE_LLM_API_KEY`) in the shell, never in chat or git; run `llm-check` for real; record the observed limits in `specs/003-hosted-demo/spec.md` Assumptions (FR-008)
- [ ] T029 [US3] Run one real cycle with Groq on the demo database with `llm_calls_per_cycle` lowered per tenant; count drafts by source; sample ten drafts and review grounding and tone; record counts and the review in `HANDOFF.md`; re-run with the key unset to confirm templates (SC-003)
- [ ] T030 [US3] Export the seed after T029 with the model name, date and draft counts in its manifest (FR-005b)

## Phase 6: Polish

- [ ] T031 [P] Update `README.md` (gaps and verification text), `docs/DEMO_GUIDE.md`, `docs/HOSTING.md`, `docs/LOOM_SCRIPT.md`, `docs/DECK.md`, `specs/001…/clarifications.md` B-34, and `HANDOFF.md`; every claim exercised or labelled unverified (SC-004)
- [ ] T032 Full backend, frontend and browser suites green; commit in themed commits; push

## Dependencies and order

Setup → Foundational → US1 → US2 (T016–T019 need only T010; T022 needs T014) → US3 (T026–T028 independent of US1/US2; T029 needs T028; T030 needs T008 and T029) → Polish. `[OWNER]` steps are the only blocking external dependencies: T014, T022, T028.

**Parallel**: T002; T007 ∥ T009; T013; T020 ∥ T021 ∥ T025; US3 T026–T027 can run beside US2.

## Implementation strategy

MVP = US1 (T001–T015): a reviewer gets the populated demo in minutes with no hosting at all. Then US2 for the URL, then US3. Do the verifiable work locally in Docker first; owner steps are batched at the end so they are one sitting, not scattered.
