# Walkthrough script (~6 minutes)

**0:00 — Framing (30s).** "The request was a dashboard and an auto-email. The evidence was a lead-time problem.
So this ranks, explains, and drafts — and a human sends."

**0:30 — One command (30s).** Terminal: `bash infra/scripts/run_all.sh` (show the end: ready, tenant/operator ids).
Say it went from an empty database to scored, and that it is idempotent.

**1:00 — Monday queue (60s).** UI → paste tenant + operator id → Queue. Point at: bounded list, "why" column,
value at risk, renewal distance, delta since last cycle, "N more below the cut".

**2:00 — Trust it (75s).** Click the top account. Driver bars → expand Evidence → open a Zendesk payload.
Use *What moved*: compare against an earlier date. "Every number resolves to a source record."

**3:15 — Saying "I don't know" (30s).** Low confidence tab: reason + remedy; "never green".

**3:45 — The boundary (75s).** Drafts tab: draft beside its grounding; edit, approve. Admin: auto-send is off per play
by default. Run log tab: stage counts and the *declined decisions with reasons*.

**5:00 — Honesty (60s).** `GET /model`: precision@100 0.33 vs 0.02. Then say plainly: AUC is 0.69 and the two planted
lost-renewal accounts are not flagged, so I don't claim lead time. Diagnosed, written down (B-15), not tuned to the demo.

**6:00 — Close.** Isolation is in Postgres, mutation-tested; the cycle is what breaks first at 10×.
