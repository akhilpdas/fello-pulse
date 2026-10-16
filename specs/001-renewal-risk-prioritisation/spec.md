# Feature Specification: Renewal-Risk Prioritisation for Customer Success

**Feature Branch**: `001-renewal-risk-prioritisation`

**Created**: 2026-10-15

**Status**: Approved for implementation

**Input**: Forwarded request from VP Customer Success — "a dashboard with a health
score per account, red / yellow / green… and then automate the outreach — if an
account goes red, the system should email them."

---

## Problem Restatement

The request names two artefacts (a health-score dashboard, an automatic email). The
evidence in the request names a different problem.

What the VP actually reported is three facts:

1. **A CSM owns ~120 accounts and allocates attention by guessing.** The failure is
   not that they lack a colour per account; it is that they have no defensible
   ordering of where the next hour goes.
2. **Two renewals were lost that nobody saw coming, and the signals were already in
   Zendesk and product usage.** The failure is a *detection-and-lead-time* failure,
   not a reporting failure. A static colour would have been amber for months on both
   accounts and told nobody anything.
3. **The data is scattered, partial, and three years deep.** Any system that assumes
   complete data will be confidently wrong on the accounts that matter least and
   silently absent on the ones that matter most.

Therefore the problem this feature solves is: **give each CSM, unprompted, a short
ranked list of the accounts where their attention changes the outcome this week, with
the evidence that justifies the ranking and a draft of the first move.**

The health score is retained as a *display affordance* because the business asked for
it and it is a reasonable way to glance at a portfolio. It is explicitly **not** the
ranking primitive. See "Where This Specification Disagrees With the Request".

---

## Where This Specification Disagrees With the Request

### D1 — A single health score is not actionable; we predict a dated outcome instead

A score that blends support unhappiness, usage decline and payment friction into one
number destroys the only information a CSM can act on: *which* thing is wrong. Two
accounts at 62 need opposite interventions.

**Instead**: the model predicts one specific, dated, checkable outcome — the
probability that an account churns or materially contracts within 90 days of the
decision date. That probability is decomposed into its drivers, and the drivers are
what the CSM reads. The 0–100 health score shown in the UI is a monotone
transformation of that probability, provided for glanceability, and the product never
asks a CSM to act on the number alone.

### D2 — Automatically emailing a red account is the single most damaging thing we could build

Three independent reasons, any one of which is sufficient:

- **Precision.** At 5,000 accounts, a model operating at a realistic precision will
  mark hundreds of accounts red per cycle. Auto-sending means hundreds of
  unnecessary "we noticed you might be unhappy" emails per cycle to customers who are
  fine. That is a churn *cause*, not a churn *control*.
- **Causality.** A large share of red accounts are red *because our support is
  failing them*. An automated cheerful check-in to a customer with an unresolved P1
  ticket sitting at nine days is not neutral; it is insulting, and it is the exact
  message a CSM would never send.
- **Ownership.** The highest-ACV accounts going red are the ones where the
  relationship is the asset. Those conversations are a phone call from a named human,
  not a templated send.

**Instead**: the system automates the *preparation* and gates the *sending*. Every
cycle, the agent assembles the evidence, selects an appropriate play, and drafts the
outreach so that the CSM's Monday starts with a reviewed-and-send decision rather
than a blank page. Autonomous sending exists, but only for plays an operator has
explicitly allowlisted as low-stakes and high-confidence — the canonical example
being a feature-adoption nudge to an account that never activated a core feature —
and always under per-account suppression and per-tenant rate limits.

The thing being automated away is the CSM's research hour, not their judgement.

### D3 — Level is the wrong signal; change and lead time are the signal

An account that has been amber for fourteen months is a known quantity. An account
that moved from green to amber in nine days with a renewal in six weeks is the
emergency, and a red/yellow/green dashboard renders those two identically.

