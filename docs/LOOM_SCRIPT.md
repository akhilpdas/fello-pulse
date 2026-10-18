# Walkthrough guide — what to show, where to click, what to say

A Loom is a screen recording with your voice over it. You open the app, click through it and talk. Nothing to type, nothing
interactive for the viewer. This guide is the order to do it in. **Say it in your own words** — the quoted lines are prompts, not a
script to read out.

**Length.** Three parts, each about 4–5 minutes, so each fits Loom's free-plan limit (I believe 5 minutes a video; check yours).
Record them as three videos and put three links in the email, or as one if your plan allows ~13 minutes.

| Part | Covers | Sign in as |
|---|---|---|
| **A. The product** (~5 min) | Queue, browse, week picker, account page, evidence, what moved, low confidence | Northwind **operator** |
| **B. The CSM's day and the boundary** (~4.5 min) | Judgement buttons, drafts, approve, what the language model may and may not do, a second login | Northwind **operator**, then **csm01** |
| **C. Operating it and being honest** (~4 min) | Admin, run log, audit, model quality, how it is built and hosted | Northwind **operator** |

## Before you record (5 minutes)

- Open the hosted site (the link in your email draft) **a few minutes early** so it is awake; sign in once to check.
- The password is in `.submission-attachments/Pulse_demo_credentials.txt`. Type it with the recording **paused**, or sign in before you press record and sign out/in only when the script says. Never leave it on screen.
- Close other tabs, mute notifications, zoom the browser to 110–125% so the table is readable.
- Keep this file on a second screen or phone.
- **The hosted demo is shared state.** Approve, suppress and "confirm" clicks stay for the next reviewer. Do the clicking steps on a **non-top** account (rank 5–15 in the queue), not the top one.
- Optional: have a terminal window open at the repo root for the 20-second "run it locally" shot in Part C.

## The logins (show this once, early in Part A)

The sign-in has three boxes: **Workspace** (the customer organisation), **Email**, **Password**. One shared password for every demo user.

| Workspace | Operator (sees everything, has **Admin**) | CSM (sees only their own accounts, no Admin) |
|---|---|---|
| `northwind` — 2,800 accounts | `csm00@northwind.example.com` | `csm01@northwind.example.com` |
| `globex` — 1,700 | `csm00@globex.example.com` | `csm01@globex.example.com` |
| `initech` — 500 | `csm00@initech.example.com` | `csm01@initech.example.com` |

Say: "Three simulated customer companies — tenants — about 5,000 accounts and 350,000 events from five sources. One person at one
company can never see another company's data; that is enforced in the database, not just the app."

---

## PART A — The product (about 5 min)

**0:00 Frame it (30 s).** On the sign-in page, before you sign in.
"The request was a churn dashboard and an auto-email. What the data shows is a *lead-time* problem: by the time a customer looks
unhealthy, there is no time left to act. So Pulse does three things every cycle without being asked: it **ranks** which accounts a
CSM should act on this week, it **explains** why down to the source records, and it **drafts** a first message. A human sends it."
Point at the three boxes, then say the logins line above. Sign in as `csm00@northwind.example.com`.

**0:30 The queue (75 s).** You land on **Queue** ("This week's queue").
- Top bar: the nav — **Queue, Low confidence, Drafts, Run log, Admin** — and, on the right, your name, role and workspace.
- Columns, left to right: `#` rank, **Account**, **Tier** (red/amber/green), **Risk** (probability of churn or shrinking within 90 days), **Value at risk**, **Renewal** (days), **Why** (dominant driver), **Since last cycle**.
- Say: "The list is deliberately short. It is capped to the team's weekly capacity — a CSM can only act on so many — and it says 'N more below the cut'. A ranked list of 2,800 would be a dashboard nobody reads."
- Point at the small grey reference under a name: "Names repeat inside a tenant, so every account shows its CRM reference."
- The **Since last cycle** column: "new", "up", "down" — what changed since the last scoring run.

