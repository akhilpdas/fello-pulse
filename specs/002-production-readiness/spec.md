# Feature Specification: Production Readiness — Identity, Delivery, Drafting, Packaging

**Feature Branch**: `002-production-readiness` (spec directory only; work continues on `main`)

**Created**: 2026-10-16

**Status**: Implemented (all 108 tasks done). Not verified, and stated as such in `README.md`: any real email or model call, and the containers. Where the build differs from this text it is called out inline (FR-001, FR-018, FR-021).

**Input**: User description: "Close the four gaps that were wrongly listed as 'deliberately skipped' in Pulse: real outbound email, live LLM drafting, containerised one-command deployment, and an authentication system apt for this application. Strict TDD; ambiguity in clarifications.md; dropped scope written down."

**Builds on**: `specs/001-renewal-risk-prioritisation` (the system as delivered). Where this
spec tightens a decision made there, it says so. It does not change ranking, scoring or the
model, and must not (constitution Principle II).

## Why this exists

Four items were listed in the delivered system's README under "Deliberately skipped". On review,
only part of that was a decision. The rest was unfinished work labelled as a decision:

| Item | What the delivered system does today | Why that is a defect, not a choice |
|---|---|---|
| Identity | Tenant and user are read from `X-Tenant-Id` / `X-User-Id` request headers; the approver's id is read from the **request body**. | Anyone who can reach the API can act as any user of any tenant. Row-level security stops cross-tenant leaks *given a correct tenant claim*, but the claim itself is client-supplied. Approval attribution — the audit trail the constitution leans on — is forgeable. |
| Email | Approving a draft calls a recording stub and sets the action to `sent`. The recipient is the placeholder `csm+<account>@example.test`. | "Sent" is not true. Nothing leaves the system, and the data contains **no customer contact address** to send to. The approval step approves a message that goes nowhere. |
| LLM | The LLM path is wired but its body raises "no LLM client is wired in". | The system claims "an LLM only writes" while having no way to write. The boundary (Principle II) has never been exercised against a real model. |
| Packaging | One shell script; the planned container setup (T004) was dropped because Docker is not installed on the dev machine. | An environment limitation, not a design decision. The files can be written and flagged unverified. |

## User Scenarios & Testing *(mandatory)*

### User Story 1 — A real person signs in, and the system believes the credential, not the caller (Priority: P1)

A CSM opens Pulse and signs in with their email and password. From then on, which tenant they
belong to, who they are, and what they may do are determined by the verified credential — never
by anything the browser asserts. An operator signs in the same way and additionally manages the
tenant's configuration and auto-send allowlist. A CSM sees the accounts they own; an operator
sees the whole tenant.

**Why this priority**: Everything else is unsafe without it. Real email on top of forgeable
identity means anyone can approve a send as anyone. It also closes the one place the
tenant-isolation story depends on trust (the tenant claim feeding row-level security).

**Independent Test**: With the sign-in in place and nothing else from this spec, a request that
supplies a different tenant id or user id than its credential carries is either rejected or
ignored, and approving a draft records the *authenticated* user as the approver — verifiable
without any email or LLM.

**Acceptance Scenarios**:

1. **Given** a registered user with the right password, **When** they sign in, **Then** they
   receive a session that identifies exactly their tenant, user and role, and nothing else about
   those three things can be supplied by the caller afterwards.
2. **Given** a request with no credential, an expired credential, or a tampered credential,
   **When** it reaches any data route, **Then** it is refused as unauthenticated and no data is
   returned, **and** no database work is done under any tenant claim.
3. **Given** a signed-in Northwind CSM, **When** their request also carries Globex's tenant id
   (in a header, query or body), **Then** the result is exactly as if it had not — they still see
   only Northwind, and the attempt is recorded.
4. **Given** a signed-in CSM, **When** they call an operator-only route (tenant configuration,
   auto-send allowlist, coverage), **Then** they are refused as forbidden, and an operator is not.
5. **Given** a CSM who owns some of a tenant's accounts, **When** they open the queue, drafts or
   run log, **Then** account-level data is limited to accounts they own; an operator sees all of
   the tenant's accounts.
6. **Given** a CSM approves a draft, **When** the request body also names a different user as
   the approver, **Then** the recorded approver is the authenticated CSM, not the named user.