**Instead**: the ranked queue is driven by expected value at risk — calibrated
probability × contract value × a renewal-proximity urgency factor — and the primary
UI element on every row is the *delta since last cycle* with the feature-level
explanation of what moved. "Why is this new?" is a first-class question the product
answers.

### D4 — The queue must respect the CSM's actual capacity

Forty red accounts is the same uselessness as the original spreadsheet, differently
coloured. A list a human cannot work is not a work queue.

**Instead**: the queue is bounded to a configured weekly capacity per CSM, and the
model is evaluated at that operating point (precision and captured-ACV in the top-N)
rather than on an aggregate metric that nobody operates at.

### D5 — The system must be allowed to say "I don't know"

The request implies every account gets a colour. Roughly a tenth of accounts in a
realistic estate have too little evidence to score — new logos, accounts whose
billing identity never linked, whole tenants with a source not connected. Giving
those accounts a confident green is how a system loses the trust of the team using
it, and it is the specific failure mode that precedes "nobody saw it coming".

**Instead**: thin-evidence accounts are routed to an explicit low-confidence state
with a stated reason and the missing-data remedy. They appear in a separate bucket
with its own count, never as healthy.

### D6 — "Nothing slips" is not achievable and should not be promised

The honest claim is a measurable reduction in the number of churn events that arrive
with no prior warning, and a measurable increase in lead time on the ones that do get
flagged. The system reports both against a backtest, and the README states the
residual rate rather than implying zero.

---

## What We Need From the Business and Did Not Receive

These are open questions whose answers would change the implementation. Each is
recorded here with the assumption adopted in its absence, and each is listed in
`clarifications.md` with the reasoning.

| # | Question | Why it matters | Assumption adopted |
|---|---|---|---|
| B1 | What exactly counts as a "lost renewal" in your systems — a Salesforce stage, a Stripe cancellation, a non-renewal at contract end, a >25% downgrade? | This *is* the training label. Getting it wrong makes every number downstream meaningless. | Churn-or-material-contraction: subscription cancelled, or MRR reduced ≥25%, observed in Stripe and corroborated by Salesforce stage. Configurable per tenant. |
| B2 | Do you have reliable contract end dates and ACV per account? | Without ACV there is no value-at-risk and the ranking degenerates to pure probability, which over-serves cheap accounts. | Assumed present on the Salesforce account record; accounts missing ACV fall back to annualised Stripe MRR, and are flagged if both are absent. |
| B3 | How many meaningful customer touches can one CSM make per week? | This sets the operating point the model is tuned and reported at. | 10 per CSM per week, configurable per tenant. |
| B4 | Do you have history of which interventions were attempted and whether the account was saved? | Without it we can model *risk* but not *treatment effect*, so we cannot tell a CSM which play works — only that risk exists. | Not available. The system models risk only, and records play outcomes from day one so that uplift modelling becomes possible later. Stated as a known limitation. |
| B5 | Who owns the account relationship at renewal — CS or the AE? | Determines whether outreach from CS is even appropriate, and who the queue belongs to. | CS owns the renewal motion; the account's Salesforce owner is the queue owner. |
| B6 | Which of your tenants have consented to outbound automated email, and under what jurisdiction? | Auto-send without this is a compliance incident, not a feature. | Auto-send defaults to off for every tenant and every play; it must be switched on per tenant per play by an operator. |
| B7 | Which two accounts were the renewals you lost? | They are the most valuable test case in the building — a retrospective check of whether the system would have flagged them, and with how much lead time. | Synthesised equivalents are planted in the generated data as a named retrospective fixture, and the backtest reports lead time against them. |
| B8 | What does the business commit to doing when an account is marked red? | A tier with no committed action attached to it is decoration. | Red is defined as "a human contact is owed within five business days", which is what makes the capacity bound in B3 binding. |

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — The Monday queue (Priority: P1) 🎯 MVP

