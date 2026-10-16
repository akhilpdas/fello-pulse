# Verification log

Evidence that the tests prove what they claim. A green suite only means the
assertions did not fire; this file records the deliberate breakages that confirm
they *would*.

## Tenant isolation (constitution IV)

Three realistic regressions were introduced against a live database and the
suite re-run. Each is a thing that happens in real systems: a migration that
enables RLS but forgets FORCE, a table whose policy is dropped during a
refactor, and an operations change that grants the application role broader
rights to "fix" a permissions error.

| Mutation | Why it is realistic | Result |
|---|---|---|
| `ALTER TABLE account NO FORCE ROW LEVEL SECURITY` | ENABLE without FORCE is the common mistake; the owner silently bypasses its own policy | **1 failure** — `test_every_tenant_scoped_table_has_rls_enabled_and_forced` |
| `DROP POLICY tenant_isolation ON score` | A table loses its policy in a refactor and nothing visibly breaks | **5 failures** across three files, including the unfiltered-select and join tests |
| `ALTER ROLE pulse_app BYPASSRLS` | Granting the app role more rights to clear a permissions error | **11 failures** — nearly the whole suite |

Restored to the correct configuration: **17 passed**.

The third mutation is the important one. Granting BYPASSRLS is exactly the
change someone makes under time pressure when a query returns no rows, and it
silently converts the entire isolation model into decoration. Eleven failing
tests is the alarm that should accompany it.

Reproduce:

```bash
psql -h /tmp -U pulse -d pulse -c "ALTER ROLE pulse_app BYPASSRLS"
cd backend && PYTHONPATH=. python3 -m pytest tests/isolation -q      # expect failures
psql -h /tmp -U pulse -d pulse -c "ALTER ROLE pulse_app NOBYPASSRLS"
cd backend && PYTHONPATH=. python3 -m pytest tests/isolation -q      # expect 17 passed
```

## Ingestion (T024–T027) — post-hoc tests, mutation-verified

Phase 4 predates the TDD mandate and its four ingestion tests did not exist until the
delivery pass: the behaviour had been checked by hand (a second run inserting 0 rows) and
recorded in `HANDOFF.md`, but nothing guarded it. They were written after the code, so they
passed on first run and prove nothing by that alone; the table is the evidence that they can fail.

| Mutation to production code | Caught by |
|---|---|
| Remove `ON CONFLICT … DO NOTHING` from the event insert | `test_the_unique_constraint_alone_prevents_duplicates_when_the_watermark_is_lost` |
| Stop lowercasing the source event type in the adapter base | `test_both_type_casings_and_both_field_names_normalise_identically` |
| Skip events whose account reference is unmapped instead of storing them unresolved | `test_unmapped_ref_is_stored_unresolved_and_creates_no_account` |

Each mutation produced exactly one failure; restored, all 7 ingestion tests pass. The out-of-order
tests (T025) were not separately mutated: that property is the *absence* of sorting, which a
mutation would have to introduce.

## The unattended worker (validated 2026-10-16 against the exercise sheet)

`tests/integration/test_worker_serve.py` — five tests, each run red first for its own reason:
due-ness judged on the injected clock (not wall-clock `started_at`); a failing tenant neither stops the
others nor disappears from the run log; `serve` cycles on every interval and not inside one; `OffsetClock`.
End-to-end proof, not a unit test: on a throwaway copy of the demo database `pulse serve --simulate-present`
with a 1-minute interval produced one new `succeeded` run per tenant, one interval after the seeded ones, with
no human action. The `pulse serve` CLI wrapper itself has no unit test (smoke-run only, as above).


## 002 Phase 1 — isolation covers the new tables (T214)

Mutation: `DROP POLICY tenant_isolation ON app_session` on `pulse_test`. Result: 3 tests red
(`test_no_tenant_scoped_table_lacks_a_policy`, `test_unfiltered_select_returns_no_other_tenant_rows`,
`test_every_scoped_table_is_visible_to_its_own_tenant`); policy restored, 17 isolation tests green.
Also: the isolation suite failed on the new tables *before* `two_tenants` seeded rows into them — by design,
because "zero foreign rows" is vacuous on an empty table.

## 002 Phase 2 — identity (T248)

Each protection was removed on a backup copy and the named tests run; originals restored after (22 green).

| Mutation | Result |
|---|---|
| `get_session` trusts `X-Tenant-Id` again | `test_identity_forgery::test_a_forged_tenant_header_changes_nothing` red |
| ownership filter returns "everything" for everyone | 5 of 5 `test_csm_scoping` tests red |
| reject believes an `actor_user_id` named in the body | `test_actor_is_principal[POST /actions/{id}/reject]` red |

Also confirmed end to end against the real demo database (curl): no credentials → 401; a forged `X-Tenant-Id` with
no credentials → 401; wrong password → the same 401 body; operator queue 12 rows (2,490 below the cut); `csm01`
queue 12 rows (78 below the cut — their own accounts only); CSM on `/admin/config` → 403; cookie POST without
`X-Requested-With` → 403.

Not verified: the browser login form (no browser run); the per-process login limiter across multiple API instances.

## 002 Phase 3 — email (T273)

Each safety rule was broken on a backup copy and the named tests run; originals restored after (47 green).

| Mutation | Result |
|---|---|
| send gate allows everything (switched-off tenant, opted-out contact) | 6 tests red across `test_approve_delivers`, `test_send_gate` |
| demo mode ignored (deliver to the real contact) | 4 tests red incl. `test_in_demo_mode_nothing_reaches_a_real_contact_across_a_whole_cycle` |
| an ambiguous outcome is retried | 2 tests red: `test_an_ambiguous_outcome_is_never_retried...`, `test_an_ambiguous_outcome_is_send_unconfirmed...` |

