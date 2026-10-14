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