Dana owns 118 accounts. She opens Pulse on Monday at 09:00. She does not configure
anything, run anything, or choose a report. The work is already done: a ranked list
of ten accounts, each with a one-line reason, the dollar value at risk, days to
renewal, and what changed since last Monday. She works down the list. By 09:40 she
has made four calls and sent two reviewed emails.

**Why this priority**: This is the entire product. Everything else in this
specification exists to make this list trustworthy. If only this story ships, the
original problem — a CSM guessing from a spreadsheet — is solved.

**Independent Test**: Seed a tenant, run one unattended cycle, request the queue for
a CSM, and assert it returns a bounded, ordered list where every row carries a reason,
a value at risk, a renewal distance and a since-last-cycle delta — with no human
having triggered the computation.

**Acceptance Scenarios**:

1. **Given** a tenant with scored accounts and a CSM with capacity 10, **When** Dana
   opens her queue, **Then** she sees at most 10 accounts ordered by expected value at
   risk, and the count of everything below the cut is shown so she knows what she is
   not seeing.
2. **Given** an account that entered the queue this cycle and was absent last cycle,
   **When** Dana views the row, **Then** it is marked as newly surfaced and names the
   feature movement that caused it.
3. **Given** an account with a renewal 300 days out and an identical risk probability
   to one renewing in 30 days, **When** both are ranked, **Then** the nearer renewal
   ranks higher, and the urgency multiplier is visible in the row's explanation.
4. **Given** Dana took an action on an account last week, **When** the queue is built
   this week, **Then** that account is suppressed from re-surfacing for the configured
   window unless its risk materially worsened.

---

### User Story 2 — Tracing a number back to the evidence (Priority: P1)

Dana does not trust the ranking yet. She clicks the top account. She sees that 41% of
the risk contribution comes from support experience, expands it, and reads the four
Zendesk tickets behind it — including the P1 opened eleven days ago that is still
unresolved with a first response time of 32 hours. She clicks the ticket and sees the
record Pulse ingested, with its timestamps. She now believes the number, and she knows
what to say on the call.

**Why this priority**: Co-equal P1 with the queue. A ranking a CSM cannot interrogate
is a ranking a CSM will abandon in week two, and then the system has achieved
nothing. This is also the constitutional requirement that nothing unexplained reaches
a human.

**Independent Test**: For any persisted score, assert that every non-trivial feature
contribution resolves to at least one source record identifier, that each identifier
is retrievable with its original payload, and that the displayed contributions sum to
the model's output within tolerance.

**Acceptance Scenarios**:

1. **Given** a scored account, **When** Dana opens it, **Then** she sees the
   contributions ranked by magnitude, each labelled in business language, each
   expandable to the feature values and then to the source records.
2. **Given** a score that changed since the previous cycle, **When** Dana asks what
   changed, **Then** she sees a feature-level diff of the two feature vectors with the
   contribution change attributed per feature.
3. **Given** an account whose risk is driven by a data-quality problem rather than
   customer behaviour, **When** Dana opens it, **Then the explanation says so** rather
   than attributing the signal to the customer.
4. **Given** any number displayed anywhere in the product, **When** Dana follows it
   down, **Then** she reaches either a source record or a stated computation, never a
   dead end.

---

### User Story 3 — The system works while nobody is watching (Priority: P1)

Nobody runs Pulse. At 02:00 on Sunday the worker wakes, pulls new records from the
five sources, recomputes features for the accounts with new evidence, rescores them,
notices that 23 accounts moved materially, selects a play for each, drafts the
outreach, and writes a run record. At 09:00 Monday the queues for every CSM in every
tenant are already correct. Nothing was sent to a customer without a human saying so,
except the two feature-adoption nudges the tenant's operator allowlisted.

**Why this priority**: Co-equal P1. A system a CSM has to remember to refresh is a
spreadsheet with extra steps, and the brief requires work that no human triggers.

**Independent Test**: Start the worker with no API traffic and no human input, let one
cycle complete, and assert that scores advanced, a run record exists describing what
was and was not done, drafts were created in a pending-review state, and no
non-allowlisted message left the system.

