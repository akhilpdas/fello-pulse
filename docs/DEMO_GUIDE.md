# Pulse — demo guide

How to start it, how to sign in, what to show, what is real and what is not. Written for someone presenting or reviewing this
for the first time. (`README.md` is the engineering summary; `HANDOFF.md` is the project log.)

## What you are looking at

A system that, every cycle and without anyone asking, scores each customer account's risk of churning or shrinking within 90
days, ranks the accounts a CSM should act on this week, shows **why** (down to the source records), drafts a first message, and
lets a human approve it. Three simulated customer organisations (tenants), ~5,000 accounts, ~350,000 events from five sources.

## Start it (pick one)

**A. VS Code tasks** — `Terminal ▸ Run Task…`, in order:

1. `Pulse: 1. start Postgres`
2. `Pulse: 2. build demo data (~4 min; safe to re-run)` — only the first time, or after a reset
3. `Pulse: 3. run the demo (API + UI)` → open **http://localhost:5173**
4. optional: `Pulse: 4. unattended worker` — the agent that cycles each tenant on its own (watch **Run log** gain rows)

**B. Terminal**

```bash
bash infra/scripts/run_all.sh                                   # empty database -> scored system; prints the sign-in at the end
cd backend && source .venv/bin/activate && export PGTZ=UTC
uvicorn pulse.api.main:app --port 8000                          # terminal 1
cd frontend && npm install && npm run dev                       # terminal 2  -> http://localhost:5173
python3 -m pulse.cli serve --simulate-present                   # terminal 3 (optional): the unattended worker
```

**C. Containers** (built and run on Apple-silicon/Colima; see README for what that did and did not cover)

```bash
docker compose up --build
docker compose run --rm api python3 -m pulse.cli bootstrap-demo   # builds the estate; prints the sign-in ONCE
# open http://localhost:5173
```

Only one of A/B/C can use port 5173 at a time (`docker compose down` to free it).

## Sign in

The sign-in asks for a **workspace** (the customer organisation), an **email** and a **password**.

| Workspace | Operator — sees the whole tenant, has the **Admin** page | CSM — sees only their own accounts |
|---|---|---|
| `northwind` (2,800 accounts) | `csm00@northwind.example.com` | `csm01@northwind.example.com` |
| `globex` (1,700) | `csm00@globex.example.com` | `csm01@globex.example.com` |
| `initech` (500) | `csm00@initech.example.com` | `csm01@initech.example.com` |

Every demo user in a database shares one password. **It is never in git.** Where it comes from:

- **VS Code / terminal:** `run_all.sh` generates one, prints it at the end, and keeps it in **`.demo-credentials.pulse`** at the repo root
  (git-ignored, mode 0600). The task `Pulse: show demo sign-ins` prints it again. A rebuild reuses the same file, so the password stays stable.
- **Containers:** `bootstrap-demo` generates one and prints it **once**.
- **To choose your own** (recommended for a presentation — at least 12 characters, not a common password):
  `PULSE_DEMO_PASSWORD='your chosen passphrase' bash infra/scripts/run_all.sh` (or set it before `docker compose run … bootstrap-demo`).
  It is applied only to users that have no password yet, so on an existing database run task `RESET demo database` first, then rebuild.

> If you will hand this to someone else, give them the password in the submission message, not in the repository.

## Guided tour (about 6 minutes)

1. **Sign in as the Northwind operator.** The queue is a short, ordered list — bounded to the weekly capacity, with "N more below the cut". Columns: tier, risk, value at risk,
   renewal distance, *why* (the dominant driver), and the change since the last cycle.
2. **Open the top account.** Driver bars show what is pushing the score; **Evidence** lists the source records behind each driver — open one to see the original payload.
   **What moved** compares two dates. *Every number resolves to a record.*