Found by thinking through how a credential could escape, then proven by a failing test: `smtplib.SMTPException` subclasses
`OSError`, so credentials offered to a server with no AUTH were classified *transient* and retried three times; now permanent.

**What "delivered" means here — and does not.** Delivery is exercised against an in-process fake SMTP server that can reject,
tempfail, greet 421 or accept a body and never answer. **No test, and nothing in this session, sent a real email.** A real
inbox check is a manual step: run `python3 -m pulse.tools.smtp_sink`, or point `PULSE_SMTP_HOST` at a real provider. Bounces and
replies are not processed, so a hard bounce is not known to the system.

## 002 Phase 4 — language-model drafting (T274–T288)

Mutations (backup copy, named tests, restored after; 25 green):

| Mutation | Result |
|---|---|
| output validator accepts everything | 6+ `test_validate_llm_output` tests red (invented numbers, links, markup, instructions all got through) |
| a provider exception propagates instead of falling back | 3 `test_llm_in_the_cycle` tests red |
| account name placed in the instruction channel | `test_the_user_message_is_one_json_document...` red |

Also pinned (guard, not test-first): importing the cycle, drafter, grounding, delivery, feature computation, training
and scoring loads **no** LLM module until a key is configured; scoring, tiers, deltas and priority are identical with the
model off, on and failing (`test_ranking_is_identical_with_the_model_off_on_or_failing`).

**Not verified: no real call to a language-model provider has ever been made by this system.** Every test uses a scripted
stand-in for the provider. The `AnthropicClient` adapter (about fifteen lines over the SDK) has never been run. To check live:
`pip install -e ".[llm]"`, then `PULSE_LLM_ENABLED=true PULSE_LLM_API_KEY=… python3 -m pulse.cli cycle` and read the drafts in
the UI (`draft_source: llm`, with the model name). A model could pass this validator and still write something awkward: the
validator guarantees *traceability*, not good prose, which is why drafts are still reviewed by a human.

## 2026-10-17 — closing pass on spec 002

**`/speckit-analyze` re-run on spec 002** (36 FR, 13 SC, 108 tasks; every requirement is cited by a task). Findings and what was done:

| Finding | Severity | Resolution |
|---|---|---|
| FR-007 asks for rate limiting "per identity *and per source*"; only per (address, workspace, email) existed, so password spraying never tripped it | HIGH | address-wide limit added (`test_login_spraying`, shown red without it, green with it) |
| FR-001/SC-002 claimed "no tenant-scoped work" for refused requests, but resolving a session reads the session table under the (untrusted) claimed tenant | MEDIUM | spec reworded to "no *data* work"; behaviour unchanged and tested |
| FR-021 said provider credentials "per tenant"; built as deployment-level credentials with a per-tenant sender address | MEDIUM | spec reworded to match; gap recorded (B-29, README) |
| `tasks.md` totals were stale (104 vs 108) | LOW | recomputed |
| SC-005 (sign-in to a working queue < 30 s) was not measured | MEDIUM | now asserted in the browser suite (it takes well under a second) |
| Edge case "model reply in the wrong language" has no check | LOW | open — the validator checks numbers, links, markup, instructions and claims, not language |

**The failing reconcile test** was not a SHAP defect. Attribution reconciles to the model's logit to floating-point noise (~1e-15, new strict unit test, mutation-verified). The integration check compares the *stored* probability, which has
5 decimals, so rounding alone can move the log-odds by up to 5e-6/(p(1−p)) — ~3e-4 at p=0.016. The old fixed 1e-4 only worked for probabilities near 0.5, and its account-picking query had no `ORDER BY`, so a rebuild changed which account it
tested. The tolerance now follows p, and the account is chosen deterministically.

**Browser suite** (`npm run e2e`, real Google Chrome, scratch copy of the demo DB): 9 scenarios, run three times in a row — stable. Two failures along the way were both test bugs, not product bugs: it matched an account by *name* (names repeat),
and it assumed the first few drafts had a contact (≈1 in 9 do not, and they cluster). The demo database was confirmed untouched after every run.

**Deck:** `docs/Pulse_deck.pptx` rebuilt with the real top of the signed-in queue (the builder signs in; tested against a stand-in server). Only slide 1 has ever been rendered to an image (macOS Quick Look); slides 2–11 are text and one table, checked programmatically.

**Totals at the end:** backend 436 · frontend 34 · browser 9. Nothing pushed.

**`pulse send-test`** (added 2026-10-17): one command that sends a labelled test message through the configured SMTP provider and reports delivered / permanent / transient / unconfirmed. Tested against the fake server only (4 tests); it exists so the one
unverified step — a real message to a real inbox — is a one-minute job for whoever holds credentials. **It has not been run against a real provider.**

## 2026-10-17 — the container stack, actually run

Installed Colima + Docker CLI (Homebrew; arm64). Built and ran `docker compose`. Observed, not assumed:
**builds** (api/worker 882 MB, web 92 MB) · **healthy** db → api (migrations) → worker, web · **non-root** (uid 10001; nginx 101) · **no data, models or credential files** in the image (`/app/data`, `/app/artifacts` empty;
no credential-named env var baked in) · **bug found by running it:** the worker crash-looped with no model → fixed (`test_worker_waits_for_a_model`) · `bootstrap-demo` in the container → 347,740 events, ROC-AUC 0.690,
precision@100 0.289, **identical to the host** · queue through nginx: 12 rows, 2,490 below the cut (same top account as the host) · **9/9 browser scenarios pass against the containers** · `down` then `up`: sign-in and queue intact.
One transient: the queue read empty right after `bootstrap-demo` because the worker (started cycling as soon as a model existed) was still scoring northwind; leases kept the two cyclers from double-processing a tenant. Not verified: amd64, scans, timing.
