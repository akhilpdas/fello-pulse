# Clarifications

**Feature**: 001-renewal-risk-prioritisation | **Date**: 2026-10-15

Two kinds of ambiguity are recorded here. **Section A** holds questions only the
business can answer; each is carried into `spec.md` as an open item with the
assumption adopted in its absence. **Section B** holds decisions that were genuinely
ours to make, where the request was silent and we had to choose; these are resolved,
not open, and the reasoning is recorded so the choice can be argued with.

---

## Section A — Open questions for the business

These are listed in `spec.md` under "What We Need From the Business and Did Not
Receive" (B1–B8). They are repeated here with the full reasoning rather than the
summary table.

### A1 (B1) — The definition of the label

**Question**: What exactly counts as a lost renewal?

This is the single highest-leverage unknown in the project. Everything downstream —
features, metrics, thresholds, the ranking, the claim that the system works — is
defined relative to this. Four plausible definitions exist in a Salesforce + Stripe
estate and they disagree materially:

1. Salesforce renewal opportunity moved to Closed Lost.
2. Stripe subscription cancelled.
3. Contract end date passed with no renewal record created.
4. Account retained but MRR cut by a large fraction.

(1) is recorded by humans and therefore late, inconsistent, and sometimes never
updated. (2) is reliable but fires at the end of a notice period, often months after
the decision was made, and misses accounts that stay on a shrunken plan. (3) is a
silent event with no record to key on, and is exactly the kind of churn that "nobody
saw coming". (4) is economically a partial loss that CS is measured on but that none
of the first three capture.

**Adopted**: churn-or-material-contraction — a Stripe cancellation, *or* an MRR
reduction of ≥25% sustained past one billing cycle, corroborated where possible by
Salesforce stage. Rationale: it is observable from billing (so it is consistent and
timely), it captures downgrades (so the model learns the contraction signal that
precedes full churn), and the sustained-past-one-cycle condition rejects billing
noise. The threshold and the corroboration requirement are per-tenant configuration,
because this is precisely the parameter a real customer will argue about.

**Risk if wrong**: a definition that is too narrow starves the model of positives; one
too broad teaches it to chase ordinary plan changes. Mitigated by making it
configurable and by reporting positive-class rate per tenant in the model card.

### A2 (B2) — ACV and renewal dates

**Question**: Are contract value and contract end date reliably populated?

Both are load-bearing. ACV is the multiplier that turns a probability into a
prioritisation; renewal date is the urgency term. If ACV is missing the ranking
collapses to pure probability, which systematically over-serves small accounts,
because small accounts churn more.

**Adopted**: ACV read from the CRM account record, falling back to annualised billing
MRR, and if both are absent the account is flagged as unrankable-by-value and ranked
on probability alone with that fact displayed. We do not impute a segment median,
because an invented dollar figure propagates into an expected-loss number a human will
quote to their VP.

### A3 (B3) — CSM capacity

**Question**: How many meaningful customer touches can one CSM make in a week?

This is not a UI parameter. It is the operating point at which the model must be
tuned, thresholded and reported, and reporting at the wrong operating point is how
models look good in a deck and fail in use.

**Adopted**: 10 per CSM per week, per-tenant configurable. Rationale: at ~120 accounts
and a five-day week, 10 substantive touches is the upper end of plausible alongside
reactive work. If the real number is 4, the thresholds change but no code does.

### A4 (B4) — Intervention history

**Question**: Do you have a record of which saves were attempted and which worked?

Without it, we can rank *risk* but we cannot rank *treatable risk*. The account most
likely to churn may be the one nobody can save; the right call may be the one at 40%
where a QBR flips it. That is an uplift question and it needs treatment history.

**Adopted**: not available, so the system models risk only. This is stated as a
limitation in the README rather than finessed. Mitigation: every play, approval,
send, and subsequent outcome is recorded from day one specifically so the dataset
needed for uplift modelling accrues from the moment the system is live. The schema
is built for the question we cannot yet answer.

### A5 (B5) — Who owns the renewal

**Adopted**: CS owns the renewal motion and the CRM account owner is the queue owner.
Noted because if the AE owns it, the queue has the wrong audience and the drafted
outreach has the wrong voice — a product problem, not a modelling one.

