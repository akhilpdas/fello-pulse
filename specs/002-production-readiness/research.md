# Research — decisions for 002

Each entry: **Decision · Rationale · Alternatives rejected**. Anything the business could overturn is
repeated in `clarifications.md` when the work lands.

**R-1 Credentials and sessions.** Email + password per tenant user. Password hashed with stdlib
`hashlib.scrypt` (per-user salt, parameters stored with the hash so they can be raised). Session = opaque
random 256-bit token; only its SHA-256 is stored; sent as an `HttpOnly; SameSite=Strict` cookie (and
accepted as `Authorization: Bearer` for API clients and tests). *Why*: revocation and role changes must bite
on the next request (FR-008), which stateless tokens cannot do without a lookup anyway; no new dependency.
*Rejected*: JWT (not revocable without a store, adds a library, tempts putting role in the token);
SSO/OIDC, MFA (out of scope, named); bcrypt/argon2 (a dependency for no gain at this scale).

**R-2 How the tenant claim is set before the tenant is known.** The session token is
`<tenant_id>.<secret>`. The tenant id prefix is *untrusted*: the request opens a transaction under that
claimed tenant and looks up `sha256(secret)` in `app_session` **under RLS**. A forged prefix finds nothing
(the row belongs to the real tenant, which RLS hides) and the request is refused before any work. *Why*:
no `SECURITY DEFINER` function and no cross-tenant read on the request path, so constitution IV needs no
exception. *Rejected*: a global session table (a cross-tenant read serving requests); a definer function.

**R-3 Login disambiguation.** Sign in with workspace (tenant slug) + email + password. The slug resolves
to an id from the global `tenant` table, then everything runs under that claim. *Why*: the same email may
exist in two tenants (edge case); email-only login would need an ambiguous merge. *Rejected*: email-only.

**R-4 Login rate limiting.** In-process sliding window keyed by (client address, workspace, email),
returning the same response for unknown and known accounts, with a constant-cost password check for unknown
users. *Known limit, stated*: per process — with N API instances the allowance is N× (a shared store is the
fix, not built). *Rejected*: DB-backed counters (cannot attribute attempts for an unknown workspace under RLS).

**R-5 CSRF and cookies.** `SameSite=Strict` plus required `X-Requested-With` on state-changing cookie
requests; `Secure` when served over HTTPS. Bearer-token requests are not CSRF-able and skip the header.

**R-6 Ownership.** `account.owner_user_id` is already populated from the CRM owner reference
(`ingest/dimension.py`, users `csmNN`). CSM visibility = `owner_user_id = principal.user_id`; operators see
all; unowned accounts operator-only (FR-005). Applied in one shared helper so no router can forget it.
*Risk to verify first*: the demo users must exist for every owner ref — a test checks it.

**R-7 Worker identity.** The worker already opens `tenant_session(tenant_id)` directly and never goes through
the API; nothing to forge. Its actions are recorded with `actor = system` (no user id). The Python code path
that approves/rejects takes the user from the principal only (FR-006).

**R-8 Customer contact.** Add `contact_name`, `contact_email` to `account` (nullable). The generator emits
`primary_contact` in `Account.updated` for ~90% of accounts (the rest deliberately missing). *Consequence*:
regenerating data changes the seed-derived estate, so metrics are re-run and every quoted figure (0.33,
0.69, 0.326…) is re-quoted from the new run. Contact fields are excluded from `features/` by test.

**R-9 Email transport.** `Transport` protocol unchanged. `SmtpTransport` (stdlib `smtplib`, STARTTLS,
timeouts) reads host/credentials from the environment; the tenant supplies only the From address and
enabled/verified/demo flags (so provider credentials are deployment-level, not in the database — FR-021).
Message-ID derived from the action id so a provider/recipient can de-duplicate. *Rejected*: per-tenant SMTP
credentials stored in the DB (a secret-at-rest problem we are not solving here — recorded as a gap).

**R-10 Send state machine.** `drafted → approved → sending → sent | send_failed | send_unconfirmed |
not_configured | outbound_disabled | no_recipient | opted_out`. The `drafted → approved` step is a single
conditional `UPDATE … WHERE state='drafted' RETURNING` (today's read-then-write races), so a duplicate
approval cannot send twice. Transient failures (connect/4xx) retry ≤3; permanent (5xx) do not; ambiguous
(timeout after DATA) → `send_unconfirmed`, never auto-retried. Config is re-checked at send time.

**R-11 Opt-out.** `contact_opt_out(tenant_id, email)`; operator-managed (`POST /admin/opt-outs`) and
checked before every send; messages carry a footer saying how to opt out. *Gap, stated*: replies and
bounces are not processed automatically (spec Assumptions).

**R-12 Demo mode.** `tenant_config.demo_mode` defaults **true**; when true every send is redirected to
`tenant_config.test_inbox` (or captured if none) with subject prefix `[DEMO → original recipient]`, and the
action records `redirected_to`. Databases built by the generator stay in demo mode.

**R-13 LLM drafting.** `anthropic` SDK, lazily imported, model name from settings. Output contract: JSON
`{subject, body, claims[]}`. Grounding gains `facts` (short human-readable strings derived from the score's
top drivers, e.g. "3 support tickets in the last 28 days"). Validator: `claims ⊆ evidence drivers`; every
number/date in the text must appear in `facts` or the account/play inputs; no URLs, markup or instructions;
length cap; otherwise reject → template, reason recorded. Ingested ticket/email text is *never* put in the
prompt as free text — only the derived facts are (FR-030, prompt-injection). Bounds: ≤N calls per cycle per
tenant, per-call timeout; breaker opens after consecutive failures so a dead provider costs seconds, not minutes.

**R-14 Leave-one-tenant-out (001 FR-018).** In `ml/pipeline`, for each trainable tenant train on the
others and score that tenant's held-out block; report AUC and precision@capacity per tenant in the model
card and `GET /model`. Cost ≈ (tenants) extra fits; measured and stated in the card. Not a promotion gate.

**R-15 Containers.** Multi-stage backend image (API + worker share it, different command), nginx-served
frontend build, Postgres 16 with a named volume, `depends_on: service_healthy`, migrations in an entrypoint
step. Compose is **unverified** until run on a machine with Docker; the docs say so (FR-034).