**Acceptance Scenarios**:

1. **Given** no human interaction of any kind, **When** a scheduled cycle fires,
   **Then** ingestion, feature refresh, scoring, change detection, play selection and
   drafting all advance, and a run record captures each stage's counts.
2. **Given** a worker that is killed mid-cycle, **When** a worker starts again,
   **Then** the leased work resumes and no account is double-processed and no draft is
   duplicated.
3. **Given** two workers running concurrently, **When** both poll for work, **Then**
   each unit of work is claimed exactly once.
4. **Given** a play that is not allowlisted for autonomous sending, **When** the agent
   selects it, **Then** the draft is queued for human approval and the run record
   states that dispatch was withheld and why.
5. **Given** an account contacted two days ago, **When** the agent considers it again,
   **Then** suppression blocks the outreach and the decision is recorded rather than
   silently dropped.

---

### User Story 4 — Reviewing and sending the drafted outreach (Priority: P2)

Dana reads the draft for the top account. It references the unresolved P1 by name and
proposes a specific remedy; it does not say "I noticed you may be experiencing
challenges". She edits one sentence, approves, and it sends. The approval, the edit
and the send are all recorded against the account.

**Why this priority**: P2 because the queue plus the evidence already solves the
stated problem; drafting compounds the time saving but is not load-bearing. It is also
the piece most likely to need tuning with the actual CS team's voice, so building it
behind a review gate is deliberate.

**Independent Test**: Generate a draft for a known account and assert every factual
claim in it maps to a feature or source record in that account's evidence set, that
approval transitions state and records the actor, and that no send occurs without an
approval or an allowlist entry.

**Acceptance Scenarios**:

1. **Given** a drafted message, **When** Dana views it, **Then** the evidence it was
   grounded in is shown beside it.
2. **Given** a draft containing a claim not supported by the evidence set, **When** it
   is validated, **Then** it is rejected before a human ever sees it and the rejection
   is logged.
3. **Given** no language model is configured, **When** a play requires a draft,
   **Then** a deterministic evidence-filled template is produced and the product
   continues to function.

---

### User Story 5 — Two customer organisations on one deployment (Priority: P2)

Northwind's operator sets capacity to 15 and allowlists the adoption nudge. Globex
sets capacity to 8, allowlists nothing, and has never connected Gmail. Neither can see
the other's accounts, scores, drafts or run records — including through a bug.

**Why this priority**: P2 in sequencing only; it is a non-negotiable in the brief and
a correctness property, so it is built into the schema from the first migration rather
than retrofitted. It is listed after the single-tenant stories because they are what
prove the product works at all.

**Independent Test**: Issue deliberately unfiltered queries against every
tenant-scoped table while holding tenant A's session claim, and assert zero rows
belonging to tenant B are returned.

**Acceptance Scenarios**:

1. **Given** a session authenticated for Northwind, **When** any query runs — including
   one that forgot its tenant filter — **Then** no Globex row is returned, because the
   database refuses it.
2. **Given** Globex has no Gmail source connected, **When** Globex accounts are
   scored, **Then** email-derived features are absent rather than zero, the model
   handles their absence natively, and the coverage is reported to the operator.
3. **Given** per-tenant configuration of capacity, thresholds and allowlists, **When**
   either tenant changes a setting, **Then** only that tenant's behaviour changes.

---

### User Story 6 — The operator asks whether to trust the model (Priority: P3)

Before rollout, Northwind's operations lead wants to know whether this is better than
the spreadsheet. She opens the model report: performance at the operating point she
will actually run, the lift over the heuristic a human would have written, the
calibration curve, per-tenant breakdowns, median lead time before a churn event, and
the retrospective check against the two accounts that were lost.

**Why this priority**: P3 by sequence, not by importance — it is the deliverable that
decides adoption, but it reports on the system rather than constituting it.