### A6 (B6) — Consent and jurisdiction for automated email

**Adopted**: auto-send is off by default for every tenant and every play, and must be
switched on per tenant per play by an operator. We will not ship a default that can
create a compliance incident on behalf of a customer who never asked for it.

### A7 (B7) — The two lost renewals

**Question**: Which accounts were they?

They are the most valuable test in the building: a retrospective check of whether the
system would have flagged them and with how much warning. "Would it have caught the
ones we missed" is the question that decides adoption, and it cannot be answered with
aggregate metrics.

**Adopted**: two synthetic analogues are planted deliberately in the generated data —
one slow support-driven decline, one fast champion-departure collapse — and the
backtest reports whether each was flagged and with what lead time. When the real
account identifiers arrive, the same harness runs against the real history unchanged.

### A8 (B8) — What the business commits to on red

**Adopted**: red means a human contact is owed within five business days. Stated
because a tier with no committed action is decoration, and because it is the
commitment that makes the capacity bound binding rather than advisory.

---

## Section B — Resolved decisions where the request was silent

### B-1 — What does the model predict?

**Options considered**

| Option | Why rejected / chosen |
|---|---|
| A continuous "health score" fitted to nothing | Rejected. Unfalsifiable: no outcome to check it against, so it can never be shown to be wrong, and therefore never improved. This is what the request implicitly asked for. |
| P(non-renewal) conditioned on being inside a renewal window | Rejected as the primary target. Annual contracts mean most account-weeks have no renewal in range, so the model is undefined for most of the panel and cannot answer "who do I call this week". |
| P(churn or ≥25% contraction within 90 days of the decision date) | **Chosen.** Defined for every account-week, captures off-cycle cancellation and downgrade, and directly answers the question the CSM is asking. |
| Multi-class (churn / contract / renew / expand) | Rejected for v1. More informative but splits an already thin positive class four ways, and the action is the same for the two loss classes. Recorded as a natural v2. |

**Horizon choice**: 90 days. Shorter (30) gives too little lead time to act, which is
the entire complaint in the request. Longer (180) buries the signal in noise and
makes the probability nearly uniform across the estate. 90 is long enough that a CSM
can still change the outcome and short enough that behaviour predicts it.

### B-2 — Where does renewal proximity enter?

**Chosen**: not as a model feature driving the score, but as an explicit multiplier in
the ranking layer.

Two reasons. First, separation of concerns: the model answers "how likely is this to
go wrong", the business layer answers "how much do I care right now". Mixing them
means a change to CS prioritisation policy requires retraining a model. Second,
explainability: "61% risk × $42k × 1.8× because renewal is in 38 days" is arithmetic
a CSM can check, whereas a learned interaction between renewal distance and risk is
not. Days-to-renewal *is* available to the model as a feature for its predictive
content; what it does not do is secretly encode the prioritisation policy.

### B-3 — Which model family?

**Chosen**: gradient-boosted trees (scikit-learn `HistGradientBoostingClassifier`),
with isotonic calibration on a held-out time block.

Rationale: the decisive property is **native handling of missing values**. A tenth of
this estate has partial data, a whole tenant has a source missing, and absence is
informative — an account with no email history is not an account with zero emails.
Boosted trees learn a split direction for missing natively, so absence is modelled
rather than imputed. Imputing a median would fabricate evidence, which the
constitution forbids. Secondary rationale: nonlinearity and interactions matter here
(a usage drop means something different on a 5-seat account than a 500-seat one), tree
ensembles are cheap to fit and re-fit, and they support exact per-prediction
attribution via TreeSHAP, which User Story 2 requires.

Rejected: logistic regression (kept as a baseline — interpretable but needs imputation
and hand-built interactions); a neural model (no benefit at this width and sample
size, worse attribution, more to defend); survival models such as Cox (a better fit to
the *question* of time-to-event, and recorded as the most interesting v2 direction,
but the discrete 90-day panel formulation is easier to evaluate honestly and to
explain to a CSM).

### B-4 — How is the training panel constructed?

**Chosen**: weekly account-level snapshots. For each tenant, each account, each Monday
in the training window, compute features as-of that Monday using only records with
`received_at <=` that Monday, and label from the following 90 days.

