# Implementation Plan: Hosted Demo and Reviewer Experience

**Spec**: `specs/003-hosted-demo/spec.md` · **Date**: 2026-10-18 · **Method**: strict TDD (AGENTS.md); ambiguity to `clarifications.md`; dropped scope written down.

## Summary

Make the demo reachable in minutes instead of tens of minutes, and reachable at a free URL. Three moves: (1) a **seed** — a 51 MB `pg_dump` of the built demo, published as a GitHub Release asset and loaded by one command; (2) a **single-service hosted image** (API + built UI behind one origin) with a Render blueprint, and Railway as the fallback; (3) a **Groq smoke check** and a seed built from a real Groq cycle. No scoring, ranking or model change.

## Technical context

- Python 3.13 container image, FastAPI, Postgres 16 with RLS (roles `pulse_app` NOBYPASSRLS, `pulse_trainer` BYPASSRLS, owner), React/Vite UI, nginx in the existing `web` image.
- Measured today: seed 51 MB (custom format, `--no-owner`); API idle 163 MB; demo database 564 MB (source_event 382 MB); Render free = 512 MB RAM web service, 1 GB Postgres expiring after 30 days, no free worker, no disks; Railway Hobby $5/month, 5 GB volume.
- Unverified: whether Render's database user can `CREATE ROLE` (migration 0002 also creates a `BYPASSRLS` role, which needs a superuser).

## Design

### 1. Seed (`pulse.seed`, CLI `export-seed` / `load-seed`)
- `export-seed --out seed.dump`: `pg_dump -Fc --no-owner -T alembic_version`, plus a sidecar `seed.json` (schema revision, row counts, sha256, model name for drafts, created date).
- `load-seed --file F | --url U [--overwrite]`: verify sha256; refuse unless the database is migrated to the seed's revision; refuse if tenants already exist unless `--overwrite` (then truncate tenant data first, preserving schema and roles); `pg_restore --data-only --no-owner`; verify row counts against the sidecar.
- The `postgresql-client` package is added to the backend image so the command works in the container.
- Reset (FR-005a) is `load-seed --overwrite`: a CLI only, no route.

### 2. Hosted image (`infra/docker/hosted.Dockerfile`, `pulse.api.hosted`)
- An ASGI wrapper: `/api/*` is handed to the existing app with the prefix stripped (the UI already calls `/api/...`); everything else is the built UI with SPA fallback. One port from `$PORT`.
- Entrypoint: migrate; if the database holds no tenants and `PULSE_SEED_URL` is set, load the seed.
- `render.yaml` blueprint (web service + free Postgres); `docs/HOSTING.md` gets exact steps. A `probe` script reports in seconds whether a given database URL can create roles / bypass-RLS roles (the go/no-go for Render).
- If the probe says roles can be created but `BYPASSRLS` cannot, migration 0002 skips only the trainer role (training does not run on the hosted demo) — tested with a non-superuser CREATEROLE role.
- Fallback: Railway (Docker + Postgres template with superuser, so no migration change), same image.

### 3. Groq (`pulse llm-check`)
- One real, minimal call through the configured provider; prints model, latency and any rate-limit headers; exit code says whether the provider is usable. Tested against a local fake server; run for real once with the owner's free key.
- The seed cycle: `PULSE_LLM_*` for Groq, `llm_calls_per_cycle` lowered per tenant, one cycle, then `export-seed`.

### 4. Docs and measurement
- README/DEMO_GUIDE Docker quick path = `up` → `load-seed` (≈ 2 min). Stopwatch from a clean clone is recorded (SC-001). Every number labelled with its conditions.

## Constitution check

Principle IV (isolation below the application) is untouched for `pulse_app`; the only change is conditional on the *trainer* role and is tested. Principle II (a model never ranks) untouched: drafts only. No complexity exceptions.

## Risks

| Risk | Mitigation |
|---|---|
| Render DB user cannot create roles | probe first; Railway fallback, same image |
| Seed restore violates FKs on a data-only load | order is handled by `pg_restore`; if not, restore into an empty migrated DB with triggers deferred (local has superuser) — verified in Docker before relying on it |
| Seed older than code (schema moved on) | revision check refuses with a clear message; seed is rebuilt with the release |
| Groq quota exhausted mid-cycle | existing breaker falls back to templates; seed notes state the real split |
| Hosted cold start looks like an error | UI loading state (T-task) |