7. **Given** repeated failed sign-ins for one identity, **When** the limit is reached, **Then**
   further attempts are delayed or refused for a period, without revealing whether the email exists.
8. **Given** the web app with no session, **When** it loads, **Then** it shows a sign-in form
   (not the paste-your-ids bar), and signing out ends the session.

---

### User Story 2 — An approved draft is actually delivered, safely (Priority: P2)

A CSM approves a drafted message and the customer receives it, from the right sender, once. If
delivery fails the CSM can see that it failed and why. Nothing is ever delivered for a tenant or a
play that has not been explicitly switched on, and nothing real is delivered from a demo.

**Why this priority**: It turns approval from theatre into an outcome, and it is the first
point where Pulse can harm a real customer relationship — so it must arrive after identity (US1)
and be safe by default.

**Independent Test**: With a controllable fake mail server standing in for the provider, approve
a draft for a configured tenant and observe exactly one message at the server with the expected
sender, recipient, subject and body; then break the server and observe the bounded retries and a
visible `send_failed` with the reason.

**Acceptance Scenarios**:

1. **Given** a tenant with a verified sender and outbound email enabled, **When** a CSM approves a
   draft for an account with a known contact, **Then** exactly one message is delivered to that
   contact from that tenant's sender, and the action records the outcome and the time.
2. **Given** a transient provider failure, **When** a send is attempted, **Then** it is retried a
   bounded number of times with the attempt count recorded; if it still fails the action ends in
   `send_failed` carrying the last error, and nothing is silently dropped.
3. **Given** a tenant that has not configured a sender, or has not enabled outbound email,
   **When** a draft is approved, **Then** no delivery is attempted, the action says why
   (`not_configured` / `outbound_disabled`), and the CSM is told plainly.
4. **Given** an account with no contact address, **When** its draft is approved, **Then** no
   delivery is attempted and the action says `no_recipient`; the system never substitutes a
   placeholder or a different person's address.
5. **Given** a contact who has opted out (or been suppressed) for the tenant, **When** a draft to
   them is approved or auto-sent, **Then** it is not delivered and the reason is recorded.
6. **Given** the autonomous cycle and a play that is not allowlisted, **When** the cycle runs,
   **Then** the play still cannot send itself (constitution Principle III) — real delivery does
   not loosen the boundary. Suppression windows and the per-cycle rate limit still apply.
7. **Given** the same approval submitted twice (double click, retry after a timeout), **When**
   both arrive, **Then** the contact receives one message and the second call reports the first's result.