**Independent Test**: Run the evaluation and assert the report contains the operating
point metrics, both baselines, calibration, per-tenant slices and lead-time
distribution, with the data seed and model version recorded.

**Acceptance Scenarios**:

1. **Given** a trained model, **When** evaluation runs, **Then** metrics are reported
   at the configured weekly capacity, not only as aggregates.
2. **Given** the heuristic baseline, **When** compared, **Then** the lift is stated
   with its direction and the comparison is reproducible from the recorded seed.
3. **Given** a model that does not beat the baseline at the operating point, **When**
   the gate runs, **Then** promotion to serving fails.

---

### Edge Cases

**Data arrival and ordering**

- A Zendesk ticket from nine days ago arrives today. It must affect today's score and
  must not retroactively alter the score computed six days ago, which remains on
  record as what the system knew then.
- The same Stripe event is delivered twice with the same source identifier. It is
  stored once; the second delivery is a no-op, not a duplicate signal.
- A source backfills six months of history in one batch. The ingestion must not
  interpret the arrival spike as customer behaviour, and the watermark must advance
  correctly so the next cycle does not re-read it.
- Two events share an `occurred_at` to the millisecond. Ordering must be total and
  stable, so feature computation is deterministic.

**Missing, partial and broken data**

- An account exists in Salesforce with no Stripe customer, no tickets and no usage.
  It must be low-confidence with "no linked billing identity" as the stated reason,
  never green.
- A whole tenant has no Gmail connection. Email features must be *absent*, which the
  model treats as information, rather than *zero*, which the model would read as
  "the customer has gone silent".
- An account's `seats` field is null for part of its history. Per-seat features must
  be absent for that period rather than dividing by a guess.
- A source renames a field midway through the three years of history. Both spellings
  must normalise to one internal field, and the adapter must have a test for each.
- An account appears under two identities across sources and the mapping table is
  incomplete. Identity resolution must be explicit, its failures must be visible, and
  an unresolved identity must not silently create a second account.

**Model and scoring**

- An account whose entire history is 11 days long. Window features cannot be computed;
  the abstain path must trigger rather than extrapolate.
- A new tenant with no churn history of its own. The shared model must still serve it,
  and the leave-one-tenant-out evaluation must report how much worse it is.
- A feature's distribution shifts because a source integration changed. Drift must be
  detectable from persisted feature snapshots without re-deriving history.
- The model scores an account above threshold purely because of a data outage. The
  explanation must attribute it to data quality, and the play selector must not send
  customer outreach on that basis.

**Autonomous operation**

- A cycle takes longer than the interval to the next cycle. The next tick must not
  pile on; it must observe the lease and defer.
- The LLM provider is down. Drafting must fall back to templates and the run record
  must note the degradation; the queue must still be correct.
- A play's send fails at the transport layer. It must be retried with backoff a bounded
  number of times and then surfaced, never silently abandoned.
- A tenant's operator revokes auto-send mid-cycle. Nothing allowlisted-but-not-yet-sent
  may go out under the old policy.

**Human interaction**

- Two CSMs are assigned the same account. It must appear once per owner without
  double-sending outreach.
- A CSM marks a flagged account as a false positive. That must be recorded as labelled
  feedback for future training, not merely dismissed from a list.
- An account is deliberately being allowed to churn. It must be suppressible with a
  reason, and excluded from the queue without being deleted.

---

## Requirements *(mandatory)*

### Functional Requirements — Data foundation

- **FR-001**: System MUST ingest records from five source families — CRM
  (Salesforce-shaped), email (Gmail-shaped), support (Zendesk-shaped), product usage,
  and billing (Stripe-shaped) — into a single append-only event log.
- **FR-002**: Every stored record MUST carry `tenant_id`, `source`, `source_event_id`,
  `occurred_at`, `received_at`, a normalised event type, and its original payload.
- **FR-003**: Ingestion MUST be idempotent on `(tenant_id, source, source_event_id)`;
  re-delivering a record MUST NOT create a second row or a second signal.
