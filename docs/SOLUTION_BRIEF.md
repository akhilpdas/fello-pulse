# Pulse — solution brief

**Problem.** A CSM owns ~120 accounts and spends attention by guesswork. Two renewals were
lost with no warning although the signals sat in Zendesk and usage data. That is a
detection-and-lead-time failure, not a reporting failure.

**What we built.** Every cycle, unprompted: ingest five sources → score each account's
probability of churn or ≥25% contraction within 90 days → rank by
`probability × value at risk × renewal urgency` → bound to the CSM's weekly capacity →
draft the first move. The CSM signs in and opens a short, ordered list of *their own* accounts with the reason,
the delta since last week, and the evidence down to the source payload. Operators also manage users, the sender and
opt-outs, and see an audit trail.

**Where we disagreed with the request, and why.**
- *One health score* → a dated, checkable probability split into six drivers; 0–100 is cosmetic.
- *Auto-email red accounts* → draft, don't send. Red often means we failed the customer, and a
  cheerful template to someone with a nine-day-old P1 is harmful. Auto-send exists only per tenant,
  per play, opt-in, under suppression and rate limits — and even then only through a verified sender, never to an
  opted-out or contact-less account, and in **demo mode (the default) never to a real customer**.
- *A colour for everyone* → an honest low-confidence bucket with a reason and a remedy.
- *"Nothing slips"* → not promised; we report what is caught and the residual.

**Guarantees, each proven by a test.** No future data in any feature · a model ranks, an LLM only
writes, only from derived facts, and its output is rejected if any number or claim does not trace to them
(system runs identically with it off) · autonomy bounded and every refusal recorded · tenant isolation
enforced in Postgres, mutation-tested, with the tenant taken from a verified session, never a header ·
every number traces to evidence.

**Results (seed-reproducible).** Rolling-backtest ROC-AUC **0.661** (an oracle holding each account's hidden health: 0.673 — the data's ceiling is near 0.7); lead time over all 390 losses: **32%** flagged at the amber
line, a median **72 days** ahead; precision@100 about 0.5 vs 0.02 for the heuristic (latest block, one draw); a full cycle over ~4,500 accounts in ~105 s against a 15-minute interval.

**What is not done.** The two planted "lost renewal" accounts are still *not* flagged out of sample (both are flawed fixtures, B-33), so lead time is measured over every loss instead; about 70% of losses are
not foreseeable from these signals. Email was verified over real SMTP against a local mail server and drafting ran against a free local model, but **no real mail provider and no Anthropic API call has been used**; the containers were built and run on one machine only (arm64, Colima); no SSO/MFA;
no uplift modelling; the Loom is a script, not a recording.

**First thing to break at 10×.** The cycle (per-account event loading, ~19 min at 50k vs a 15-min
interval); fix is batched loading plus more lease-holding workers.
