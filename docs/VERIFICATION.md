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
