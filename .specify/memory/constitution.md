# Pulse Constitution

Pulse is a renewal-risk and account-prioritisation system for Customer Success teams.
This constitution is the contract the implementation is held to. The five principles
below are derived from the non-negotiables in the engagement brief; they are not
stylistic preferences and a change to any of them is an amendment, not a refactor.

## Core Principles

### I. Point-in-Time Correctness (NON-NEGOTIABLE)

Every number the system produces must be reproducible from only the data the system
had actually received at the moment the number was computed.

- Every ingested record carries both `occurred_at` (when the thing happened in the
  source system) and `received_at` (when Pulse first durably stored it). Both are
  mandatory; neither is derived from the other.
- All feature computation is a pure function of `(tenant_id, account_id, as_of)` over
  the event log filtered by `received_at <= as_of`. Filtering by `occurred_at` alone
  is a defect, because a record that arrived three days late was not knowledge the
  system possessed.
- Training labels are drawn strictly from a window that begins after the `as_of` of
  the features they label. Backtests must therefore reproduce what the system *would
  have* said, not what hindsight knows.
- Event types that are mechanically downstream of the outcome being predicted
  (cancellation records, Closed-Lost stage transitions, final invoices) are denied to
  the feature layer by an explicit, tested denylist.
- Enforcement: a leakage test suite that (a) proves injecting an event after `as_of`
  does not change the feature vector, (b) proves label permutation collapses model
  skill to chance, and (c) proves every denylisted event type is unreachable from
  feature code.

### II. Fitted Models Rank; Language Models Only Write (NON-NEGOTIABLE)

Prioritisation is produced by a statistical model fitted on Pulse's own data, and a
language model is never an input to it.

- The ordering a CSM sees derives from a supervised model trained on historical
  outcomes, calibrated so its probabilities carry their stated meaning, and evaluated
  against both a trivial baseline and the heuristic a human would have written.
- An LLM may draft customer-facing language from evidence that has already been
  computed. It may not score, rank, tier, filter or re-order accounts, and no LLM
  output is ever an input to a feature or a score.
- The system must remain fully functional with no LLM configured. Degraded language
  quality is acceptable; degraded ranking is not.
- Enforcement: the ranking code path has no dependency on any LLM client, and a test
  asserts the full scoring pipeline runs with LLM support disabled.

### III. Autonomy With a Reviewed Boundary (NON-NEGOTIABLE)

The system does its work unprompted, and the boundary between what it does alone and
what a human confirms is explicit, configurable and auditable.

- A worker process advances the pipeline on its own schedule with no human trigger:
  ingest, recompute, score, detect material change, select plays, draft, dispatch.
- Work is leased from a durable queue, so a crashed worker resumes rather than
  silently skipping a cycle, and two workers never double-send.
- Every autonomous cycle writes a run record containing its inputs, the decisions it
  made, the decisions it declined to make and why, and its outputs. A run that
  produced nothing must still say so.
- Irreversible outward-facing actions default to human approval. Autonomous sending
  is permitted only for plays an operator has explicitly allowlisted, and is always
  bounded by per-account suppression windows and per-tenant rate limits.
- Enforcement: tests prove the worker runs unattended end to end, that lease
  expiry is safe, that an un-allowlisted play cannot self-send, and that suppression
  and rate limits hold under repeated cycles.

### IV. Tenant Isolation Enforced Below the Application (NON-NEGOTIABLE)

Multiple customer organisations share the deployment, and a forgotten `WHERE` clause
must not be able to leak data across them.

- `tenant_id` is a mandatory column on every tenant-scoped table and part of every
  natural key.
- Isolation is enforced by database row-level security against a session tenant
  claim, not by application filters. The application connects as a role that cannot
  bypass RLS. Application-level filtering is defence in depth, never the control.
- Cross-tenant work (training a shared model, computing global baselines) runs under
  a separate, explicitly named path that is reviewed as such, and never serves a
  request.
- Enforcement: a test suite that issues deliberately unfiltered queries under tenant
  A's session and asserts zero rows of tenant B's data are returned, for every
  tenant-scoped table.

### V. Nothing Unexplained Reaches a Human (NON-NEGOTIABLE)

Anything a CSM sees must be traceable, in the product, to the records the system
actually read.

- Every persisted score carries the model version, the full feature vector as
  evaluated, the per-feature contributions, and the arithmetic of the final priority.
- Every contributing feature resolves to the identifiers of the source records that
  produced it, and those records are retrievable with their original payloads.
- Score changes are explained as a feature-level diff against the previous score, so
  "why did this move" is answerable without a data pull.
- The system must be able to say "I don't know". Accounts whose evidence is too thin
  for a trustworthy score are routed to an explicit low-confidence state and are
  never presented as healthy by default.
- Enforcement: a contract test asserts no score is persisted without a resolvable
  evidence trail, and that the abstain path is reachable and surfaced.

## Engineering Standards

**Stack**: Python 3.13, FastAPI, SQLAlchemy 2.0 + Alembic, PostgreSQL 16,
scikit-learn, React 19 + TypeScript + Vite. No service is introduced without a named
problem it solves that the existing stack cannot.

**Determinism**: every stochastic process — data generation, train/test splitting,
model fitting, sampling — is seeded and the seed is recorded in the artefact it
produced. Re-running a documented command on a documented seed reproduces the
reported numbers.

**Honest metrics**: model quality is reported at the operating point the business
actually uses (a bounded weekly queue per CSM), alongside calibration and a lift
figure over a stated baseline. Headline aggregate metrics without an operating point
are not acceptable reporting.

**Boundaries**: domain logic is pure and IO-free, and therefore unit-testable without
a database. Persistence, HTTP and scheduling are adapters around it.

**Migrations**: schema changes ship as migrations. No implicit table creation in
application startup outside of test fixtures.

## Delivery Workflow

1. A change begins with the specification, not the code. `spec.md` states the
   behaviour; `plan.md` states how; `tasks.md` is derived from both.
2. Ambiguity is recorded and resolved in `clarifications.md` with the reasoning,
   including the questions that could only be answered by the business and the
   assumption adopted in their absence.
3. The test that would have caught a defect is written with the fix.
4. Scope deliberately dropped is written down as dropped, with the reason. Silence
   about a gap is treated as a worse failure than the gap.

## Governance

This constitution supersedes convenience. A pull request that violates a
non-negotiable is rejected regardless of what it enables. Violations that are
genuinely necessary are recorded in the Complexity Tracking table of `plan.md` with
the simpler alternative that was rejected and why.

Amendments require: the amended text, the rationale, and the migration for anything
already built against the prior text.

**Version**: 1.0.0 | **Ratified**: 2026-10-15 | **Last Amended**: 2026-10-15