Alternatives rejected: one row per account (throws away almost all the signal and
gives a few thousand rows); one row per account per day (7× the rows for almost no new
information, and adjacent days are near-duplicates that inflate apparent performance).
Weekly matches the cadence the product actually runs at, which is the cadence it
should be evaluated at.

**Splitting**: time-based, train on the earliest block, validate on the next,
calibrate and test on the most recent. An account legitimately appears in both train
and test at different dates — that is exactly the deployed situation and excluding it
would understate performance. A grouped-by-account split is additionally reported as a
sanity check against memorisation, and leave-one-tenant-out is reported for cold-start
tenants.

### B-5 — Why not let an LLM do the scoring?

Beyond the brief requiring a fitted model: an LLM's judgement cannot be calibrated, so
its output cannot be multiplied by a dollar figure; it cannot be backtested against
three years of history at 5,000 accounts without absurd cost; it is not stable across
runs, so "why did this move" becomes unanswerable; and it has no mechanism to abstain
honestly on thin data — it will confidently narrate a story about an account with
eleven days of history.

The LLM's correct job here is the one thing the fitted model cannot do: write a
sentence a human would be willing to send. It is confined to that, behind an
evidence-grounding check, and the system runs without it.

### B-6 — How is tenant isolation enforced?

**Chosen**: PostgreSQL row-level security against a session claim set per request,
with the application connecting as a role holding `NOBYPASSRLS`.

The alternative — a `tenant_id` filter in every query, or a scoped-session pattern in
the ORM — was rejected as the *control* (it is retained as defence in depth). The
argument is simple: application-level filtering fails open. One forgotten `WHERE`, one
raw SQL report, one `JOIN` that loses the scope, and data crosses a tenant boundary
with no error raised. RLS fails closed: the forgotten filter returns zero rows. For a
property where the cost of a single mistake is a customer-facing breach, the control
belongs in the layer that cannot be bypassed by forgetting.

Cost accepted: the session claim must be set on every connection (middleware plus a
transaction-scoped `SET LOCAL`), connection pooling must not leak a claim between
requests, and background jobs need an explicit elevated path. All three are tested.

### B-7 — One model for all tenants, or one per tenant?

**Chosen**: one shared model, with per-tenant evaluation and tenant-level features.

Most tenants will not have enough churn events to fit their own model; a per-tenant
model for a 500-account tenant with six months of history would be fitted on a handful
of positives and would be worse than the shared model in every respect. The shared
model borrows strength across tenants, which is the entire reason a multi-tenant
product can offer better prediction than each customer could build alone.

The cost is honestly reported: per-tenant metrics are published so a tenant whose
behaviour is atypical is visible rather than averaged away, and a leave-one-tenant-out
evaluation states what a brand-new tenant should expect on day one.

### B-8 — How is the unattended work triggered?

**Chosen**: a long-running worker process with a tick loop, which claims units of work
from a database-backed queue under a time-bounded lease.

Rejected: cron inside the API process (dies with the web server, duplicates on every
replica, no record of a missed run); an external scheduler calling an HTTP endpoint
(moves the reliability problem to something outside the repo and gives an HTTP
timeout authority over whether work completes); a hosted queue broker (a new piece of
infrastructure for a workload measured in thousands of units per cycle — the database
is already durable, already transactional, and already there).

Leases rather than a simple status column, because the failure that matters is a
worker dying mid-unit. A status of `in_progress` with no lease expiry is a unit that
is never retried and never reported — exactly the silent gap that caused the original
complaint.

### B-9 — When does the agent act?

**Chosen**: on *material change*, not on level.

Acting on level re-floods the queue with the same chronically-amber accounts every
cycle, which is how a tool trains its users to ignore it. Material change is defined
as a tier crossing, a probability movement beyond a configured delta, or a change in
the dominant driver — the last being important because an account whose risk stayed at
55% but whose cause switched from slow adoption to unresolved support tickets is a
genuinely new situation.

### B-10 — What is the smallest honest UI?

**Chosen**: three views — the ranked queue, the account evidence trail, and the run
log — plus the draft review surface.

Deliberately excluded from v1: portfolio analytics, cohort charts, trend dashboards,
configurable report builders. None of them help a CSM at 09:00 on Monday, all of them
cost build time, and the brief explicitly prefers a narrow slice built properly. The
run log is included despite being an operator surface rather than a CSM one, because
an autonomous system whose decisions cannot be inspected is one nobody will leave
switched on.

