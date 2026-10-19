# Walkthrough script (~6 minutes)

**0:00 — Framing (30s).** "The request was a dashboard and an auto-email. The evidence was a lead-time problem.
So this ranks, explains, and drafts — and a human sends."

**0:30 — Running it (45s).** Say there are two ways in and show both briefly.
(1) *Hosted:* the link in the submission email, open in the browser. It is a free-tier service that sleeps when idle, so the first load can take about a minute — **open it a few minutes before recording** so it is awake.
(2) *Local:* Terminal: `docker compose up -d --build db api web`, then `docker compose run --rm api python3 -m pulse.cli load-seed --url https://github.com/akhilpdas/fello-pulse/releases/download/seed-v1/seed.dump` — it finishes in about 15 seconds and prints the sign-in.
Say: the first dry run measured the old path at 7 min 37 s to build plus 10 to 46 minutes for the history, so a reviewer now gets a pre-built, checksummed seed (the from-scratch build still works and is documented).

**1:00 — Monday queue (75s).** UI → sign in as the Northwind operator → Queue. Point at: bounded list, "why" column, value at risk, renewal distance, delta since last cycle, the small grey CRM reference
under each name (names repeat inside a tenant), "N more below the cut". Open the **Week** picker and move to an earlier week; click **Browse all accounts →**, search a name, filter by tier.
Then sign in as csm01 to show they see only their own accounts.

**2:00 — Trust it (75s).** Click the top account. Driver bars → expand Evidence → open a Zendesk payload.
Use *What moved*: compare against an earlier date. "Every number resolves to a source record."

**3:15 — Saying "I don't know" (30s).** Low confidence tab: reason + remedy; "never green".

**3:45 — The boundary (105s).** Drafts tab: a draft beside its grounding, labelled **"Drafted by llm"** — these 91 drafts were written by a free Groq model (`qwen/qwen3.8-27b`) in one real cycle; 15 are templates.
Say what the model may and may not do: it only writes the prose from facts the system derived; it never ranks or scores; its reply is rejected, and a template used instead, if it contains any number or claim not traceable to the facts (3 of 106 were rejected that way, 12 hit the per-cycle call cap). Unset the key and the same cycle writes all 106 as templates; switching to Anthropic is three settings (not run).
Edit a draft and approve it. On the hosted demo outbound email is off, so the notice reads "Not sent: outbound email is switched off for this workspace" (with outbound on in demo mode it reads "captured but not delivered — no customer was emailed"). **On the hosted demo, do this on one non-top account — what you click stays for the next reviewer.**
Admin (operator only; a CSM has no Admin link and the API refuses them): outbound is off until a sender is *verified*, demo mode is the default, opt-outs. Run log: stage counts and the *declined decisions with reasons*. Audit trail shows who did what.
Say plainly what was and was not run for real: email over real SMTP into a local inbox (Mailpit), including an unattended send — no real provider; drafting against a free local model (Ollama) and against Groq's free tier — the Anthropic API has not been run.

**5:00 — Honesty (60s).** The hosted demo has no promoted model (`/api/model` answers "no promoted model", because the hosted copy never trains), so do not open it: show the README "Results" section or the deck slide, or just say the numbers. On a rolling backtest ROC-AUC averages 0.661, and an oracle that is handed every account's hidden health gets 0.673 — so about 0.7 is the ceiling on this data.
Lead time: at the amber line it flags 32% of losses, a median 72 days ahead (oracle 33%); the rest were not foreseeable. A small new tenant gets almost nothing from the shared model. The two planted
lost-renewal accounts are not flagged out of sample — and say why: one is forced to churn by a rule no health signal shows, the other churned a year before its planted collapse. Written down (B-33), not tuned to the demo.

**6:00 — Close.** Hosted on Render's free tier with Postgres; the hosted database is a free one that lasts about 30 days. Isolation is in Postgres, mutation-tested; the cycle is what breaks first at 10×.
