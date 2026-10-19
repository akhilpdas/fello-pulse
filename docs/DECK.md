# Pulse — short deck (one slide per ##)

## 1. The problem
120 accounts per CSM, attention by guesswork. Two renewals lost; the signals were in Zendesk and usage all along.

## 2. What the request asked for — and why we changed it
Health-score dashboard + auto-email red accounts → ranked, bounded, evidence-backed queue + reviewed drafts. (D1–D6)

## 3. The Monday queue
Tier, risk, value at risk, renewal distance, main driver, delta since last cycle, and the below-the-cut count. Week picker for earlier weeks; All accounts pages through the whole ranking, with search and tier/driver filters.

## 4. Every number has a trail
Drivers → evidence ids → original source payload. Score diff: what moved, by how much.

## 5. It works while nobody is watching
Ingest → score → detect change → draft → record. Run log shows what it did and what it declined, and why.

## 6. Bounded autonomy
Drafts by default. Auto-send: per tenant, per play, opt-in, suppression + rate limit. Real email only through a verified sender, never to an opted-out or contact-less account, and in demo mode (the default) never to a real customer. An ambiguous send is never retried.

## 7. Five guarantees, each a test
Point-in-time · model ranks/LLM writes (only from derived facts; output rejected if a number or claim is untraceable) · reviewed boundary · tenant isolation (RLS, mutation-verified; tenant from a verified session, never a header) · explained outputs.

## 8. Does the model earn its place?
Rolling backtest (4 folds, last 52 weeks, each fold scored by a model that saw only what was known then): ROC-AUC 0.661, against 0.673 for an oracle that knows every account's hidden health — on this data 0.7 is close to the ceiling. Lead time over all 390 losses: at the amber line (≥10% risk, 4.6% of account-weeks) 32% flagged, median 72 days ahead; oracle 33%. Precision@100 about 0.5 vs 0.02 for the heuristic on the latest block (one draw). Promotion is gated on beating the baseline at the operating point.

## 9. Try it in minutes
Two ways in. Hosted: a free Render service with a free Postgres (link and sign-in are in the submission email); it sleeps when idle, so the first load can take about a minute (measured: 48 s), and its database lasts about 30 days. Local: docker compose up plus load-seed loads a checksummed 51 MB seed in 15 s, history included. The old path measured 7 min 37 s to build plus 10 to 46 minutes of backfill. Verified: backend 602 tests, frontend 49, 13 of 13 browser scenarios in real Chrome; the hosted site was checked in a browser after deploy.

## 10. What we are honest about
The two planted lost-renewal accounts are not flagged out of sample, and they are poor tests (one is forced to churn by a rule no health signal shows; the other churned a year before its planted collapse) — so lead time is measured over every loss instead (B-33). About 70% of losses are not foreseeable from these signals. A new small tenant gets almost nothing from the shared model (cold-start AUC 0.46). Drafts: 91 of the 106 in the demo were written by a free Groq model (qwen/qwen3.8-27b) in one real cycle, labelled "Drafted by llm"; 15 are templates; the guardrail rejected 3 model replies. The hosted demo shows those saved results — no background worker runs on the free tier. Email was verified over real SMTP against a local mail server, including an unattended send, but no real mail provider has been used; the Anthropic API has not been run. Earlier-week scores are in-sample, for browsing only.

## 11. 10× and what's next
Cycle is first to break (batched loading, more workers). Next: uplift once intervention history exists. More features would not help here — the existing ones already reconstruct the hidden health (R² 0.78) and adding the true health gained nothing.