### B-11 — How realistic must the synthetic data be, and what does that mean?

"Realistic" here does not mean plausible-looking values. It means the data must
contain the *structure* the system claims to exploit, and the *pathologies* the system
claims to survive.

**Chosen**: a latent-state simulation. Each account carries an unobserved health
process evolving as a mean-reverting walk with discrete shocks (champion departure,
support failure, competitive evaluation, successful QBR, price increase). All five
sources emit noisy, lagged observations of that latent state, and the churn decision
is drawn from it. Consequences that matter:

- The signals genuinely predict the outcome, because they share a cause with it — not
  because a feature was reverse-engineered from the label.
- Irreducible noise is injected deliberately (budget cuts, acquisitions, champion
  turnover unrelated to health) so that achievable performance is bounded well below
  perfect. A backtest that reports an AUC of 0.99 is evidence of a broken harness, not
  a good model, and the generator is tuned so that cannot happen.
- Pathologies are first-class features of the generator rather than afterthoughts:
  delivery lag with heavy tails, out-of-order arrival, duplicate delivery, a field
  renamed partway through the history, incomplete identity mapping across sources,
  cold-start accounts, a tenant missing an entire source, and weekday/holiday
  seasonality strong enough that a naive week-over-week feature false-positives unless
  it compares aligned windows.

Each pathology exists because a specific requirement claims to handle it. The
generator is, in effect, the adversary for the ingestion and feature layers.

### B-12 — "product.usage_daily" vs. the shipped adapter's "product.usage_rollup"

`contracts/ingestion.md` documents the normalised product event type as
`product.usage_daily`. The already-shipped `ProductAdapter` (Phase 4) in fact
normalises both weekly and daily deliveries to `product.usage_rollup`, and that
is what is actually in the database. The feature registry (`features/registry.py`)
and `compute.py` (Phase 5) follow the real adapter output, not the stale doc
string. Recorded here rather than silently reconciled, because the doc is wrong
and should be corrected in a follow-up pass, not left to be rediscovered.

### B-13 — What "unresolved identity" means at account granularity

`cov_identity_unresolved` (contracts/features.md) is specified as a per-account
boolean, but an `identity_link` row that failed to resolve has, by definition,
`account_id IS NULL` — it cannot know which account it should have belonged to.
**Adopted**: an account counts as identity-unresolved if *zero* `identity_link`
rows resolve to it at all (`features/repository.py::identity_unresolved_for_account`).
This catches an account that exists only because of a billing/CRM row with no
identity mapping ever established for any of its connected sources — the
practical case the abstain rule is trying to protect against — rather than
attempting (impossibly) to attach an orphaned unresolved reference to a
specific account after the fact.

### B-14 — AccountFeatureInput carries only `signup_date`, not the commercial fields

`ingest/dimension.py` warns explicitly against reading current account state
(`segment`, `seats`, `acv_cents`, `renewal_date`) for a point-in-time feature,
because the `account` table holds *today's* values. Phase 5 took that warning
literally: `AccountFeatureInput` (`features/denylist.py`) carries only
`signup_date` — the one commercial fact that is genuinely time-invariant.
Every other commercial attribute (`seats`, `acv_cents`, `segment`,
`renewal_date`) is derived inside `compute.py` from the latest
`crm.account_updated` event with `received_at <= as_of`, the same way every
other feature is. This is a stricter reading than the fork's original
instructions assumed (which would have passed `seats`/`acv_cents` straight
through from the account row) — the stricter reading is correct and is what
shipped.

### B-15 — A known, honestly reported gap: real-world model skill vs. the two retrospective fixtures (SC-006)

The full pipeline was run end to end against the real ingested dataset
(5,000 accounts, ~131k weekly panel rows, 3 tenants). Results:

- ROC-AUC 0.69, PR-AUC 0.106 on the time-based test block — real, validated
  skill (survives label permutation — SC-010 — and clears both the trivial and
  heuristic baselines at the operating point — SC-003), but **below** the
  "low-to-mid 0.8s" ceiling the Phase 3 generator design note anticipated.