**1:45 Week picker and Browse all (60 s).**
- Open the **Week** dropdown above the table, choose an earlier week. "Nine weekly snapshots of history. The queue is reproducible for any past week."
- Click **Browse all accounts →** under the table. "The weekly queue is the head of the ranking. This is the whole ranking." Type part of a name in **Search accounts**; set **Tier** to red; set **Driver** to one value; use **Next**. Rank numbers carry on past the cut, and rows that are in this week's queue are in bold.

**2:45 One account, fully explained (110 s).** Go back to Queue, click the **top account**.
- **What is driving it** — the driver bars: six business drivers (for example engagement, support, commercial) that push the score up or down. "These are summed from per-feature SHAP attributions from the model."
- **Evidence** — open a driver. It lists the source records behind it (support ticket, usage event, invoice). Open one to show the original payload. Say: "Every number on this page resolves to a record. Nothing is a black box."
- **What moved** — choose an earlier date in **Compare against the score as of**, click **Compare**. The table shows each feature: from, to, contribution change. "This answers 'why is it on my list *this week*'."
- **Feature values** — raw inputs, for anyone who wants to check the model's working.

**4:15 Saying "I don't know" (35 s).** Click **Low confidence** in the nav.
"Some accounts the system refuses to score confidently — too little history, missing data. They get a reason and a remedy, in the **What to do** column, and are never shown as green. A silent green for an account we know nothing about is the dangerous error."

**4:50 Wrap Part A (10 s).** "Next: what a CSM does with it, and what the language model is and is not allowed to do."

---

## PART B — The CSM's day and the boundary (about 4.5 min)

**0:00 Your judgement (45 s).** Open a **non-top** account from the queue (rank 5–15). Find the **Your judgement** box.
- **Confirm risk is real** / **Mark false positive** — optional note field; stored as a label, "retained as a label for the model, not just hidden".
- **Suppress from queue** — a reason is required (the button stays disabled until you type one), pick 7, 14, 30 or 90 days. It leaves the queue but is still scored. **Lift suppression** undoes it.
- Click one (for example **Mark false positive** with a note) so the viewer sees the confirmation line. Say: "On the shared demo this stays; on your own copy it is yours."

**0:45 Drafts (120 s).** Click **Drafts** ("Draft review").
- Each card shows the play and its state, an editable **Subject** and **Body**, and beside them **Grounded in** (the drivers the message relies on). Under that it says **Drafted by llm** or **Drafted by template**, with a link **See the evidence**.
- Say what the model may and may not do — this is the key trust point:
  1. "Ranking and scoring is a gradient-boosted tree model — **not** a language model. A language model never ranks, scores, tiers or filters anything. The ranking code cannot even import it."
  2. "The language model only **writes the prose**, from a short list of facts the system already derived. It never sees raw ticket or email text."
  3. "Its reply is **rejected** — and a deterministic template used instead — if it contains any number, link or claim that is not traceable to those facts. Calls are capped per cycle, and a failing provider trips a circuit breaker."
  4. "In the real run on a free Groq model, `qwen/qwen3.8-27b`: 91 drafts were written by the model and 15 by template; 3 of 106 were rejected by the guardrail, 12 hit the per-cycle cap. With no key at all, the same cycle writes all 106 as templates — the system works either way. Switching to Anthropic is three settings; I have not run that."
- Use the **Show** dropdown: `drafted`, `sent`, `rejected`, `opted_out`, `outbound_disabled`… "Every state has an explicit name, so you can see why a message did *not* go out."

**2:45 Edit and approve (60 s).** On a non-top draft: change a word in **Body**, click **Save edit** (the edit is stored), then **Approve & send**.
- On the hosted demo outbound is off, so the notice reads **"Not sent: outbound email is switched off for this workspace."** (with outbound on in demo mode it reads "captured but not delivered — no customer was emailed"). "Outbound is off by default. Real sending needs a verified sender address *and* demo mode switched off. Nothing here can reach a real person: all addresses are `@example.com`."
- **Reject** is the other button.

