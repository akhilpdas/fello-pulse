# Walkthrough script (~6 minutes)

**0:00 — Framing (30s).** "The request was a dashboard and an auto-email. The evidence was a lead-time problem.
So this ranks, explains, and drafts — and a human sends."

**0:30 — One command (30s).** Terminal: `bash infra/scripts/run_all.sh` (show the end: the sign-in details).
Say it went from an empty database to scored, and that it is idempotent.

**1:00 — Monday queue (75s).** UI → sign in as the Northwind operator → Queue. Point at: bounded list, "why" column, value at risk, renewal distance, delta since last cycle, the small grey CRM reference
under each name (names repeat inside a tenant), "N more below the cut". Open the **Week** picker and move to an earlier week; click **Browse all accounts →**, search a name, filter by tier.
Then sign in as csm01 to show they see only their own accounts.

**2:00 — Trust it (75s).** Click the top account. Driver bars → expand Evidence → open a Zendesk payload.
Use *What moved*: compare against an earlier date. "Every number resolves to a source record."

**3:15 — Saying "I don't know" (30s).** Low confidence tab: reason + remedy; "never green".

**3:45 — The boundary (90s).** Drafts tab: draft beside its grounding; edit, approve → "Demo mode: captured, no customer was emailed".
Admin (operator only; a CSM has no Admin link and the API refuses them): outbound is off until a sender is *verified*,
demo mode is the default, opt-outs. Run log: stage counts and the *declined decisions with reasons*. Audit trail shows who did what.
Say plainly what was and was not run for real: email over real SMTP into a local inbox (Mailpit), including an unattended send — no real provider; drafting against a free local model (Ollama) — the Anthropic API has not been run.

**5:00 — Honesty (60s).** Admin → model report or `GET /model`: on a rolling backtest ROC-AUC averages 0.661, and an oracle that is handed every account's hidden health gets 0.673 — so about 0.7 is the ceiling on this data.
Lead time: at the amber line it flags 32% of losses, a median 72 days ahead (oracle 33%); the rest were not foreseeable. A small new tenant gets almost nothing from the shared model. The two planted
lost-renewal accounts are not flagged out of sample — and say why: one is forced to churn by a rule no health signal shows, the other churned a year before its planted collapse. Written down (B-33), not tuned to the demo.

**6:00 — Close.** Isolation is in Postgres, mutation-tested; the cycle is what breaks first at 10×.
