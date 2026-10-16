# Pulse — solution brief

**Problem.** A CSM owns ~120 accounts and spends attention by guesswork. Two renewals were
lost with no warning although the signals sat in Zendesk and usage data. That is a
detection-and-lead-time failure, not a reporting failure.

**What we built.** Every cycle, unprompted: ingest five sources → score each account's
probability of churn or ≥25% contraction within 90 days → rank by
`probability × value at risk × renewal urgency` → bound to the CSM's weekly capacity →
draft the first move. The CSM opens a short, ordered list with the reason, the delta since
last week, and the evidence down to the source payload.

**Where we disagreed with the request, and why.**
- *One health score* → a dated, checkable probability split into six drivers; 0–100 is cosmetic.
- *Auto-email red accounts* → draft, don't send. Red often means we failed the customer, and a
  cheerful template to someone with a nine-day-old P1 is harmful. Auto-send exists only per tenant,
  per play, opt-in, under suppression and rate limits.
- *A colour for everyone* → an honest low-confidence bucket with a reason and a remedy.
- *"Nothing slips"* → not promised; we report what is caught and the residual.

**Guarantees, each proven by a test.** No future data in any feature · a model ranks, an LLM only
writes (system runs with it off) · autonomy bounded and every refusal recorded · tenant isolation
enforced in Postgres, mutation-tested · every number traces to evidence.

**Results (seed-reproducible).** Precision@100 **0.20** vs 0.02 for the heuristic baseline;
ROC-AUC **0.68**; a full cycle over ~4,500 accounts in ~105 s against a 15-minute interval.

**What is not done.** The two planted "lost renewal" accounts are *not* flagged by the model, so we
cannot yet claim lead time; the shortfall is diagnosed (response-time vs ticket-volume attribution) and
documented, not hidden. No real email/LLM integration, no authentication layer, no uplift modelling.

**First thing to break at 10×.** The cycle (per-account event loading, ~19 min at 50k vs a 15-min
interval); fix is batched loading plus more lease-holding workers.