**3:45 A different login: the CSM (45 s).** Click **Sign out**. Sign in as `csm01@northwind.example.com`.
- The queue is much smaller — only their own accounts.
- The nav has **no Admin** link.
- Say: "Hiding the link is courtesy. The server refuses the admin API for this user even if you type the URL." (Optional proof: add `/admin` to the address; it shows no access.)
- Sign out. Back to `csm00@northwind.example.com` for Part C.

Optional (20 s): sign in to workspace `initech` as `csm00@initech.example.com` — a small tenant of 500 accounts. "Same product, a different customer's data, and none of Northwind's is visible."

---

## PART C — Operating it, and being honest (about 4 min)

**0:00 Admin (75 s).** Operator only. Click **Admin**.
- **Outbound email** — "Off until a sender is *verified*." Fields: **Sender address** → **Set sender** → **Verify sender**; **Test inbox**; **Demo mode** toggle ("ON — nothing reaches customers"). "Four independent gates before any real email can go out." *Do not change these on the hosted demo — just point.*
- **Opt-outs** — add an email; that contact is never emailed.
- **Users** — email, name, role (`csm` / `operator`), password, **Create user**. "Roles are enforced server-side."
- **Audit trail** — When, Event, By, Subject. "Who approved what, who changed a setting. Append-only."

**1:15 Run log (60 s).** Click **Run log** ("What each autonomous cycle did — and what it chose not to do, and why").
- Each cycle: time, status, trigger, duration, and stage counts (accounts scored, drafts made…).
- Open **declined decisions**. "The agent records what it chose *not* to do, with a reason — for example `no_eligible_play`. Read out one or two entries you actually see on screen. A system that acts on its own must be able to explain its restraint."
- "There is also an unattended worker that cycles each tenant on a schedule. On Render's free tier there is no background worker, so the hosted demo shows the cycles that already ran; locally the worker runs on its own."

**2:15 Model quality, said plainly (75 s).** The hosted demo has no promoted model (`/api/model` answers "no promoted model" because the hosted copy never trains), so don't open it: show the README "Results" section on GitHub or the deck slide, or just say the numbers.
- "On a rolling backtest, ROC-AUC averages **0.661**. An oracle that is handed every account's hidden health gets **0.673**. So about 0.7 is the ceiling on this data — we are close to it."
- "Lead time: at the amber line it flags **32%** of the losses, a median **72 days** ahead. The rest were not foreseeable from these signals."
- "A small new tenant gets almost nothing from the shared model — I say so rather than hide it. The two planted 'lost renewal' accounts are *not* flagged out of sample, and I wrote down why instead of tuning to hit them (clarification B-33)."

**3:30 How it is built and hosted (30 s).**
- "FastAPI, Postgres with row-level security, React, and an agent worker. Tenant isolation lives in Postgres, and I mutation-tested it."
- "Hosted on Render's free tier with a free Postgres that lasts about 30 days. Locally it is `docker compose up` plus one command that loads a pre-built seed in about 15 seconds."
- Optional terminal shot (15 s): show `docker compose up -d --build db api web` and the `load-seed` command from the README.

**4:00 Close.** "Known gaps, written down rather than hidden: no hosted worker on the free tier; an Anthropic API run and a real mail provider were never exercised; the hosted DB expires. The next thing that breaks at 10× is the cycle, not the queue."

---

## If something goes wrong while recording

- **Page is slow or blank** — the free tier may be waking up (up to a minute). Wait, reload, and re-take. Nobody minds a cut.
- **Signed out unexpectedly** — sessions expire; sign in again off-camera.
- **You clicked the wrong thing** — carry on. Loom lets you trim the start and end afterwards.
- **You went over 5 minutes** — stop at the end of the Part you are in and start the next Part as a new recording.
