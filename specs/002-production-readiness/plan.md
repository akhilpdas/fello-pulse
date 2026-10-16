# Implementation Plan: Production Readiness — Identity, Delivery, Drafting, Packaging

**Branch**: `002-production-readiness` (spec dir only; work on `main`) | **Date**: 2026-10-16 | **Spec**: [spec.md](spec.md)

**Input**: `specs/002-production-readiness/spec.md`, plus four spec-001 gaps found by `/speckit-analyze` (FR-018, FR-042, FR-047, FR-048) folded in as Phase 0 so they ship first.

## Summary

Make the delivered system safe to put in front of a real customer. Order is by risk: **close the
gaps spec 001 promised** (feedback, user suppression, leave-one-tenant-out; ownership arrives with
auth) → **authentication** (the credential, not the caller, decides tenant/user/role; CSM sees own
accounts) → **real email** behind that identity, safe by default → **real LLM drafting**, grounded and
falling back → **containers**, written but unverified. No change to ingestion features, the model,
scoring or ranking (constitution II).

## Technical Context

**Language/Version**: Python 3.14 (venv in use; constitution says 3.13 — see Complexity), TypeScript/React 19

**Primary Dependencies**: existing (FastAPI, SQLAlchemy, Alembic, psycopg, scikit-learn, Vite). **No new
runtime dependency for auth or email** (stdlib `hashlib.scrypt`, `secrets`, `hmac`, `smtplib`). One new
*optional* extra `llm = ["anthropic"]`, imported lazily (spec FR-025).

**Storage**: PostgreSQL 16; four migrations → add `0005`; new tables must join `TENANT_SCOPED_TABLES`.

**Testing**: pytest on `pulse_test` (never the demo DB), vitest. Real SMTP exercised against an
in-process fake SMTP server; the LLM against a scripted stand-in client. **No test calls a real
provider** (spec Assumptions).

**Target Platform**: macOS dev; Linux containers (unverified here — Docker not installed).

**Project Type**: web application (backend + frontend) + worker.

**Performance Goals**: auth adds one indexed lookup per request (<5 ms); LLM calls bounded so a cycle
still finishes inside its 15-minute interval (SC-011); today ~104 s for ~4,500 accounts.

**Constraints**: isolation must not depend on any client-supplied value (FR-002/003); no secret in the
repo, an image, a log or an API response (FR-021/033); non-container path must keep working (FR-035).

**Scale/Scope**: 3 tenants / ~5k accounts today; the login limiter is shared across instances through Postgres (research R-4, revised).

## Constitution Check

| Principle | Status | How |
|---|---|---|
| I Point-in-time | **Pass, with a test** | The new customer-contact fields are *not* features. A test asserts contact columns are unreachable from `features/` (extends the existing denylist test). Regenerating data changes numbers; they are re-run and re-quoted (R-8). |
| II Models rank, LLM writes | **Pass** | LLM client lives only in `agent/llm_drafter.py`, lazily imported; existing `test_no_llm_in_ranking` and `test_runs_without_llm` stay; new test: queue/scores identical with LLM off / on / failing (SC-009). |
| III Reviewed boundary | **Pass** | Real SMTP sits behind the same allowlist, suppression, rate limit and approval gate. Outbound defaults off per tenant; demo mode default on. Approvals now attributed to the credential. |
| IV Isolation below the app | **Pass, strengthened** | The tenant claim now derives from a verified session, still set transaction-local. Sessions/audit/opt-outs are tenant-scoped tables under RLS. No `SECURITY DEFINER` bypass (R-2). Login resolves workspace slug → id from the global `tenant` table. |
| V Nothing unexplained | **Pass** | Every draft records provenance (template/LLM, model, rejection reason, original vs edited text). |

No violation requires a Complexity Tracking waiver; two honest deviations are listed below.

## Project Structure

### Documentation (this feature)

```text
specs/002-production-readiness/
├── spec.md · plan.md · research.md · data-model.md · quickstart.md
├── contracts/api-changes.md
├── checklists/requirements.md
└── tasks.md            # /speckit-tasks
```

### Source Code

```text
backend/pulse/
├── auth/            # NEW  passwords.py (scrypt) · sessions.py · principal.py · limiter.py · audit.py
├── api/
│   ├── deps.py            # CHANGED  get_principal replaces header trust; get_session(principal)
│   └── routers/auth.py, feedback.py, suppression.py (NEW); admin.py/actions.py/queue.py/accounts.py CHANGED
├── agent/
│   ├── transport.py       # + SmtpTransport; send state machine
│   ├── llm_drafter.py     # real client + validate_llm_output
│   └── drafter.py         # facts-aware grounding
├── ml/evaluate.py, pipeline.py   # leave-one-tenant-out (FR-018)
├── ingest/dimension.py           # contact fields
└── db/migrations/versions/0005_auth_delivery_contacts.py
generator/                      # + primary contact per account (some missing)
frontend/src/                   # Login, session context, feedback/suppress actions
infra/docker/ + docker-compose.yml   # UNVERIFIED
backend/tests/{unit,integration,isolation,contract}/
```

**Structure Decision**: extend the existing backend/frontend layout; one new package `pulse/auth/`.
Domain logic (password policy, grounding validator, send state machine) stays pure and IO-free per the
constitution's Boundaries rule; routers and the SMTP/LLM clients are adapters.

## Phases (strict TDD — AGENTS.md; each task writes its failing test first)

| Phase | Delivers | Spec refs |
|---|---|---|
| **0 Gaps from spec 001** | `POST /accounts/{id}/feedback`, `POST /accounts/{id}/suppress` + UI actions; leave-one-tenant-out in the model card; fix T039/T096 wording | 001: FR-047, FR-048, FR-018 |
| **1 Auth (US1)** | credentials, sessions, principal, role + ownership enforcement, audit, login UI, header-trust removed, all tests migrated | FR-001–012, FR-042(001) |
| **2 Email (US2)** | contact in data, sender config, SMTP transport, send state machine, opt-out, demo mode | FR-013–023 |
| **3 LLM (US3)** | facts-aware grounding, Anthropic client, validation + fallback, bounds, provenance | FR-024–030 |
| **4 Packaging (US4)** | Dockerfiles, compose, entrypoint, docs marked UNVERIFIED | FR-031–035 |
| **5 Honesty** | README skipped-list split; clarifications; re-run `run_all.sh`, re-quote metrics; analyze | FR-036 |

## Deviations recorded (not constitutional)

| Deviation | Why | Alternative rejected |
|---|---|---|
| FR-018/SC-006 weakened: SMTP gives no idempotency, so an ambiguous outcome (timeout after the message body was sent) becomes `send_unconfirmed`, **never auto-retried**, and surfaces to a human | Auto-retry would risk a duplicate customer email; a rare manual re-send is safer | Auto-retry (violates "exactly once"); an idempotent API provider (not available provider-neutrally). Spec FR-018 reworded accordingly. |
| Python 3.14 in use vs constitution's 3.13 | Pre-existing environment fact; suite is green on it | Downgrading mid-project for no defect |