- **FR-004**: Ingestion MUST maintain a per-tenant, per-source watermark so each cycle
  reads only what is new, and MUST advance it only after a batch is durably stored.
- **FR-005**: System MUST accept records whose `occurred_at` precedes already-ingested
  records, without reordering or rejecting them.
- **FR-006**: System MUST resolve source-native identifiers (Salesforce account,
  Stripe customer, Zendesk organisation) to one internal account, MUST record the
  resolution, and MUST surface unresolved identities rather than guessing.
- **FR-007**: System MUST normalise known source schema variations, including a field
  renamed partway through the history, to a single internal representation.

### Functional Requirements — Features

- **FR-008**: Feature computation MUST be a pure function of `(tenant_id, account_id,
  as_of)` and MUST read only records where `received_at <= as_of`.
- **FR-009**: Features MUST distinguish *absent* from *zero*, and MUST propagate
  absence to the model rather than imputing a value.
- **FR-010**: System MUST maintain an explicit denylist of event types that are
  mechanically downstream of the predicted outcome, and feature code MUST be unable to
  read them.
- **FR-011**: System MUST persist, for every computed feature vector, the identifiers
  of the source records that contributed to each feature group.
- **FR-012**: System MUST compute per-source coverage and recency signals and expose
  them both as model inputs and as operator-facing data-quality reporting.

### Functional Requirements — Model

- **FR-013**: The ranking MUST derive from a supervised model fitted on Pulse's
  historical data; an LLM MUST NOT contribute to any score, tier, order or filter.
- **FR-014**: The model MUST predict a dated outcome — churn or material contraction
  within a fixed horizon following the decision date — defined per tenant.
- **FR-015**: Training examples MUST be account-level snapshots taken at historical
  decision dates, with features computed as-of that date and labels drawn only from
  the horizon after it.
- **FR-016**: Evaluation MUST use a time-based split, MUST report performance at the
  configured weekly capacity operating point, and MUST compare against both a trivial
  baseline and a stated heuristic baseline.
- **FR-017**: Predicted probabilities MUST be calibrated on held-out data, because
  they are multiplied by contract value.
- **FR-018**: System MUST report per-tenant performance and a leave-one-tenant-out
  result for cold-start tenants.
- **FR-019**: System MUST report lead time — the distribution of days between first
  crossing the risk threshold and the actual churn event.
- **FR-020**: Promotion of a model to serving MUST fail if it does not beat the
  heuristic baseline at the operating point.
- **FR-021**: Every model artefact MUST be versioned and accompanied by a model card
  recording training window, feature list, metrics, seed and data version.

### Functional Requirements — Scoring, ranking and explanation

- **FR-022**: System MUST persist every score with its model version, full feature
  vector, per-feature contributions, and the arithmetic of the final priority.
- **FR-023**: Ranking MUST be computed as calibrated probability × value at risk ×
  renewal-proximity urgency, adjusted by suppression, and every factor MUST be visible
  to the user.
- **FR-024**: System MUST bound each CSM's queue to a configured weekly capacity and
  MUST state how many accounts fall below the cut.
- **FR-025**: System MUST compute a red/amber/green tier for display, derived from the
  risk probability and tenant-configured thresholds.
- **FR-026**: System MUST route accounts with insufficient evidence to an explicit
  low-confidence state with a machine-readable reason and a stated remedy, and MUST
  NOT present them as healthy.
- **FR-027**: System MUST expose a feature-level diff between any two scores for an
  account, attributing the change in output to the change in each feature.
- **FR-028**: Every displayed contribution MUST resolve to retrievable source records
  with their original payloads.

### Functional Requirements — Autonomous operation

- **FR-029**: A worker MUST advance the pipeline on a schedule with no human trigger.
- **FR-030**: Work MUST be claimed from a durable queue under a lease, so that a
  crashed worker's work is retried and concurrent workers never double-process.