8. **Given** the system is in demo mode, **When** any send occurs, **Then** it is delivered only
   to the configured test inbox (never to the account's contact), and the message and the action
   both say the original recipient was redirected.

---

### User Story 3 — Drafts are written by a language model from the evidence, and only from the evidence (Priority: P3)

When a language-model key is configured, the first-move drafts read like a person wrote them,
using the specific evidence the system already computed. When no key is configured, or the model
misbehaves, drafts fall back to the existing deterministic templates. In every case the ranking is
byte-for-byte what it would have been without a model.

**Why this priority**: It improves prose, not the product's correctness; the system is already
fully functional without it (Principle II). It is also the highest-novelty risk surface (made-up
facts in customer-facing text), so it follows the delivery path it feeds.

**Independent Test**: Run the same cycle with the model disabled and enabled (using a scripted
stand-in for the provider): the scores, tiers and queue order are identical; the enabled run's
drafts differ only in prose; a stand-in that invents a number or an account fact is rejected and
replaced by the template.

**Acceptance Scenarios**:

1. **Given** a configured key and an account with a grounding record, **When** the cycle drafts
   a first move, **Then** the draft is written by the model, marked as model-written together with
   which model, and every concrete fact in it (a number, a date, a named event, a plan or account
   attribute) is present in that action's grounding.
2. **Given** a model reply containing a fact that is not in the grounding, **When** the draft is
   validated, **Then** it is rejected, the deterministic template is used instead, and the
   rejection and its reason are recorded.
3. **Given** no key, the feature switched off, a provider error, a timeout, or an empty reply,
   **When** drafting runs, **Then** the template draft is produced, the cycle does not fail or
   slow materially, and the run log records that the fallback happened.
4. **Given** any configuration of the model (on, off, failing), **When** the scoring and ranking
   run, **Then** every score, tier, delta and queue position is identical to the model-off result,
   and the scoring and ranking code paths do not depend on the model client at all.
5. **Given** a cycle over many accounts, **When** it drafts, **Then** the number of model calls is
   bounded per cycle and per tenant, and accounts beyond the bound receive template drafts.
6. **Given** a CSM edits a model-written draft before approving, **When** it is sent, **Then** the
   record still shows what the model originally wrote and what the human changed.

---

### User Story 4 — One command runs the whole system in containers (Priority: P4)

Someone who has never seen the project clones it, runs one command, and gets the database, the
API, the unattended worker and the web app running together — including the worker that cycles
every tenant on its own.

**Why this priority**: It makes the system runnable and reviewable elsewhere, and replaces the
dropped T004. It touches no behaviour, so it comes last and can be verified only where a container
runtime exists.

**Independent Test**: On a machine with a container runtime and nothing else installed, one
documented command reaches a state where the sign-in page loads, a sample sign-in works, and a new
run appears in the run log without anyone clicking anything. **Until that has been done on such
a machine, the packaging is described as unverified.**

**Acceptance Scenarios**:

1. **Given** a clean machine with only a container runtime, **When** the documented command is run,
   **Then** the database, API, worker and web app start, schema migrations apply, and the system is
   reachable on documented ports.
2. **Given** the stack is up, **When** the demo-data command is run, **Then** it produces the same
   populated, scored estate as the non-container path for the same seed.
3. **Given** the worker container is killed mid-cycle, **When** it restarts, **Then** it resumes
   without double-running a tenant (existing lease behaviour), and the failure is visible in the run log.
4. **Given** the stack is brought down and up again, **When** it returns, **Then** previously
   created data is still present, and nothing secret has been baked into any image.
5. **Given** the test suite, **When** it runs in the containers, **Then** it uses its own database
   and never the demo one (as today).

---

### Edge Cases

- A user's role changes or the user is disabled while a session is live: the next request reflects
  it (a disabled user is refused; a demoted operator loses operator routes) without waiting for expiry.
- A user exists in two tenants with the same email: the sign-in resolves to exactly one
  (tenant, user) pair, never an ambiguous merge.
- The worker (no human) acts for a tenant: it needs a tenant claim but no user session; it must not
  reuse a person's credential, and its actions are attributed to the system, not to a user.
- An approval is made, then the tenant switches outbound email off before the send runs: the send
  re-checks at the moment of sending and refuses.
- The provider accepts a message but the response is lost (timeout after acceptance): a retry must
  not produce a duplicate delivery.
- A draft contains characters or length a provider rejects: surfaced as a send failure with the
  reason, not retried indefinitely.
- A model reply is in the wrong language, contains markup, links, or instructions to the reader
  (prompt injection echoed from ingested ticket text): only plain text drawn from grounding is
  accepted; anything else falls back to the template.
- Ticket or email text containing instructions aimed at the model arrives through the evidence the
  model reads: it is treated as data and cannot change the output's constraints.
- A model key is present but invalid or over quota: behaves exactly like no key, once recorded,
  rather than failing every account for the whole cycle.
- Container start-up when the database is not yet ready: the dependants wait or retry; they do not
  crash-loop silently.
- An operator allowlists a play, a worker is mid-cycle, and the operator revokes it: nothing
  allowlisted-but-unsent is sent after revocation (extends 001's mid-cycle revocation edge case).

## Requirements *(mandatory)*

### Functional Requirements

**Identity and access**

- **FR-001**: Every route that reads or writes tenant data MUST require a verified credential; a
  request without one, or with an invalid, expired or tampered one, MUST be refused as
  unauthenticated before any *data* work is done for it. (Resolving a session necessarily reads the session
  table under the tenant claim the token names; that claim is untrusted and row-level security hides every row
  that is not that tenant's, so a forged one finds nothing — research R-2. No query against account, score, action
  or any other data table runs for an unauthenticated request.)
- **FR-002**: The tenant, user and role for a request MUST come only from the verified credential.
  A tenant id, user id or role supplied by the caller in any other way (header, query, body) MUST
  have no effect on the result, and a mismatch MUST be recorded as a security event.
- **FR-003**: The tenant claim that row-level security enforces MUST be derived from the verified
  credential, and remain transaction-local as today (constitution Principle IV). Isolation MUST NOT
  depend on any client-supplied value.
- **FR-004**: The system MUST support the roles `csm` and `operator`, enforced on the server.
  Operator-only capabilities (tenant configuration, auto-send allowlist, coverage report, model
  report, sender and outbound settings) MUST be refused to a `csm`.
- **FR-005**: A `csm` MUST see account-level data (queue, low-confidence list, drafts, account
  detail) only for accounts they own; an `operator` MUST see the tenant's accounts. Accounts with no
  owner MUST be visible to operators only.
- **FR-006**: The approver or rejecter of a draft MUST be the authenticated user; any actor named in
  the request body MUST be ignored, and the recorded identity MUST be the one in the credential.
- **FR-007**: Passwords MUST never be stored or logged in recoverable form, MUST meet a minimum
  strength, and sign-in MUST be rate-limited per identity and per source without revealing whether an
  email address is registered.
- **FR-008**: Sessions MUST expire, MUST be revocable (sign-out; disabling a user), and a change to a
  user's role or disabled state MUST take effect on their next request.
- **FR-009**: An operator MUST be able to create and disable users of their own tenant and assign
  their role and account ownership; they MUST NOT be able to affect any other tenant's users.
- **FR-010**: The autonomous worker MUST act under a system identity scoped to one tenant at a time,
  distinct from any user, and its actions MUST be attributed to the system.
- **FR-011**: The web app MUST present a sign-in form and sign-out, MUST NOT ask a person for tenant
  or user ids, and MUST hide operator-only views from a `csm`.
- **FR-012**: Sign-ins, sign-outs, refusals, role changes and identity/tenant mismatches MUST be
  recorded in an audit trail visible to the tenant's operator.

**Outbound email**

- **FR-013**: Approving a draft MUST attempt a real delivery through the tenant's configured email
  provider, and the action MUST record the outcome, the number of attempts and the time, as it
  already does for the stub.
- **FR-014**: Delivery MUST NOT be attempted unless the tenant has a configured, verified sender
  **and** outbound email explicitly enabled for it. Both default to off. In every other case the
  action MUST end in a distinct, queryable state naming the reason, and no network call is made.
- **FR-015**: The recipient MUST be the account's recorded customer contact. An account with no
  contact MUST NOT be sent to; no placeholder or fallback address may ever be used.
- **FR-016**: A contact on the tenant's opt-out or suppression list MUST NOT be sent to, and a
  message MUST carry what is needed for the recipient to opt out. Opt-outs MUST be honoured on every
  later send for that tenant.
- **FR-017**: Delivery MUST be retried a bounded number of times for transient failures, MUST NOT be
  retried for permanent ones, and a final failure MUST be surfaced (`send_failed` with the reason).
- **FR-018**: The system MUST NOT knowingly send a second message for one approval: a repeated
  approval, a retry after a *definite* failure, or a worker restart MUST NOT produce a duplicate. Where the
  outcome is genuinely unknown (the provider may or may not have accepted the message), the action MUST end in
  a distinct `send_unconfirmed` state, MUST NOT be retried automatically, and MUST surface to a human. (Exactly-once
  cannot be guaranteed over a provider-neutral mail protocol; this is the strongest honest guarantee.)
- **FR-019**: Real delivery MUST NOT relax the autonomy boundary: an un-allowlisted play cannot send
  itself, and suppression windows, the per-cycle rate limit and mid-cycle revocation continue to
  apply exactly as in specification 001 (FR-029, FR-035).
- **FR-020**: The system MUST have a demo mode in which every message is delivered only to a
  configured test inbox (or captured without delivery), marked as redirected, never to a real
  contact. Demo mode MUST be the default for any database populated by the data generator.
- **FR-021**: Credentials for the email provider MUST be supplied by configuration outside the
  codebase and database dumps and MUST NOT appear in logs, run records or API responses. **As built, the provider
  credentials are deployment-level (environment); what is per tenant is the verified sender *address*.**
  Per-tenant provider credentials were not built — storing a secret per tenant at rest is a problem this
  work does not solve (clarifications B-29, README "Gaps").
- **FR-022**: The recording implementation MUST remain, and remain the default for tests and the
  demo, so the whole system runs with no provider configured (as Principle II requires of the LLM).
- **FR-023**: The data generator and ingestion MUST carry a primary customer contact per account
  (including accounts with none, as a realistic gap), so that FR-015 can be exercised end to end.

**Language-model drafting**

- **FR-024**: When enabled and keyed, drafting MUST be performed by a real language-model client
  behind the existing drafting interface, using only the account's grounding as source material.
- **FR-025**: The model MUST NOT be reachable from, imported by, or an input to feature computation,
  scoring, tiering, change detection, ranking or queue ordering (constitution Principle II,
  001/FR-013). Enforced by test, as today.
- **FR-026**: Every model-written draft MUST be validated against its grounding: any specific fact it
  asserts that is not in the grounding, any link, markup or instruction, and any length or format
  violation MUST cause it to be rejected and replaced by the template draft, with the reason recorded.
- **FR-027**: With no key, the feature switched off, a provider error, a timeout, an invalid key, or
  an over-quota key, drafting MUST fall back to the template without failing the cycle, and the fallback
  MUST be recorded in the run record.
- **FR-028**: Model calls MUST be bounded per cycle and per tenant, with a bounded time for each call,
  so a slow or degraded provider cannot make a cycle miss its interval.
- **FR-029**: Each draft MUST record how it was produced (model-written or template), which model, and
  — for a model-written draft a human edited — both the original and the edited text.
- **FR-030**: Text from tickets, emails or other ingested sources that reaches the model as evidence
  MUST be treated as data: it MUST NOT be able to change the output constraints or cause an action.

**Packaging**

- **FR-031**: The repository MUST provide container definitions and a single composition that runs
  the database, the API, the unattended worker and the web app together, with migrations applied
  automatically and dependants waiting for the database.
- **FR-032**: A documented single command MUST start the stack, and a second documented command MUST
  populate it with the demo estate, matching the non-container path for the same seed.
- **FR-033**: Images MUST contain no secrets or generated data; configuration MUST come from the
  environment; data MUST persist across restarts of the stack.
- **FR-034**: The documentation MUST state that the container path is **unverified** until it has been
  run on a machine with a container runtime, and the verification MUST be recorded when it is.
- **FR-035**: The existing non-container path (`run_all.sh`, VS Code tasks) MUST keep working
  unchanged.

**Honesty and delivery**

- **FR-036**: Anything in this feature that is not done, not verified, or deliberately dropped MUST be
  written down as such in `clarifications.md` and the README; the README's "Deliberately skipped" list
  MUST be split into decisions (with reasons) and gaps.

### Key Entities *(include if feature involves data)*

- **Credential**: a user's secret proof of identity; stored only in a non-recoverable form; belongs to
  one (tenant, user).
- **Session**: a time-limited, revocable proof that a request comes from a signed-in user; carries
  tenant, user and role, and nothing the caller can alter.
- **User**: an existing entity (tenant, email, name, role), extended with an enabled/disabled state.
  Owns zero or more accounts.
- **Audit event**: who or what did what, to which tenant, when, and the outcome; includes security
  events (refusals, mismatches).
- **Sender configuration**: per tenant — the sending identity, whether it is verified, whether
  outbound email is enabled, and whether the tenant is in demo mode.
- **Customer contact**: per account — the person to write to, and whether they are reachable.
- **Opt-out**: per tenant and contact — a recipient who must not be sent to again.
- **Delivery record**: per send — attempts, outcome, provider reference, redirection (if demo), time.
- **Draft provenance**: per draft — how it was made, with which model, any rejection reason, original
  versus edited text.
- **System identity**: the non-human principal the worker acts as, scoped to one tenant per cycle.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With forged tenant or user identifiers supplied in any part of a request, **100%** of
  attempts to read or act on another tenant's data or as another user fail, across every route, verified
  by a test that iterates over all routes.
- **SC-002**: **100%** of data routes refuse an unauthenticated, expired or tampered request, and **0**
  data-route (non-session) tenant-scoped operations occur for such requests — verified by
  `test_identity_forgery` (no data-route session is opened) and the every-route sweep.
- **SC-003**: A `csm` is refused on **100%** of operator-only routes, and an operator is not refused on
  any of them.
- **SC-004**: Every approval, rejection and edit in the audit trail names the authenticated user;
  **0** records name a user taken from a request body.
- **SC-005**: A signed-in user reaches a working queue in **under 30 seconds** from the sign-in page,
  with no identifier copied by hand.
- **SC-006**: For a configured tenant, an approved draft is received **exactly once** by the test
  provider in **100%** of runs including induced definite failures followed by retry, and duplicate approvals;
  an induced *ambiguous* failure results in **zero** automatic re-sends and a visible `send_unconfirmed`.
- **SC-007**: For an unconfigured tenant, a tenant with outbound email off, an account with no contact,
  and an opted-out contact, **0** messages reach the provider and each case reports its own distinct reason.
- **SC-008**: Across a full cycle, **0** messages are delivered to a real contact while demo mode is on;
  **100%** reach only the test inbox, marked as redirected.
- **SC-009**: Scores, tiers, deltas and queue order are **identical** between a cycle run with the model
  off and a cycle run with it on or failing, for every account.
- **SC-010**: **100%** of model-written drafts shipped contain no fact absent from their grounding; a
  deliberately invented fact is rejected in **100%** of trials and replaced by a template draft.
- **SC-011**: With the model provider down or slow, a full cycle still completes inside the existing
  cycle interval, and the run record states how many drafts fell back.
- **SC-012**: On a machine with a container runtime and nothing else, the documented single command
  reaches a state where sign-in works and an unattended run appears, in **under 10 minutes** after the
  images are built. **Not claimed until run; until then the documents say "unverified".**
- **SC-013**: The README's skipped list distinguishes decisions from gaps, and every gap named in it is
  also in `clarifications.md`.

## Assumptions

- **Sign-in method**: email and password per tenant user, with a signed, expiring, revocable session.
  This is the simplest scheme that makes the credential — not the caller — the source of truth, and
  that a small team can own. Single sign-on (OIDC/SAML), multi-factor authentication, self-service
  sign-up and email-driven password reset are **out of scope and named as such** (reset by an operator
  is in scope). Rationale and the alternative rejected are to be recorded in `clarifications.md`.
- **Ownership**: accounts already carry an owner reference from the CRM feed; mapping owners to users
  is part of this work. Demo users are created one per owner so a CSM's view is non-empty.
- **Customer contact does not exist in the data today** (verified: the generated feeds carry no contact
  address). The generator is extended to emit a primary contact per account, leaving a realistic share
  without one. Alternatives considered: tenant-supplied contact import, deriving a contact from inbound
  email senders. To be recorded in `clarifications.md`; neither is built here.
- **Email provider**: delivery goes through a provider-neutral interface with one real implementation
  (an authenticated mail-sending provider), plus the existing recording implementation. Provider-specific
  features (bounce webhooks, reply threading, open tracking, templating) are **out of scope**. Because
  bounces are not processed, a hard bounce is not known to the system; that limit is stated in the README.
- **Real sending is exercised in tests against a controllable fake provider.** No test sends real mail.
  Real delivery to a real inbox is a manual, operator-run check, not an automated one.
- **Language model**: one provider key held by the deployment (not per tenant); the model's name is
  configuration. Cost control is by the per-cycle and per-tenant bounds in FR-028. The system is
  verified against a scripted stand-in for the provider; a live call is a manual check.
- **Consent and compliance**: the tenant, not Pulse, is responsible for having a lawful basis to email
  its customers (001 clarifications, A6/B6). Pulse's part is: off by default, an opt-out mechanism honoured on
  every send, and nothing sent from the demo. Jurisdiction-specific content rules are out of scope.
- **Containers**: Docker is **not installed** on the development machine, so the container files will be
  written, reviewed and statically checked but **not run** here. They are flagged unverified (FR-034,
  SC-012) until run elsewhere. The alternative of leaving packaging undone was rejected.
- **The worker's system identity** is a deployment-level secret, not a user, so a compromised user session
  cannot start or alter cycles.
- **Backwards compatibility**: the existing tests that pass identity by header are migrated to the new
  mechanism in the same change; no header-trusting path remains behind a flag.
- **Not changed by this feature**: ingestion, features, the model, scoring, ranking, the evidence trail
  and the agent's decision logic. Any change that touches them is out of this spec's scope.
