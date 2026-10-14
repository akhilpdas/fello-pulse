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
