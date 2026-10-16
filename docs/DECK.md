# Pulse — short deck (one slide per `##`)

## 1. The problem
120 accounts per CSM, attention by guesswork. Two renewals lost; the signals were in Zendesk and usage all along.

## 2. What the request asked for — and why we changed it
Health-score dashboard + auto-email red accounts → ranked, bounded, evidence-backed queue + reviewed drafts. (D1–D6)

## 3. The Monday queue
Tier, risk, value at risk, renewal distance, main driver, delta since last cycle, and the below-the-cut count.

## 4. Every number has a trail
Drivers → evidence ids → original source payload. Score diff: what moved, by how much.

## 5. It works while nobody is watching
Ingest → score → detect change → draft → record. Run log shows what it did *and what it declined, and why*.

## 6. Bounded autonomy
Drafts by default. Auto-send: per tenant, per play, opt-in, suppression + rate limit. Real email only through a verified sender, never to an opted-out or contact-less account, and in demo mode (the default) never to a real customer. An ambiguous send is never retried.

## 7. Five guarantees, each a test
Point-in-time · model ranks/LLM writes (only from derived facts; output rejected if a number or claim is untraceable) · reviewed boundary · tenant isolation (RLS, mutation-verified; tenant from a verified session, never a header) · explained outputs.

## 8. Does the model earn its place?
Precision@100 0.29 vs 0.02 baseline (~12×; range 0.22–0.33 by row order); AUC 0.69; promotion is gated on beating the baseline at the operating point.

## 9. What we are honest about
Two planted lost-renewal accounts not flagged → lead time not claimed (B-15). A new small tenant gets almost nothing from the shared model (cold-start AUC 0.53). No real email sent and no real model call made — built and tested against stand-ins; containers built and run on arm64 only (browser suite passes against them).

## 10. 10× and what's next
Cycle is first to break (batched loading, more workers). Next: response-time feature work with held-out validation, uplift once intervention history exists.