- The two planted retrospective fixtures (`northwind-00000`,
  slow_support_decline, churned 2026-07-02; `northwind-00009`,
  champion_collapse, churned 2025-08-21) were **not** flagged at any point in
  their history by this model — max predicted probability 0.047 and 0.021
  respectively, far below `tier_red_at` (0.32 for northwind). **SC-006 and
  SC-005 are not currently satisfied.**
- This was investigated, not just reported: the individual features *do* show
  real signal for `northwind-00000` close to its churn date (`usage_active_users_wow`
  ≈ 0.56, `usage_seat_utilisation` ≈ 0.06 on a 119-seat account — a genuine
  usage collapse), and ticket volume stayed low because the generator's
  "support failure" shocks degrade *response time*, not ticket *volume* — so a
  feature set that weights volume over responsiveness will under-react to
  exactly this fixture's story. Support response-time features
  (`support_median_first_response_h_28d`) were present but did not dominate the
  model's attribution for this account at the checked snapshots.
- **Not fixed in this pass.** Hand-tuning the feature set or the model against
  these two specific accounts would itself be a form of overfitting to the
  fixtures rather than a genuine improvement, and the time budget for this
  session did not allow for principled feature-engineering iteration (e.g.
  interaction terms between response-time degradation and usage collapse,
  or re-weighting the training objective toward the positive class) with
  proper held-out validation that it actually generalises. Recorded as the
  top item for the next iteration, not silently dropped.

### B-16 — Play eligibility by renewal proximity: only `commercial_review` gates on it

T061 asks for eligibility "by dominant driver, value tier, renewal proximity,
confidence." Four of the five plays (`support_recovery`, `adoption_nudge`,
`billing_resolution`, `relationship_rebuild`) have no defensible reason to
withhold outreach based on how far away the renewal is — a customer having a
bad support experience deserves a response whether the renewal is in 10 days
or 300. `commercial_review` ("getting ahead of your renewal") is different:
opening a commercial conversation a year out is premature and not what the
play is for. `Play.max_days_to_renewal` (`agent/plays.py`) is therefore
`None` (no gate) for four plays and `90` for `commercial_review` only — the
mechanism is general (any future play can set this field) but only one play
currently uses it, which is the honest reflection of which plays the brief's
domain actually supports a proximity rule for.

### B-17 — Withheld auto-send is recorded on the Action row, not in `decisions_declined`

`agent_run.decisions_declined` is for accounts the cycle took *no* action on
at all (no eligible play, human-suppressed, inside the per-account cooldown,
an ungrounded draft, a failed send). The ordinary case — a play is drafted
but not auto-sent because the tenant hasn't allowlisted it, or the per-cycle
send cap is already spent — is not a decline in that sense: a draft *was*
produced, a human will see it, nothing was silently skipped. Recording that
reason as `Action.state_reason` (`not_allowlisted_for_auto_send` /
`rate_limit_reached`) rather than duplicating it into every drafted
account's run-level entry keeps `decisions_declined` meaningful (genuinely
unusual withholdings) while still making every withholding of auto-send
individually auditable on the row that explains it (T070).

### B-18 — `work_lease` is managed through `owner_session`, not a fourth DB role

`db/session.py` documented exactly three roles and their purposes (owner /
app / trainer), none of which was "worker infrastructure." Introducing a
fourth role for `work_lease` claiming would mean a new migration and grant
set for a table that, per its own docstring, "is never served to a request"
— the same invariant `owner_session` already carries for migrations and test
fixtures. `owner_session`'s docstring was extended (one line) to cover this
use rather than adding a role whose only justification would be organisational
tidiness, not a real isolation boundary `work_lease` needs (it holds no
tenant data).

### B-19 — Editing a draft does not change its lifecycle state

`Action` has no dedicated "last edited by/at" column, only `decided_by_user_id`
/ `decided_at`. T075 asks for "list, approve, reject, edit; actor and
timestamp recorded." Rather than adding schema for a fourth decision kind,
`PATCH /actions/{id}` records the edit using the same two columns a decision
uses (so every human touch is actor-and-timestamp-auditable) but leaves
`state` at `drafted` — editing is revision, not a decision, and a human must
still explicitly approve or reject afterward. Edits are only permitted while
`state == 'drafted'`; once a decision has been made the row is immutable
history.