3. **Your judgement.** "Confirm risk is real" / "Mark false positive" are stored as labels. "Suppress from queue" hides the account for N days — it leaves the queue but is still scored.
4. **Low confidence.** Accounts the system refuses to score confidently, with the reason and a remedy — *never* shown green.
5. **Drafts.** A drafted first move beside its grounding. Edit it, then **Approve & send**. In demo mode (the default) the message is **captured, never delivered**, and the page says so.
6. **Sign out, sign in as `csm01@northwind.example.com`.** A much smaller queue (their own accounts only); there is no **Admin** link, and the server refuses the admin API even if you type the URL.
7. **Back as the operator → Admin.** Outbound email is *off until a sender is verified*; demo mode is on; opt-outs; users; the audit trail of who did what.
8. **Run log.** Each cycle's stage counts and the **declined decisions with reasons** — what the agent chose *not* to do, and why.
9. **Be candid** (this is what the exercise rewards): precision@100 is about **0.29 against 0.02** for the heuristic baseline — one draw from 0.22–0.33; ROC-AUC 0.69; a small new
   tenant gets almost nothing from the shared model; the two planted "lost renewal" accounts are *not* flagged, so lead time is not claimed. See `README.md` and `clarifications.md` B-15, B-27.

## Which language model is used, and for what

- **The model that ranks accounts is not a language model.** It is a gradient-boosted tree classifier (scikit-learn), calibrated, with per-feature SHAP attributions summed into six
  business drivers. A language model **never ranks, scores, tiers or filters** anything — the ranking code cannot import it, and the system produces identical scores with it off, on, or failing.
- **A language model only writes.** It drafts the *prose* of the first-move message from a short list of facts the system already derived. It is **Claude (Anthropic)**, through the
  Anthropic SDK. The default model id is **`claude-sonnet-5-5`** (set `PULSE_LLM_MODEL` to change it).
- **It is off by default.** Without a key every draft is a deterministic template, and the whole system works. To turn it on: `pip install -e ".[llm]"`, then
  `PULSE_LLM_ENABLED=true PULSE_LLM_API_KEY=<your key>` and run a cycle (`python3 -m pulse.cli cycle`, or the worker). Drafts then show `draft_source: llm` and the model name.
- **Guardrails:** the model sees only derived facts (never ticket or email text); its reply is rejected — and the template used instead — if it contains any number, link, markup or
  claim that is not traceable to those facts; calls are capped per cycle and a failing provider trips a breaker.

## What is real and what is a stand-in

| | Status |
|---|---|
| Sign-in, sessions, roles, per-CSM scoping, audit | **Real**, tested, and exercised in a browser |
| Scoring, ranking, evidence trail, the unattended worker | **Real** |
| Email delivery code (SMTP, send gate, demo mode, opt-outs) | **Built and tested against a fake mail server. No real email has been sent.** Verify with `python3 -m pulse.cli send-test --to <your own address>` after setting `PULSE_SMTP_HOST/PORT/USER/PASSWORD` |
| Language-model drafting | **Built and tested against scripted replies. No real model call has been made.** Verify as above, with a key |
| Containers | Built and run on one machine (arm64/Colima); no amd64 build |
| The customer data | Simulated (a generator); addresses are `@example.com` — nothing can reach a real person |

## Tests

```bash
cd backend && source .venv/bin/activate && export PGTZ=UTC && python3 -m pytest -q    # uses its own pulse_test database, never the demo one
cd frontend && npm test && npm run build
cd frontend && npm run e2e                                                              # real Chrome, against a scratch copy of the demo DB
```

## Troubleshooting

- **Port 5173 or 8000 is in use** — another copy of the stack is running (`docker compose down`, or stop the VS Code tasks).
- **Postgres not running** — task `Pulse: 1. start Postgres`.
- **Sign-in says "invalid credentials"** — wrong workspace/email/password; five failures from one address-and-account (or fifty from one address) are rate-limited for five minutes.
- **The queue is empty right after `bootstrap-demo`** — the worker is still scoring; wait a couple of minutes.
- **Backend tests stop with "Test database 'pulse_test' is missing or empty"** — build it once: `PULSE_DB_NAME=pulse_test bash infra/scripts/run_all.sh`.
- **`npm run e2e` cannot start a browser** — it uses the Google Chrome you have installed; install Chrome or run `npx playwright install chromium`.
- **Start over** — task `RESET demo database (drops 'pulse' only)`, then task 2.