- **FR-031**: Each cycle MUST write a run record containing per-stage counts, the
  decisions taken, the decisions declined with their reasons, and the resulting
  artefacts.
- **FR-032**: The agent MUST detect material change between consecutive scores — tier
  crossings, probability movement beyond a threshold, and newly dominant drivers — and
  act on change rather than on level alone.
- **FR-033**: The agent MUST select a play from a registry by rule, where eligibility
  depends on the dominant risk driver, value tier, renewal proximity, confidence,
  suppression state and tenant policy.
- **FR-034**: Outreach MUST default to a pending-human-approval state. Autonomous
  dispatch MUST require an explicit per-tenant, per-play allowlist entry.
- **FR-035**: Autonomous dispatch MUST respect per-account suppression windows and
  per-tenant rate limits, and every suppressed decision MUST be recorded.
- **FR-036**: Drafted language MUST be grounded only in that account's evidence set,
  MUST be validated against it before a human sees it, and MUST fall back to a
  deterministic template when no language model is available.
- **FR-037**: The scoring and ranking path MUST function with language-model support
  entirely disabled.

### Functional Requirements — Multi-tenancy and access

- **FR-038**: Every tenant-scoped table MUST carry `tenant_id`, and isolation MUST be
  enforced by database row-level security against a session claim.
- **FR-039**: The application MUST connect using a role that cannot bypass row-level
  security.
- **FR-040**: Cross-tenant operations MUST run under a separately named path that
  never serves a request.
- **FR-041**: Per-tenant configuration MUST cover capacity, tier thresholds, horizon
  definition, play allowlists, suppression windows and rate limits.
- **FR-042**: Users MUST see only the accounts they own, within only their tenant.

### Functional Requirements — CSM-facing product

- **FR-043**: Users MUST be able to open a ranked queue with, per row: account, tier,
  expected value at risk, probability, days to renewal, the dominant driver in business
  language, and the change since the previous cycle.
- **FR-044**: Users MUST be able to open an account and read the full evidence trail
  down to source records.
- **FR-045**: Users MUST be able to see the score history for an account and the
  explanation of each movement.
- **FR-046**: Users MUST be able to review, edit, approve or reject a drafted message,
  and those actions MUST be recorded against the account with the actor.
- **FR-047**: Users MUST be able to mark a flagged account as a false positive with a
  reason, and that MUST be retained as labelled feedback.
- **FR-048**: Users MUST be able to suppress an account from the queue with a reason
  and an expiry, without deleting it.
- **FR-049**: Users MUST be able to inspect the autonomous run log for their tenant.

### Key Entities

- **Tenant** — a customer organisation using Pulse. Owns all other data. Carries
  configuration: horizon, thresholds, capacity, allowlists, limits.
- **Account** — an internal account record, the unit that is scored. Holds
  firmographics, ACV, renewal date, owner, and its resolved source identities.
- **Identity Link** — a mapping from a source-native identifier to an internal
  account, with the resolution method and confidence, including unresolved entries.
- **Source Event** — one immutable ingested record: tenant, source, source event id,
  normalised type, `occurred_at`, `received_at`, original payload.
- **Ingestion Watermark** — per tenant and source, the high-water mark of what has
  been durably read.
- **Feature Snapshot** — the feature vector for an account as-of a decision time, with
  per-feature-group evidence references and coverage metadata.
- **Model Version** — a fitted artefact with its model card: training window, feature
  list, metrics, calibration, seed, data version, and promotion state.
- **Score** — a scored account at an `as_of`: probability, tier, confidence, feature
  snapshot reference, contributions, and the ranking arithmetic.
- **Risk Driver** — a named business-language grouping of features (support
  experience, usage decline, relationship engagement, payment friction, commercial
  signals, data quality) with its contribution and evidence.
- **Play** — a named intervention with eligibility rules, a message template, a
  stakes classification, and whether it is allowlisted for autonomous dispatch.
