---
description: "Task list for 002-production-readiness"
---

# Tasks: Production Readiness — Identity, Delivery, Drafting, Packaging

**Input**: `spec.md`, `plan.md`, `research.md`, `data-model.md`, `contracts/api-changes.md`, `quickstart.md`

**IDs** start at T201 so they never collide with spec 001's T001–T101.

**Strict TDD (AGENTS.md).** Every `RED` task is a test written first, run, and watched to fail *for the
stated reason* before its `GREEN` task. A `RED` task names the production change that would make it fail.
A `GUARD` task is a regression test over behaviour that already exists — it is expected to pass immediately and
is labelled so, never presented as test-first. Run the **full** suite (`python3 -m pytest -q` from `backend/`;
`npm test` from `frontend/`) before ticking any `GREEN`.

**Traceability.** Every task cites the requirement it serves: `FR-0nn`/`SC-0nn` are this spec's;
`001/FR-0nn` are spec 001's. `[P]` = different files, no dependency on an unfinished task.

**Story labels**: `[GAP]` spec-001 gaps · `[US1]` identity · `[US2]` email · `[US3]` LLM · `[US4]` containers.

## Phase 0 — Spec-001 gaps found by `/speckit-analyze` (ships first)

**Goal**: the four requirements spec 001 promised and did not build (001/FR-018, 001/FR-042, 001/FR-047,
001/FR-048) are built or honestly dropped. 001/FR-042 (ownership) is delivered in Phase 2 (T235).