### B-20 — Dedicated-tenant integration tests for the agent cycle, not the real `northwind` estate

Early drafts of `test_dispatch_gate.py` and `test_runs_without_llm.py` ran
against the real ingested `northwind` tenant, the same pattern already used
by `test_scoring_service.py`. That pattern broke here specifically: those two
tests assert "at least one account drafts this run," which depends on
`material_change` seeing no previous score (`previous=None` → always
`"first_score"`). Once more than one cycle-level test runs against the same
real tenant in a single test session, a later test inherits `score` rows an
earlier one left behind, and whether its accounts still register as
"materially changed" against a *different* toy model's predictions becomes
execution-order-dependent — found by running the full suite twice and
getting two different outcomes. Fixed by giving every cycle-level test
(`test_dispatch_gate`, `test_suppression_and_rate_limit`,
`test_runs_without_llm`) its own freshly created tenant via the shared
`tests/integration/_agent_fixtures.py` helper, with deterministic ticket
volume driving a deterministic dominant driver — `test_scoring_service.py`'s
northwind-based tests remain fine because they assert generic properties
(tier is one of four values, probability in `[0, 1]`) that don't depend on
run history.

### B-21 — Lead time is not reported, and the report says so (SC-005, FR report)

`GET /model` returns `lead_time_days: {"available": false, "reason": ...}` rather than a
number. Lead time needs the date of each outcome next to the first threshold crossing, and
`PanelRow` carries only `(account, as_of, features, label)`. Deriving it for the whole panel
is real work, and computing it only for the two planted fixtures — which the model does not
flag (B-15) — would produce a flattering-looking nothing. Dropped deliberately; the
alternative rejected was a placeholder figure. Revisit together with the B-15 feature work.

### B-22 — Precision@capacity is tie-aware (a bug found by running the pipeline three times)

Three runs on identical data gave precision@100 of 0.30, 0.30 and 0.24 with identical AUC.
Isotonic calibration produces plateaus of tied scores, and `argsort` broke ties by database
row order, so the headline operating-point metric (and with it the promotion gate) depended
on an arbitrary ordering. `precision_at_capacity` and `captured_acv_at_capacity` now resolve
ties at the cut by expectation (each tied row equally likely to take a remaining slot); the
figure is 0.326 vs 0.021 for the heuristic baseline, identical across reruns. The earlier
0.30/0.32/0.24 figures were noise from tie-breaking and should not be quoted.

### B-23 — Training only reads ingested tenants

`pulse.ml.pipeline` trained on every row of `tenant`, including tenants that integration tests
seed directly, so a promoted model's training data and per-tenant report included `agent-test-*`.
Trainable tenants are now those with an `ingestion_watermark` (i.e. whose data arrived through
the ingestion path). Caveat: some older tests (`test_scoring_service`, `test_queue_endpoint`)
still write toy-model scores into the real `northwind` tenant of a development database, which
makes the queue's "delta since last cycle" misleading *there*. A database built by `run_all.sh`
is clean (verified); the tests should move to throwaway tenants like the Phase 9 ones (B-20).

### B-24 — The unattended loop was not actually runnable; three defects found by validating against the brief

The brief's non-negotiable is that something runs *without a human triggering it*. Validation
found that `worker.serve` (the loop) had no entry point, no test, and was not started by anything:
the only way to run a cycle was a person typing `pulse cycle`. Making it real exposed two more:

1. **One failing tenant killed the worker.** `tick` re-raised, so tenant A's exception stopped
   tenants B, C and D. It now logs and continues.
2. **A failed cycle left no trace.** The cycle is one transaction, so its `running` row rolled
   back with the failure; the run log showed nothing and `due_tenants`'s "a failed run is due
   again" rule had nothing to see. `run_once` now records a `failed` run (with the error) in its own
   transaction.
3. **"Is this tenant due?" compared two clocks.** It tested wall-clock `started_at` against the
   injected clock, so under a simulated clock every tenant was always due (a hot loop). It now
   compares `as_of`, the injected clock's own domain; identical in production.

Fixed test-first (`tests/integration/test_worker_serve.py`, each test watched failing for its stated
reason). `pulse serve` is the entry point; `--simulate-present` runs on the data's present (its
newest event) via `OffsetClock`, because the generated data is dated later than the wall clock.