- **Action** — a selected play instance for an account: its state (drafted, pending
  approval, approved, sent, rejected, suppressed, failed), its draft, its grounding
  evidence, and its actor history.
- **Agent Run** — one autonomous cycle: timing, per-stage counts, decisions taken and
  declined with reasons, and errors.
- **Work Lease** — a claim on a unit of autonomous work, with owner and expiry.
- **Feedback** — a human judgement on a score or action, retained for training.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A CSM opening the product on Monday reaches a ranked, bounded,
  evidence-backed work list with zero configuration and zero manual triggering.
- **SC-002**: Every number displayed in the product resolves, in at most three
  interactions, to either a source record or a stated computation. No dead ends.
- **SC-003**: At the configured capacity of 10 accounts per CSM per week, the model's
  precision exceeds the heuristic baseline's precision at the same cut, and the lift
  is reported with its seed.
- **SC-004**: Predicted probabilities are calibrated such that accounts predicted in a
  given decile churn at a rate within a reported tolerance of that decile.
- **SC-005**: Median lead time between the first threshold crossing and the churn
  event is reported, and exceeds 30 days on the backtest.
- **SC-006**: The planted retrospective accounts — the synthetic equivalents of the two
  renewals lost with no warning — are flagged by the backtest, with their lead times
  stated.
- **SC-007**: A complete autonomous cycle over 5,000 accounts across all tenants
  completes within the scheduling interval, and the run record proves which stages ran.
- **SC-008**: Deliberately unfiltered queries under one tenant's session return zero
  rows from any other tenant, for every tenant-scoped table.
- **SC-009**: Injecting a source record dated after a score's `as_of` does not change
  that score's feature vector when recomputed.
- **SC-010**: Permuting training labels collapses model performance to chance,
  demonstrating no target leakage.
- **SC-011**: No customer-facing message leaves the system without either a recorded
  human approval or a recorded per-tenant allowlist entry for that play.
- **SC-012**: Accounts with insufficient evidence appear in a low-confidence bucket
  with a stated reason, and none of them is displayed as green.
- **SC-013**: With language-model support disabled, the system still produces a correct
  queue and template-based drafts.
- **SC-014**: A documented single command takes an empty database to a running, scored,
  populated system.

---

## Assumptions

- The five sources are reachable as batch feeds of normalised records; building and
  authenticating real Salesforce, Gmail, Zendesk and Stripe connectors is out of scope
  and is replaced by a generator that emits the same contracts, so the ingestion layer
  is real even though the transport is not.
- Product usage arrives as daily per-account-per-user rollups rather than raw
  clickstream. Raw clickstream at this estate size would be hundreds of millions of
  rows and no real integration would deliver it to a CS tool; the rollup is both the
  realistic contract and the honest scoping decision.
- Historical outcomes exist for roughly three years, which is enough for a time-based
  split with a usable test block. Tenants onboarded recently have less, and the
  evaluation reports that asymmetry rather than hiding it.
- One shared model serves all tenants, with tenant identity available as a feature and
  per-tenant performance reported. Per-tenant models are rejected for now because most
  tenants have too few churn events to fit one; this is recorded as a decision, not an
  oversight.
- Email send transport is abstracted behind an interface with a recording
  implementation. Real delivery, bounce handling and reply threading are out of scope
  and named as such. **[Partly superseded by spec 002: a real SMTP transport, send gate,
  demo mode and opt-outs now exist; bounce handling and reply threading remain out of scope.]**
- Authentication is a signed bearer token carrying tenant and user claims. A real
  identity provider is out of scope; the tenant claim path it feeds is real, because
  that is the part isolation depends on. **[Superseded by spec 002: real sign-in with
  opaque server-side sessions; the tenant claim now comes from a verified session, not a
  header. SSO/MFA remain out of scope. See clarifications B-28.]**
- Time is injectable throughout. Nothing calls the system clock directly, because a
  system whose correctness depends on "now" cannot be tested for point-in-time
  behaviour.