- [x] T201 [P] [GAP] RED `backend/tests/integration/test_feedback.py` — `POST /accounts/{id}/feedback {kind,note}` stores a `feedback` row (kind ∈ false_positive|true_positive|not_actionable, linked to the account's latest score, author = caller); bad kind → 422; another tenant's account → 404. Fails: route missing. (001/FR-047)
- [x] T202 [GAP] GREEN `backend/pulse/api/routers/feedback.py` + register in `api/main.py`. (001/FR-047)
- [x] T203 [P] [GAP] RED `backend/tests/integration/test_account_suppression.py` — `POST /accounts/{id}/suppress {reason,expires_at}` removes the account from `/queue` but its score still exists; empty reason or past expiry → 422; `DELETE` lifts it; expired suppression no longer hides it. Fails: route missing. (001/FR-048)
- [x] T204 [GAP] GREEN `backend/pulse/api/routers/suppression.py` (writes `suppression`; scoring untouched). (001/FR-048)
- [x] T205 [P] [GAP] RED `frontend/src/api/__tests__/gaps.test.ts` — client functions `postFeedback`, `suppressAccount` send the right method/path/body and surface error detail. Fails: functions missing. (001/FR-047, 001/FR-048)
- [x] T206 [GAP] GREEN `frontend/src/api/client.ts` + `frontend/src/pages/AccountPage.tsx` — "Mark false positive" and "Suppress…" (reason + days) actions. (001/FR-047, 001/FR-048)
- [x] T207 [P] [GAP] RED `backend/tests/unit/test_leave_one_tenant_out.py` — `evaluate.leave_one_tenant_out(rows_by_tenant, train_fn)` trains once per tenant on the *other* tenants only (assert via a spy that the held-out tenant's rows never reach `train_fn`) and returns `{tenant: {auc, precision_at_capacity}}`; a tenant with no positives reports `null`, not 0. Fails: function missing. (001/FR-018, R-14)
- [x] T208 [GAP] GREEN `backend/pulse/ml/evaluate.py` (pure, IO-free). (001/FR-018)
- [x] T209 [GAP] RED `backend/tests/integration/test_model_report_loto.py` — `GET /model` returns `leave_one_tenant_out` list from the promoted card; absent card section reads "unavailable" with a reason. Fails: key missing. (001/FR-018)
- [x] T210 [GAP] GREEN `backend/pulse/ml/pipeline.py` writes the section into the card; `backend/pulse/api/routers/model.py` serves it; record the measured extra training time in the card. (001/FR-018)
- [x] T211 [GAP] Correct spec-001 bookkeeping: reword `specs/001-…/tasks.md` T039 (lead time is dropped — B-21; leave-one-tenant-out now delivered by T207–T210) and T096 (script only, not a recording); add Phase 15 to 001 `tasks.md` listing T098–T101 → T201–T210/T235; add `clarifications.md` entry B-25 stating the four gaps and their resolution. (Constitution: Delivery Workflow §4)

**Checkpoint**: full suite green; the three behaviours are demonstrable in the UI/API.

## Phase 1 — Foundational schema (blocks Phases 2–4)

- [x] T212 RED `backend/tests/integration/test_migration_0005.py` — every column/table in `data-model.md` exists with the stated types, nullability and defaults (`outbound_enabled` false, `demo_mode` true, `llm_calls_per_cycle` 50); new tables are in `TENANT_SCOPED_TABLES` and have RLS FORCEd. Fails: migration missing. (FR-003, FR-013, FR-014, FR-023, FR-029)
- [x] T213 GREEN `backend/pulse/db/migrations/versions/0005_auth_delivery_contacts.py` + `db/models.py` (`AppSession`, `AuditEvent`, `ContactOptOut`; new columns) + `TENANT_SCOPED_TABLES`. `audit_event`: INSERT/SELECT only for the app role. (data-model.md)
- [x] T214 GREEN `backend/tests/conftest.py` — `two_tenants` seeds a row in each new table for both tenants, so the existing isolation suite proves zero foreign rows for them (SC-001, 001/FR-038). Verify the isolation suite fails if a new table's policy is removed (mutation, record in `docs/VERIFICATION.md`).
- [x] T215 [P] RED `backend/tests/unit/test_settings_secrets.py` — new settings exist with the stated defaults (`session_hours` 12, `llm_enabled` false, `llm_model` `claude-sonnet-5-5`); `smtp_password`, `llm_api_key` have no default and never appear in `repr()`/`str()` of `Settings`. Fails: settings missing. (FR-021)
- [x] T215a GREEN `backend/pulse/config.py` — add `session_hours`, `login_max_failures`, `login_window_seconds`, `smtp_host/port/user/password/starttls`, `llm_enabled`, `llm_model`, `llm_api_key`, `cookie_secure` using `SecretStr` for secrets. (FR-021)

## Phase 2 — US1: a real person signs in (P1, MVP)

**Goal**: tenant, user and role come only from a verified credential.
**Independent test**: with only this phase built, a forged tenant/user id has no effect and an approval records the authenticated user.

- [x] T216 [P] [US1] RED `backend/tests/unit/test_passwords.py` — scrypt hash is salted (same password → different hashes), parameters embedded, `verify` true/false, constant-cost verify for "no such user"; policy: ≥12 chars, not equal to the email, not in a deny-list of common passwords. Fails: module missing. (FR-007)
- [x] T217 [US1] GREEN `backend/pulse/auth/passwords.py` (pure; stdlib `hashlib.scrypt`). (FR-007)
- [x] T218 [P] [US1] RED `backend/tests/integration/test_sessions.py` — a token is `<tenant_id>.<secret>`; only `sha256(secret)` is stored; expired and revoked sessions fail; a forged tenant prefix with a real secret finds nothing (RLS) and returns "no session" without doing tenant work. Fails: module missing. (FR-008, FR-003, R-2)
- [x] T219 [US1] GREEN `backend/pulse/auth/sessions.py`. (FR-008, FR-003)
- [x] T220 [P] [US1] RED `backend/tests/unit/test_login_limiter.py` — after N failures per (address, workspace, email) within the window further attempts are refused until it slides; unknown and known identities behave identically. Fails: module missing. (FR-007, R-4)
- [x] T221 [US1] GREEN `backend/pulse/auth/limiter.py` (documented single-process limit). (FR-007)
- [x] T222 [US1] RED `backend/tests/integration/test_auth_routes.py` — `POST /auth/login` sets an `HttpOnly; SameSite=Strict` cookie and returns user+tenant; wrong password, unknown email and unknown workspace return the **same** 401 body and timing class; limited → 429; `GET /auth/me`; `POST /auth/logout` revokes (next request 401). Fails: routes missing. (FR-001, FR-007, FR-008)
- [x] T223 [US1] GREEN `backend/pulse/api/routers/auth.py` + `backend/pulse/auth/principal.py` (`Principal{tenant_id,user_id,role}`), `api/deps.py::get_principal`. (FR-001)
- [x] T224 [US1] GREEN test helper `backend/tests/auth_helpers.py::login_as(tenant_id, user_id)` creating a real session row and returning cookies; **migrate every existing test that sends `X-Tenant-Id`/`X-User-Id`** to it. Done before T225 so the suite stays green. (FR-002)
- [x] T225 [US1] RED `backend/tests/integration/test_identity_forgery.py` — with Northwind's session: a Globex `X-Tenant-Id`/`X-User-Id` (header, query, body) changes nothing; no cookie, expired, tampered, and forged-prefix tokens → 401 and **zero** tenant-scoped queries issued (spy on `tenant_session`); (the `tenant_mismatch` audit event is asserted in T240). Fails today: headers are trusted. (FR-002, FR-003, SC-001, SC-002)
- [x] T226 [US1] GREEN `api/deps.py` — `get_session(principal)` sets the claim from the principal; delete all header reading; route list updated. (FR-002, FR-003)
- [x] T227 [P] [US1] RED `backend/tests/contract/test_every_route_requires_auth.py` — iterate `app.routes`; every route except `/auth/login`, `/docs`, `/openapi.json` returns 401 without a session. Fails for any route still unguarded. (SC-002)
- [x] T228 [US1] GREEN apply `get_principal` to every router (`queue`, `accounts`, `actions`, `admin`, `model`, `runs`, `feedback`, `suppression`). (FR-001)
- [x] T227a [US1] RED+GREEN `backend/tests/integration/test_csrf.py` — a state-changing request authenticated by the **cookie** without `X-Requested-With` → 403; with it → allowed; a bearer-token request and any GET are exempt. Fails: cookie auth accepted cross-site. (FR-001, R-5) — added after planning: `SameSite=Strict` alone is not the only control we promised.
- [x] T229 [P] [US1] RED `backend/tests/integration/test_roles.py` — a `csm` gets 403 on `/admin/*` and `/model`; an `operator` gets 200 on all of them. Fails: `require_operator` still reads `X-User-Id`. (FR-004, SC-003)
- [x] T230 [US1] GREEN `routers/admin.py::require_operator` via the principal. (FR-004)
- [x] T231 [P] [US1] GUARD `backend/tests/integration/test_demo_owner_coverage.py` — in the demo DB every CRM owner ref has a matching `app_user` (the precondition for FR-005; R-6). Expected to pass; if it fails, FR-005 degrades and that is written in `clarifications.md`. (FR-005)
- [x] T232 [US1] RED `backend/tests/integration/test_csm_scoping.py` — a `csm` sees only `owner_user_id = self` in `/queue`, `/queue/low-confidence`, `/actions`, `/accounts/{id}`, evidence, score-diff; another owner's account → **404**; an `operator` sees all; unowned accounts operator-only. Fails: no ownership filter anywhere. (FR-005, 001/FR-042)
- [x] T233 [US1] GREEN one shared helper `backend/pulse/api/visibility.py::visible_accounts(principal)` used by every account-level query. (FR-005, 001/FR-042)
- [x] T234 [P] [US1] RED `backend/tests/integration/test_actor_is_principal.py` — approve/reject/edit ignore `actor_user_id` in the body; `decided_by_user_id` equals the session user. Fails: body is trusted. (FR-006, SC-004)
- [x] T235 [US1] GREEN remove `actor_user_id` from request models in `routers/actions.py`; regenerate contract. (FR-006)
- [x] T236 [P] [US1] RED `backend/tests/integration/test_session_liveness.py` — disabling a user or demoting an operator takes effect on their next request (no waiting for expiry). Fails: nothing re-reads user state per request. (FR-008)
- [x] T237 [US1] GREEN `principal.py` re-reads `app_user.disabled_at`/`role` each request (one indexed lookup). (FR-008)
- [x] T238 [P] [US1] RED `backend/tests/integration/test_user_admin.py` — operator creates/disables/changes role/resets password for users **of their own tenant only**; a user id from another tenant → 404; password policy enforced; new user can sign in. Fails: routes missing. (FR-009)
- [x] T239 [US1] GREEN `routers/admin.py` `/admin/users` (+ audit events). (FR-009, FR-012)
- [x] T240 [P] [US1] RED `backend/tests/integration/test_audit_trail.py` — login ok/failed, logout, forbidden, mismatch, role change are recorded with actor kind; `GET /admin/audit` is operator-only and tenant-scoped. Fails: nothing writes `audit_event`. (FR-012)
- [x] T241 [US1] GREEN `backend/pulse/auth/audit.py` + `GET /admin/audit`. (FR-012)
- [x] T242 [P] [US1] RED `backend/tests/integration/test_worker_identity.py` — cycle-created actions have `actor_kind = system` and no user; the worker runs with no session; a user session cannot trigger or alter a cycle. Fails: actor not recorded as system. (FR-010)
- [x] T243 [US1] GREEN `agent/cycle.py` records the system actor; docs note the worker's deployment-level identity. (FR-010)
- [x] T244 [P] [US1] RED `frontend/src/__tests__/auth.test.ts` — `login` posts workspace/email/password with credentials, a 401 clears the session and shows the sign-in form, operator-only nav hidden for `csm`. Fails: modules missing. (FR-011)
- [x] T245 [US1] GREEN `frontend/src/auth/` (`AuthContext`, `LoginPage`, logout) — remove the paste-ids bar and the `X-*` headers from `api/client.ts`; add `X-Requested-With` to state-changing requests. (FR-011, R-5)
- [x] T246 [US1] GREEN `infra/scripts/run_all.sh` + `pulse.cli` — create demo users with passwords (from `PULSE_DEMO_PASSWORD` or generated and printed once; never committed or logged to files); `bootstrap` test asserts users have a hash. (FR-007, FR-009)
- [x] T247 [US1] GREEN regenerate `contracts/openapi.yaml` (drift test), update `quickstart.md`, VS Code task "show demo tenant + user ids" → "show demo sign-ins". (SC-005)
- [x] T248 [US1] Mutation-verify auth (3 each, recorded in `docs/VERIFICATION.md`): trust `X-Tenant-Id` again; skip the ownership filter; read `actor_user_id` from the body — each must turn a named test red. (SC-001, SC-004)

**Checkpoint (MVP)**: full backend + frontend suites green; sign in through the UI; queue shows only the CSM's accounts.

## Phase 3 — US2: an approved draft is actually delivered (P2)

**Goal**: approval sends a real message, once, safely, from the right sender.
**Independent test**: against an in-process fake SMTP server, one approval → exactly one message; broken server → `send_failed`.

- [x] T249 [P] [US2] RED `generator/tests/test_contacts.py` — generator emits `primary_contact {name,email}` in `Account.updated` for ≈90% of accounts (deterministic per seed), the rest deliberately none. Fails: field missing. (FR-023)
- [x] T250 [US2] GREEN `generator/emit.py`/`spec.py`. (FR-023, R-8)
- [x] T251 [P] [US2] RED `backend/tests/integration/test_ingest_contact.py` — ingestion populates `account.contact_name/email`; accounts without a contact stay NULL (no placeholder). Fails: ingestion ignores it. (FR-015, FR-023)
- [x] T252 [US2] GREEN `backend/pulse/ingest/dimension.py`. (FR-023)
- [x] T253 [P] [US2] GUARD `backend/tests/leakage/test_contact_not_a_feature.py` — contact columns are unreachable from `features/` (extends the denylist test). Passes immediately; protects constitution I. (R-8)
- [x] T254 [P] [US2] RED `backend/tests/unit/test_smtp_transport.py` — against the in-process fake SMTP server: exactly one message with From = sender, To = recipient, the subject/body, and `Message-ID` derived from the action id; credentials come from settings only. Fails: class missing. (FR-013, FR-021)
- [x] T255 [US2] GREEN `backend/pulse/agent/transport.py::SmtpTransport` (stdlib `smtplib`, STARTTLS, timeouts) + `backend/pulse/tools/smtp_sink.py` (the fake server, also used by the quickstart). (FR-013, R-9)
- [x] T256 [P] [US2] RED `backend/tests/unit/test_send_failure_classes.py` — connect-refused/4xx → `transient`; 5xx → `permanent`; timeout after the body was sent → `ambiguous`. Retry ≤3 only for transient; ambiguous never retried. Fails: `SendResult` has no `kind`. (FR-017, FR-018)
- [x] T257 [US2] GREEN `SendResult.kind` + `send_with_retry` honouring it. (FR-017, FR-018)
- [x] T258 [P] [US2] RED `backend/tests/unit/test_send_gate.py` — pure `decide_send(tenant_cfg, contact, opted_out, demo)` returns `ok | not_configured | outbound_disabled | no_recipient | opted_out`; each reason is distinct; no I/O. Fails: module missing. (FR-014, FR-015, FR-016)
- [x] T259 [US2] GREEN `backend/pulse/domain/send_gate.py`. (FR-014–016)
- [x] T260 [US2] RED `backend/tests/integration/test_approve_delivers.py` — approve for a configured tenant → one message at the sink, action `sent` with time/attempts/provider id; each gate state ends in its own `state` with **zero** network calls (SC-007); a second approve returns the first result; two concurrent approves → one message; `send_unconfirmed` for an induced ambiguous failure and no auto re-send (SC-006); config disabled between approve and send → `outbound_disabled`. Fails: approve calls the stub with a placeholder recipient. (FR-013–018, SC-006, SC-007)
- [x] T261 [US2] GREEN `routers/actions.py::approve` — atomic `UPDATE … WHERE state='drafted' RETURNING`, gate, send, record; delete `csm+<id>@example.test`. (FR-013–018, R-10)
- [x] T262 [P] [US2] RED `backend/tests/integration/test_demo_mode.py` — with `demo_mode` true every message goes only to `test_inbox` (or is captured with no inbox), subject prefixed `[DEMO → <original>]`, `redirected_to` recorded; databases built by the generator default to demo; **zero** messages reach a contact's real address across a full cycle (SC-008). Fails: no redirect. (FR-020, SC-008)
- [x] T263 [US2] GREEN demo redirect in the send path + `run_all.sh` leaves `demo_mode=true`. (FR-020, R-12)
- [x] T264 [P] [US2] RED `backend/tests/integration/test_outbound_settings.py` — `GET/PATCH /admin/outbound` operator-only; enabling is refused unless `sender_address` is set and `sender_verified`; only an operator can verify; every change audited. Fails: routes missing. (FR-014, FR-004, FR-012)
- [x] T265 [US2] GREEN `routers/admin.py` outbound settings. (FR-014)
- [x] T266 [P] [US2] RED `backend/tests/integration/test_opt_out.py` — `POST/GET/DELETE /admin/opt-outs`; an opted-out contact is not sent to on approve **or** autonomous send; every message carries the opt-out footer. Fails: routes/footer missing. (FR-016)
- [x] T267 [US2] GREEN `contact_opt_out` handling + footer in `agent/transport.py` message builder. (FR-016, R-11)
- [x] T268 [US2] RED `backend/tests/integration/test_autonomy_boundary_real_transport.py` — with `SmtpTransport`: an un-allowlisted play cannot self-send; suppression window, per-cycle rate limit and mid-cycle revocation still hold; every declined decision is recorded. (Principle III, FR-019). May pass immediately → label GUARD if so, and say so in the commit.
- [x] T269 [US2] RED `backend/tests/unit/test_transport_selection.py` — `select_transport(settings, tenant_cfg)` returns `SmtpTransport` only when SMTP is configured **and** the tenant has outbound enabled and a verified sender; otherwise `RecordingTransport`; with nothing configured the system still runs. Fails: function missing. (FR-014, FR-022)
- [x] T269a [US2] GREEN `api/deps.py::get_transport` and `agent/worker.build_runtime` use `select_transport`. (FR-022)

- [x] T270 [P] [US2] RED `backend/tests/integration/test_no_secrets_leak.py` — set recognisable SMTP/LLM secrets; assert they appear in no API response, `agent_run` row, log line or exception message. Fails if any path echoes them. (FR-021)
- [x] T271 [P] [US2] RED `frontend/src/__tests__/drafts_states.test.ts` — Drafts shows `redirected_to`, `send_unconfirmed` (with "check the provider before re-sending") and each blocked state in plain words. (FR-013, FR-018)
- [x] T272 [US2] GREEN `frontend/src/pages/DraftsPage.tsx`. (FR-013)
- [x] T273 [US2] Mutation-verify the send path (3, recorded): bypass the gate; ignore demo redirect; allow auto-retry on ambiguous — each must turn a named test red. (SC-006–SC-008)

## Phase 4 — US3: drafts written by a model, only from the evidence (P3)

**Goal**: real model prose, grounded, with a deterministic fallback; ranking untouched.

- [x] T274 [P] [US3] RED `backend/tests/unit/test_grounding_facts.py` — `build_facts(score)` yields short deterministic strings from the account's top drivers (e.g. "3 support tickets in the last 28 days"); contains **no** raw ticket/email text. Fails: grounding holds driver names only. (FR-024, FR-030)
- [x] T275 [US3] GREEN `backend/pulse/agent/grounding.py` + `cycle.py` stores `facts` in `action.grounding`. (FR-024)
- [x] T276 [P] [US3] RED `backend/tests/unit/test_validate_llm_output.py` — rejects an unseen number, date or percentage, any URL or markup, instruction-like text, over-length, and `claims` outside the evidence; accepts a grounded draft; each rejection returns a reason. Fails: function missing. (FR-026, SC-010)
- [x] T277 [US3] GREEN `backend/pulse/agent/drafter.py::validate_llm_output` (pure). (FR-026)
- [x] T278 [P] [US3] RED `backend/tests/unit/test_llm_prompt_isolation.py` — with a scripted client, the prompt contains the facts and constraints and **not** ticket text containing "ignore previous instructions" (prompt-injection guard); output parsed as `{subject,body,claims}`. Fails: no client. (FR-030)
- [x] T279 [US3] GREEN `backend/pulse/agent/llm_drafter.py::draft_with_llm(client=…)` — lazy `anthropic` import, injected client for tests, `pyproject` extra `llm`. (FR-024, R-13)
- [x] T280 [P] [US3] RED `backend/tests/integration/test_llm_fallback.py` — no key, disabled, provider error, timeout, empty reply, bad JSON, invalid key/over quota, and a validation failure each yield the template draft; `draft_fallback_reason` recorded; the cycle completes; the run record counts fallbacks. Fails: `draft_with_llm` raises today. (FR-027, SC-011)
- [x] T281 [US3] GREEN fallback + provenance (`draft_source`, `draft_model`, `draft_fallback_reason`) in `agent/cycle.py`. (FR-027, FR-029)
- [x] T282 [P] [US3] RED `backend/tests/integration/test_llm_bounds.py` — with a slow/failing stand-in the cycle makes ≤ `llm_calls_per_cycle` calls, opens a breaker after consecutive failures, serves the rest from templates, and still finishes inside a bound. Fails: unbounded. (FR-028, SC-011)
- [x] T283 [US3] GREEN per-cycle cap, per-call timeout, breaker. (FR-028)
- [x] T284 [US3] RED `backend/tests/integration/test_ranking_invariant_to_llm.py` — same data scored with the model off, on, and failing: scores, tiers, deltas and queue order byte-identical for every account. (SC-009, FR-025, Principle II). GUARD if it passes immediately.
- [x] T285 [P] [US3] GUARD extend `backend/tests/unit/test_no_llm_in_ranking.py` to cover the new modules (`grounding`, `llm_drafter`) — neither is importable from `features/`, `scoring/`, `ml/`, `domain/ranking`. (FR-025)
- [x] T286 [P] [US3] RED `backend/tests/integration/test_edit_keeps_original.py` — editing a model-written draft stores the original once and the edited text; sending uses the edit. Fails: original overwritten. (FR-029)
- [x] T287 [US3] GREEN `routers/actions.py::edit`. (FR-029)
- [x] T288 [US3] Document the manual live check (needs a key) in `quickstart.md`; no automated test calls a real provider. (Assumptions)

## Phase 5 — US4: one command runs it in containers (P4) — UNVERIFIED here

**Goal**: files written and statically checked; **not run** (Docker is not installed). Every doc says so until run.

- [x] T289 [P] [US4] RED `backend/tests/unit/test_container_files.py` — static checks: compose parses; services `db`, `api`, `worker`, `web` exist; db has a healthcheck and the others `depends_on: condition: service_healthy`; a named volume holds Postgres data; no password literal other than `${VAR:-dev}` defaults; images do not `COPY` `data/`, `artifacts/` or `.env`; `.dockerignore` excludes them. Fails: files missing. (FR-031, FR-033)
- [x] T290 [P] [US4] GREEN `infra/docker/backend.Dockerfile` (multi-stage; API and worker share the image) + `infra/docker/entrypoint.sh` (wait for db, `alembic upgrade head`). (FR-031)
- [x] T291 [P] [US4] GREEN `infra/docker/frontend.Dockerfile` (build → nginx, `/api` proxied to `api`). (FR-031)
- [x] T292 [US4] GREEN `docker-compose.yml` + `.dockerignore`. (FR-031, FR-033)
- [x] T293 [US4] RED `backend/tests/unit/test_cli_bootstrap_demo.py` + GREEN `pulse.cli bootstrap-demo` — the `run_all.sh` stages as one CLI command usable inside a container; same seed → same estate. (FR-032)
- [x] T294 [US4] Mark **UNVERIFIED** in `README.md`, `quickstart.md`, `HANDOFF.md`; add a "first run on a machine with Docker" checklist and where to record the result. (FR-034, SC-012)
- [x] T295 [US4] GUARD re-run `bash infra/scripts/run_all.sh` on a fresh DB and the VS Code tasks — the non-container path still works unchanged. (FR-035)

## Phase 6 — Honesty and delivery

- [x] T296 Rebuild `pulse` and `pulse_test` with `run_all.sh` (the generator changed, so the estate changed — R-8); re-run training; **re-quote every metric** (precision@100, ROC-AUC, captured value, cycle time) in `README.md`, `docs/SOLUTION_BRIEF.md`, `docs/DECK.md`, `HANDOFF.md`, and rebuild `docs/Pulse_deck.pptx`. (R-8, SC-013)
- [x] T297 Split `README.md` "Deliberately skipped" into **Decisions (with reasons)** and **Gaps (not done)**; add what 002 closed and what it did not (SSO, MFA, self-service reset, bounce/reply handling, per-tenant SMTP secrets at rest, shared login limiter, live LLM/real inbox are manual checks, containers unverified). (FR-036, SC-013)
- [x] T298 `clarifications.md`: entries for sessions-over-JWT, workspace login, contacts source, SMTP limits, opt-out limits, FR-018 deviation, per-process limiter, demo-mode default, token-prefix design. (FR-036)
- [x] T299 `HANDOFF.md` status + `docs/VERIFICATION.md` (what was mutation-verified, what was GUARD-only, what is unverified). (AGENTS.md)
- [x] T300 Re-run `/speckit-analyze` on 002; resolve every CRITICAL/HIGH or write it down. (Delivery Workflow §4)
- [x] T301 Full suites green (`python3 -m pytest -q`, `npm test && npm run build`); ask before committing/pushing.

## Phase 7 — gaps the owner questioned, closed after the main plan (added 2026-10-16)

- [x] T302 [US1] RED+GREEN `frontend/e2e/app.spec.ts` + `playwright.config.ts` + `infra/scripts/e2e.sh` — the real UI driven in real Google Chrome against the real API and a scratch copy of the demo DB: 9 scenarios (sign-in/out, wrong password, operator queue, account actions, operator pages, approving a draft in demo mode, CSM scoping + 403). It found a real bug (the audit panel went stale) fixed in T303. (FR-011, SC-005)
- [x] T303 [US1] RED+GREEN `frontend/src/pages/Admin.tsx`, `src/api/admin.ts`, `src/lib/nav.ts` (+ tests) — operator pages for outbound settings, opt-outs, users and the audit trail; role-based navigation. (FR-004, FR-009, FR-011, FR-012, FR-014, FR-016)
- [x] T304 [US1] RED+GREEN `pulse.auth.limiter.PgLoginLimiter` + migration `0006` + `tests/integration/test_pg_login_limiter.py` — login rate limiting shared across API instances; only a hash is stored. Closes the per-process limit stated in R-4. (FR-007)
- [x] T305 RED+GREEN `pulse.ml.pipeline.panel_account_ids` + `tests/integration/test_panel_order_is_deterministic.py` — the panel was built in physical-layout order, so the same data gave precision@100 0.196–0.326 across rebuilds. Now ordered by external ref. (B-27; constitution: determinism)

## Dependencies and order

```text
Phase 0 (gaps)  ─┐
                 ├─▶ Phase 1 (schema) ─▶ Phase 2 US1 (auth, MVP) ─▶ Phase 3 US2 (email) ─▶ Phase 4 US3 (LLM)
                 │                                                                      └▶ Phase 5 US4 (containers; independent)
                 └──────────────────────────────────────────────────────────────────────────▶ Phase 6 (docs, re-run, analyze)
```

- Phase 0 uses header identity (still in place) and is **migrated to sessions in T224**.
- Phase 2 must finish before Phase 3: real mail on forgeable identity is the thing this feature exists to avoid.
- Phase 4 depends on Phase 3 only through `action` columns (T213) and the cycle's draft path.
- Phase 5 is independent of 2–4 and can run any time after Phase 1; it is last because it cannot be verified here.

**Parallel examples**: T201 ∥ T203 ∥ T207; T216 ∥ T218 ∥ T220; T249 ∥ T254 ∥ T256 ∥ T258; T274 ∥ T276 ∥ T278; T289 ∥ T290 ∥ T291.

## Implementation strategy

1. **MVP = Phase 0 + 1 + 2.** Gaps closed, identity real. Stop and demonstrate before touching email.
2. Then email (safe by default, demo mode on), then LLM, then packaging.
3. Each phase ends with: full suites green → manual scenario from `quickstart.md` → write down anything not done.

## Counts

Total **108 tasks**, **108 done**. Guards (pass on first run, not test-first): T231, T253, T268\*, T284\*, T285, T295 and the reconcile/empty-key guards added later.
Of these, tasks labelled GUARD (expected to pass immediately, not test-first): T231, T253, T268\*, T284\*, T285, T295 (\* if it passes first time).
