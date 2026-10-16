# Quickstart — validating 002

Prerequisites: the 001 quickstart has been followed (Postgres up, `pulse` and `pulse_test` built).
Always `cd backend && source .venv/bin/activate && export PGTZ=UTC`.

## Automated (the gate)

```bash
python3 -m pytest -q                    # backend, on pulse_test; must stay green after every task
cd ../frontend && npm test && npm run build
python3 -m pulse.openapi_export         # contract drift test fails until regenerated
```

## Scenarios (each maps to a user story; each also exists as a test)

1. **Identity (US1).** Sign in at http://localhost:5173 as `csm01@northwind` (workspace `northwind`; the
   demo password is printed by `run_all.sh`, never committed). The queue shows only that CSM's accounts.
   `curl` the API with another tenant's `X-Tenant-Id` and no cookie → 401; with the cookie → still only
   Northwind. A CSM opening `/admin/config` → 403.
2. **Gaps (Phase 0).** On an account, mark *false positive* → a `feedback` row exists; *suppress for 14
   days* → it leaves the queue, still has a score. `GET /model` shows `leave_one_tenant_out`.
3. **Email (US2).** *(Real provider: `python3 -m pulse.cli send-test --to <you>` with `PULSE_SMTP_*` set — see README.)* Start the fake SMTP sink (`python3 -m pulse.tools.smtp_sink`), set `PULSE_SMTP_HOST=127.0.0.1`
   `PULSE_SMTP_PORT=1025`, enable outbound for the tenant in demo mode, approve a draft → exactly one message in
   the sink, addressed to the test inbox, subject prefixed `[DEMO →`. Stop the sink and approve another → `send_failed`.
4. **LLM (US3).** `pip install -e ".[llm]"`, then `PULSE_LLM_ENABLED=true PULSE_LLM_API_KEY=… python3 -m pulse.cli cycle` → drafts show `draft_source: llm` and a model name.
   Unset the key → template drafts; the queue order is byte-identical. (A live call is a manual check; tests
   use a scripted stand-in.)
5. **Packaging (US4) — built and run on arm64/Colima (see README).** `docker compose up --build` then
   `docker compose run --rm api python3 -m pulse.cli bootstrap-demo`. Then `PULSE_E2E_PASSWORD=<printed> bash infra/scripts/e2e_docker.sh`
   runs the browser suite against it. Not yet done on amd64.

## What "done" means here

Tests green **and** the matching scenario above run by hand, **and** anything not done written down.
