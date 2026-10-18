# Feature Specification: Hosted Demo and Reviewer Experience

**Feature Branch**: `003-hosted-demo` (spec directory only; work continues on `main`)

**Created**: 2026-10-18

**Status**: Draft — clarification in progress (3 questions answered; remaining items are implementation detail)

**Input**: User description: "The team said we do not need to pay for hosting and should explore free options such as Vercel, Railway or Render. Plan with Render; if that is not possible use Railway ($5 is fine). Try Groq's free tier for drafting. A reviewer must not wait 10 to 46 minutes before seeing a populated demo. Everything should be testable in Docker first, since that is what would be deployed."

**Builds on**: `specs/002-production-readiness` (containers, LLM provider switch). Does not touch scoring, ranking or the model (constitution Principle II).

## Clarifications

### Session 2026-10-18

- Q: How should a reviewer get the pre-built demo database (51 MB compressed)? → A: A GitHub Release asset; a documented command downloads and loads it (kept out of git history).
- Q: What happens to the hosted demo's data when reviewers change it? → A: Writable; the owner has a one-command reset that restores the seed.
- Q: Should the seed hold Groq-written drafts or only templates? → A: Groq-written drafts, labelled (each draft already carries its source and model name).

## Why this exists

A dry run from a clean clone (2026-10-18, Docker, README steps only) measured what a reviewer actually waits for:

| Step | Measured |
|---|---|
| `docker compose up --build` (images cached) | 17 s |
| `bootstrap-demo` (generate, ingest 350k events, train, first cycle) | 7 min 37 s |
| `backfill --weeks 8` (the earlier weeks that make the Week picker and "What moved" useful) | **46 min** (about 10 min on a quiet machine) |

The first two steps meet 002's SC-012 (under 10 minutes to a signed-in system). The third is outside SC-012 but is what makes the demo worth reviewing, and a reviewer who gives up at minute 15 never sees it. Separately, no hosted URL exists, so the reviewer must run everything locally.

## User stories

### US1 — A reviewer sees the populated demo within ten minutes (P1)
From a clean clone with only a container runtime, the documented path reaches a signed-in system **with its history** (nine weekly snapshots, drafts, run log) in under 10 minutes, without running the 10–46 minute backfill.
*Independent test*: clean clone, documented commands only, stopwatch; sign in; Week picker lists ≥ 9 days; "What moved" compares two weeks.

### US2 — A reviewer opens a free hosted URL (P1)
A URL on a free platform (Render first; Railway if Render cannot host it) serves the same demo, signs in, and runs every browser scenario, with the limits of a free tier stated (sleeps when idle, no unattended worker, time-limited database).
*Independent test*: the 13 browser scenarios run against the hosted URL.

### US3 — Drafting works with a free model, and Anthropic is a settings change (P2)
With a free Groq key, one real cycle writes drafts through the existing guardrails; unset the key and the system still runs on templates; switching to Anthropic changes only environment variables.
*Independent test*: a real Groq call from inside a container; a real cycle with `draft_source: llm` rows; the same cycle with the key unset.

## Requirements

- **FR-001**: The documented container path MUST offer a way to start from a pre-built demo database (the seed) so that history is present without running the backfill. The seed is published as a **GitHub Release asset** (about 51 MB, custom-format `pg_dump`, no owner information) and a single documented command downloads it and loads it; the seed file is never committed to git. The same asset populates the hosted database.
- **FR-002**: The seed MUST contain no real person's data and no credential (all data is simulated; `@example.com`), and loading it MUST be idempotent and refuse to overwrite a database that already holds tenants unless told to.
- **FR-003**: Building from scratch (`bootstrap-demo`, `backfill`) MUST remain documented and working; the seed is a shortcut, not a replacement.
- **FR-004**: The hosted deployment MUST run the existing images/code unchanged in behaviour; any hosting-specific accommodation (for example a managed database that cannot create a bypass-RLS role) MUST be explicit, minimal, tested, and MUST NOT weaken tenant isolation for the roles that serve requests.
- **FR-005**: The hosted deployment MUST NOT run the unattended worker on a free tier; the documentation MUST say so and say how the unattended behaviour is shown instead.
- **FR-005a**: The hosted demo is writable (approvals, suppressions, feedback and admin changes persist). A single documented command restores the seed over the hosted database (FR-001's loader with an explicit overwrite flag); it MUST refuse to run without that flag and MUST NOT be reachable from the web UI or API.
- **FR-005b**: The seed MUST be built by running one real cycle with a free Groq key (per-tenant call cap lowered so the run stays inside the free daily limits), so that its drafts carry `draft_source: llm` and the model name; the seed's release notes MUST state the model, the date and how many drafts are model-written versus template, and that this is a one-off, not reproducible bit for bit.
- **FR-006**: Secrets (database URL, demo password, any model key) MUST be supplied through the platform's environment settings, never committed; `.env` stays git-ignored.
- **FR-007**: The language-model choice MUST be selectable by environment only (provider, base URL, model, key) in Docker and on the hosted platform; with no key, drafting uses templates.
- **FR-008**: A real call to Groq's free tier MUST be exercised once end to end and its limits (requests/tokens per day) recorded as observed, not assumed.
- **FR-009**: Every documented time MUST be a measured time with the conditions stated.

## Success criteria

- **SC-001**: Clean clone to signed-in, history-bearing demo in **under 10 minutes** on a machine with a container runtime and nothing else (stopwatch, documented commands only).
- **SC-002**: The 13 browser scenarios pass against the hosted URL.
- **SC-003**: A cycle with a free Groq key produces model-written drafts that pass the grounding validator, and the same cycle with no key produces template drafts, both without code changes.
- **SC-004**: The README and `docs/HOSTING.md` contain no hosting claim that was not exercised, or they label it unverified.

## Edge cases

- The hosted API has been idle > 15 minutes (cold start of about a minute): the UI must show a loading state rather than an error.
- The free database expires (30 days on Render): documented, with the date to re-seed.
- Two reviewers act on the same hosted data at once (approvals, suppressions persist); the owner can restore the seed with the reset command (FR-005a).
- The Groq daily quota is exhausted mid-cycle: the existing breaker falls back to templates and the cycle still succeeds.

## Out of scope

Speeding up scoring itself; a hosted worker; SSO/MFA; paid tiers beyond Railway's $5; any change to the model, the ranking or the tiers.

## Assumptions

- Render and Railway terms are as read from their documentation on 2026-10-18 and must be re-checked at deploy time; whether Render's database user may create roles is unverified.
- **Observed 2026-10-18 (FR-008), Groq free tier, via `pulse llm-check` and the response headers:** 1,000 requests/day and **8,000 tokens/minute** (the binding limit: a batch of drafts meets HTTP 429 with `Retry-After`, which the client now honours, up to 3 retries of at most 30 s). Models offered on the key that day: `openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `qwen/qwen3.8-27b` and others; **`llama-3.3-70b-versatile`, named in the first plan from secondary sources, no longer exists** (HTTP 404). The two gpt-oss models spend 4–5x the tokens on hidden reasoning, so `qwen/qwen3.8-27b` (no reasoning overhead, ~0.3 s per call) is the default. Groq's Cloudflare also returns **403 (error 1010) to Python's default User-Agent**, which looks exactly like a rejected key; every request now sends `User-Agent: fello-pulse/1.0`.