Known limits, not fixed: a *persistently* failing tenant is retried every tick (30 s) with no
backoff, each attempt leaving a `failed` run row; the whole-tenant cycle is still one transaction
(one bad account fails the tenant's cycle — per-account isolation is the 10× work already listed);
and re-running `pulse cycle` at an unchanged `as_of` is now a no-op (the tenant already ran inside
the interval), which is correct but silent beyond "0/N tenants ran".

### B-25 — The headline numbers were stale, and per-tenant attribution was wrong (found while building leave-one-tenant-out)

1. **Stale figures.** The README, brief, deck and HANDOFF quoted precision@100 **0.33** (0.326) and
   ROC-AUC **0.69**. Re-running the pipeline on the current demo data gives **0.196 and 0.684**, identical
   across two runs hours apart (so it is deterministic now). The model cards show the figure drifting
   0.300 → 0.326 → 0.288 → 0.196 across the day's runs while the test block stayed the same size (13,086);
   the 0.326 predates the clean rebuild of the demo database. I could not reproduce the earlier figure and
   do not claim to know the cause. **The reproducible figure is 0.196 vs 0.021 for the heuristic baseline
   (~9×), ROC-AUC 0.684.** B-22 above quotes 0.326 and is superseded by this entry. All documents corrected.
   Captured value at the operating point is very small (0.009 of at-risk value in the cut).
2. **Per-tenant metrics were attributed to the wrong tenants.** The pipeline paired the time-sorted test
   block with the tenant-ordered slug list, so every model card said `northwind: n=13086` — one tenant
   owning the whole test block. Fixed test-first (`test_panel_tenant_alignment.py`,
   `pipeline.split_with_tenants`). The real split is globex 4,212 / initech 844 / northwind 8,030, with test
   ROC-AUC 0.729 / 0.572 / 0.669. Earlier "per-tenant performance" claims were wrong.
3. **Leave-one-tenant-out (001/FR-018) is now built** (`evaluate.leave_one_tenant_out`; train on the other
   tenants before the test period, score this tenant after it; ~3.4 s). Cold-start AUC / precision@100:
   globex 0.720 / 0.321, initech 0.575 / 0.060 (844 rows), northwind 0.672 / 0.091. **Reading:** a new tenant
   the model has never seen gets weak ranking, and a *small* new tenant gets almost none — the shared-model
   decision (B-7) is defensible for the big tenants and not for a 500-account one. That is a finding, not a pass.

### B-26 — Language-model drafting: what is guaranteed, and what is not (spec 002 US3)

**Guaranteed, by test:** the model sees one JSON document of data (account name, CSM name, derived facts, allowed claims)
and never any ticket, email or CRM free text; its reply is accepted only if every number it contains — digits *or number
words* (`seven`, `twenty-eight`) — appears in the facts, the account name or the CSM name, it contains no link, markup or
instruction-like text, and its claims are within the play; otherwise the template is used and the reason is recorded
(`draft_fallback_reason`, plus `llm_calls / llm_drafted / llm_fallbacks` in the run record). Calls are capped per cycle
(`tenant_config.llm_calls_per_cycle`) and three consecutive provider failures open a breaker. Ranking is byte-identical with the
model off, on and failing. Edits keep the original text (`original_subject/body`).
**Not guaranteed:** that the prose is *good*; that a fact is *relevant*; that a number-word like "one" is checked (it is ordinary prose
and is deliberately exempt); or that a model cannot phrase something misleading using only true facts. Human review remains the control.
**Not done:** a real provider call has never been made (scripted stand-ins only); per-tenant keys (one deployment key); prompt
caching, streaming and retries (`max_retries=0` — a failed call becomes a template, not a delay).

### B-27 — The headline metric is reproducible only for a fixed row order, and is noisy even then (found by rebuilding)

Rebuilding the demo database on **identical data** (347,740 events, byte-identical feeds) gave precision@100 of 0.196, then 0.252;
earlier builds gave 0.30, 0.326 and 0.288. Cause: the panel was built from `SELECT id FROM account` with no `ORDER BY`, so row
order followed Postgres's physical layout (which changes on update and rebuild), and the model followed row order. Measured on one
database with only the account order changed: **precision@100 0.217 / 0.289 / 0.333, ROC-AUC 0.676 / 0.690 / 0.682**, heuristic
baseline 0.021–0.023. (Part of the sensitivity is structural: gradient boosting's early-stopping validation split is drawn by row index.)
**Fix:** accounts are ordered by their stable external reference (`panel_account_ids`, test-first), so a given dataset now yields one
reproducible result. **What may be claimed:** precision@100 is roughly **0.22–0.33 against ~0.02 for the heuristic (about 10–15×)** and
ROC-AUC **0.68–0.69**; any single figure is a draw from that range. Earlier documents quoting "0.33", "0.326" or "0.196" as *the* result
overstated its precision. B-22 and B-25 above are superseded by this entry for the figure itself.

### B-28 — Authentication: what was chosen, what was rejected, what is open (spec 002 US1)

**Chosen.** Email + password per tenant user; the login names a *workspace* (tenant slug), because the same email can exist in two
tenants and an email-only login would need an ambiguous merge. Passwords: stdlib scrypt, per-user salt, parameters stored with the hash.
Sessions are **opaque and server-side** (`<tenant_id>.<secret>`; only `sha256(secret)` is stored), sent as an `HttpOnly; SameSite=Strict`
cookie (or a bearer token for API clients), with an `X-Requested-With` check on cookie-authenticated writes. The tenant id in the token is
*untrusted*: it only selects the claim under which the lookup runs, and row-level security then hides every row that is not that tenant's, so a
forged prefix finds nothing — no `SECURITY DEFINER` function, no cross-tenant read on the request path (constitution IV). A disabled user or a
changed role takes effect on the next request. Failures return one identical 401 and cost the same time. Rate limiting is shared across
instances (Postgres, hashed keys).
**Rejected.** JWT (not revocable without a store, tempts putting the role in the token); SSO/OIDC and MFA (out of scope; a real tenant will ask for SSO);
email-driven password reset (operators reset; self-service reset needs the mail path to be trusted first); per-process limiting.
**Open / not done.** Every demo user shares one generated password; no password-breach check beyond a short deny-list; no session listing or
"sign out everywhere" for a user; no account lockout notification; `Secure` cookies are off by default (set `PULSE_COOKIE_SECURE` behind HTTPS).
The application roles' passwords are fixed in migration 0002 (development defaults).

### B-29 — Email: what "real delivery" means here, and its limits (spec 002 US2)

**Chosen.** One code path (`agent/delivery.py`) for a human approval *and* the unattended cycle. A pure send gate: outbound switched on, a **verified**
sender, a provider, a known contact, no opt-out — each failure its own state, zero network traffic. **Demo mode is the default**: mail goes only to a
test inbox, or is captured without delivery. Approve is one atomic conditional UPDATE, so two simultaneous approvals send once. Outcomes are classified
**transient / permanent / ambiguous**; only transient is retried (≤3). An *ambiguous* outcome (the body was sent and no answer came back) becomes
`send_unconfirmed`, is **never** retried, and tells a human to check the provider — exactly-once is not achievable over a provider-neutral mail protocol,
so the guarantee is "never knowingly send twice". Changing the sender address revokes verification and switches sending off.
**Limits, stated.** No real email has been sent by this system (an in-process fake SMTP server stands in). Bounces, complaints and replies are not processed,
so a hard bounce is unknown to us and an opt-out sent by *reply* must be entered by an operator. SMTP credentials are deployment-level (environment), not
per tenant. The customer contact comes from the CRM feed only; there is no contact import and no contact deduplication.

**B-27 addendum — verified across a full rebuild.** With the fix, dropping *both* databases and rebuilding from nothing gave precision@100 **0.289**,
ROC-AUC **0.690**, PR-AUC 0.100, Brier 0.0348, heuristic baseline 0.023 (about 12×) — identical to the canonical-order figure measured on the previous build.
Per-tenant test ROC-AUC: globex 0.745, initech 0.546, northwind 0.678. Cold start (leave-one-tenant-out) ROC-AUC / precision@100: globex 0.706 / 0.315,
northwind 0.672 / 0.090, **initech 0.528 / 0.044** — a small new tenant gets almost no benefit from a model trained on the others. Captured value at the
operating point is 4.6% of value at risk. These supersede the cold-start figures in B-25 (which came from a differently-ordered build).

