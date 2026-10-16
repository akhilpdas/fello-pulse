# Walkthrough script (~6 minutes)

**0:00 — Framing (30s).** "The request was a dashboard and an auto-email. The evidence was a lead-time problem.
So this ranks, explains, and drafts — and a human sends."

**0:30 — One command (30s).** Terminal: `bash infra/scripts/run_all.sh` (show the end: the sign-in details).
Say it went from an empty database to scored, and that it is idempotent.

**1:00 — Monday queue (60s).** UI → sign in as the Northwind operator → Queue (then sign in as csm01 to show they see only their own accounts). Point at: bounded list, "why" column,
value at risk, renewal distance, delta since last cycle, "N more below the cut".

**2:00 — Trust it (75s).** Click the top account. Driver bars → expand Evidence → open a Zendesk payload.
Use *What moved*: compare against an earlier date. "Every number resolves to a source record."

**3:15 — Saying "I don't know" (30s).** Low confidence tab: reason + remedy; "never green".

**3:45 — The boundary (90s).** Drafts tab: draft beside its grounding; edit, approve → "Demo mode: captured, no customer was emailed".
Admin (operator only; a CSM has no Admin link and the API refuses them): outbound is off until a sender is *verified*,
demo mode is the default, opt-outs. Run log: stage counts and the *declined decisions with reasons*. Audit trail shows who did what.
Say plainly: the email path and the model drafter are tested against stand-ins — no real email or model call has been made.

**5:00 — Honesty (60s).** Admin → model report or `GET /model`: precision@100 about 0.29 vs 0.02 — and say it is one draw from
0.22–0.33 (it moves with row order, B-27). AUC is 0.69, a small new tenant gets almost nothing from the shared model, and the two
planted lost-renewal accounts are not flagged, so I don't claim lead time. Diagnosed, written down (B-15), not tuned to the demo.

**6:00 — Close.** Isolation is in Postgres, mutation-tested; the cycle is what breaks first at 10×.
