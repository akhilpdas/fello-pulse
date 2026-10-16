# Pulse — renewal-risk prioritisation for Customer Success

Pulse gives each CSM, every Monday and without being asked, a short ranked list of the
accounts where their attention changes the outcome, the evidence behind the ranking,
and a drafted first move. It runs on its own: ingest → score → detect change → draft →
record, with nothing gated on a person opening a page.

Run it in VS Code: `Terminal ▸ Run Task…` → the numbered `Pulse:` tasks (details in the quickstart).
Sign in with a workspace + email + password (task **show demo sign-ins**); CSMs see only their own accounts, operators the whole tenant — identity comes from a verified session, never from a header. Task **4** starts the unattended worker (`python3 -m pulse.cli serve`): a loop that cycles each tenant when
it is due, leased so two workers can't double-run a tenant, recording a `failed` run (and carrying on with
the other tenants) if one tenant's cycle breaks.

Start here: [`specs/001-renewal-risk-prioritisation/quickstart.md`](specs/001-renewal-risk-prioritisation/quickstart.md)
— `bash infra/scripts/run_all.sh` takes an empty database to a scored, populated system.

## The decisions that matter

The request asked for a health-score dashboard and an automatic email to red accounts.
The evidence in the request describes a different problem (attention allocation and lead
time), so the spec disagrees with it in six places (`spec.md`, D1–D6). In short:

| Asked for | Built instead | Why |
|---|---|---|
| One health score | Probability of churn-or-contraction within 90 days, split into six drivers; 0–100 is a display transform | Two accounts at 62 need opposite interventions |
| Auto-email red accounts | The agent drafts; a human approves. Auto-send is per-tenant, per-play, off by default, with suppression and rate limits | Precision, causality (red often means *we* failed them) and ownership |
| Red/amber/green level | Ranked by `p × value at risk × renewal urgency`, shown with the delta since last cycle | A 14-month amber is known; green→amber in nine days is the emergency |
| A list of reds | A queue bounded to weekly capacity, with the below-the-cut count | Forty reds is the spreadsheet again |
| A colour for everyone | An explicit low-confidence bucket with reason and remedy; never green | Thin evidence scored confidently is how trust is lost |

The five constitutional non-negotiables and the test that proves each:

1. **Point-in-time correctness** — features read only `received_at <= as_of`; denylisted outcome columns are unreachable by type; one pure code path serves training and serving. *Tests:* `tests/leakage/`, train/serve parity.
2. **Fitted models rank, language models only write** — no LLM module is reachable from ranking; the system runs fully with the LLM disabled. *Tests:* `test_no_llm_in_ranking`, `test_runs_without_llm`.
3. **Autonomy with a reviewed boundary** — allowlist, suppression window, rate limit; every declined decision is recorded with its reason in the run log. *Tests:* dispatch gate, suppression/rate-limit, action lifecycle.
4. **Tenant isolation below the application** — Postgres row-level security, `FORCE`d, on all 13 tenant tables; the app role is `NOBYPASSRLS`; the tenant claim is transaction-local. *Tests:* `tests/isolation/`, mutation-verified (`docs/VERIFICATION.md`).
5. **Nothing unexplained reaches a human** — every score persists with SHAP drivers and resolvable evidence ids; drafts are grounding-validated before anyone sees them. *Tests:* evidence trail, score diff, grounding validation.

## Containers — built and run on one machine

`docker-compose.yml` + `infra/docker/` define the database, API, the unattended worker and the web app. **Verified on 2026-10-17 on a Mac
(Apple silicon, macOS 26) using Colima — i.e. linux/arm64 — and nowhere else:**
- all three images **build** (api and worker 882 MB, web 92 MB); the processes run as non-root (uid 10001 / nginx); no data, models, `.env` or credential
  is in any image, and no credential-named variable is baked into one;
- `docker compose up` brings the stack healthy: Postgres, then the API (which runs the migrations), the worker, and nginx;
- the **worker waits** when there is no model yet and picks the model and tenants up by itself once they exist (this crash-looped on the first run — found by
  running it, fixed test-first);
- `docker compose run --rm api python3 -m pulse.cli bootstrap-demo` builds the whole estate inside the container: 347,740 events, and **ROC-AUC 0.690, precision@100
  0.289 — identical to the host build** (different OS, Python 3.13 vs 3.14, different database);
- the **9 browser scenarios pass in real Chrome against the containers** (`infra/scripts/e2e_docker.sh`), through nginx;
- data survives `docker compose down` / `up` (volumes), and a restarted stack signs in and serves the same queue.

```bash
docker compose up --build
docker compose run --rm api python3 -m pulse.cli bootstrap-demo     # builds the demo estate; prints the sign-in once
# open http://localhost:5173
```

**Not verified:** a **linux/amd64** build (only arm64 was built — Python wheels such as shap/numba/scikit-learn are the likeliest thing to differ); the spec's
"under ten minutes from a clean machine" timing (SC-012 — not measured); image vulnerability scans; running with a real provider or a real model key inside the
stack. Known limits: the application database roles' passwords are fixed by migration 0002 (development defaults — change before exposing anything); images are not
pinned by digest; there is no TLS terminator.

## Layout

```
backend/pulse/   features/ ml/ scoring/ domain/ agent/ ingest/ api/ db/ auth/ tools/   (FastAPI + SQLAlchemy + scikit-learn)
                 auth/ sessions, passwords, login limiter, audit · agent/ cycle, delivery, SMTP transport, LLM drafter · tools/ the fake mail server
backend/tests/   unit/ integration/ isolation/ leakage/ contract/
generator/       the simulated estate: 3 tenants, ~5,000 accounts, ~350k events, five sources, 12 data pathologies
frontend/        React 19 + Vite + TypeScript (sign-in, queue, account, drafts, run log, low confidence, operator Admin)
frontend/e2e/    Playwright tests that drive the real UI in real Chrome (`npm run e2e`)
infra/scripts/   pg_bootstrap.sh, run_all.sh, e2e.sh   ·   infra/docker/ + docker-compose.yml (built and run on arm64/Colima)
docs/            SOLUTION_BRIEF, DECK (+ Pulse_deck.pptx), LOOM_SCRIPT, VERIFICATION (what was checked, how, and what was not)
specs/001-…/     the delivered system: spec, plan, data model, contracts (incl. openapi.yaml), tasks, clarifications (B-1…B-29)
specs/002-…/     production readiness: sign-in, real email, model drafting, containers — spec, plan, research, data model, tasks
```

## What was verified, and what was not

**Automated, and re-run before each commit:** backend suite (`python3 -m pytest -q`, 436 tests, against its own `pulse_test` database — never the demo one),
frontend unit tests (`npm test`, 34), and **9 browser scenarios in real Google Chrome** against the real API and a scratch copy of the demo data
(`npm run e2e`: sign-in/out, a wrong password, the operator queue, account feedback and suppression, the operator pages, approving a draft in demo mode,
CSM scoping and the server refusing the admin API). The OpenAPI contract has a drift test. **Mutation-checked** (each protection removed, a named test goes red):
tenant isolation, identity forgery, CSM ownership, approver identity, the send gate, demo mode, no-retry-on-ambiguous, the LLM output validator, the
provider-failure fallback and prompt isolation (`docs/VERIFICATION.md`). `run_all.sh` was run from an empty database (exit 0) and training was reproduced
across a full rebuild.

**The model, honestly.** Precision@100 is **0.29** against **0.02** for the heuristic baseline (about 12×); ROC-AUC **0.69**. That is one draw from a
range — **0.22–0.33** — because the figure moves with row order (B-27); it is reproducible for a given dataset, not a point to quote to two decimals.
A *new* tenant the model has not seen does worse (leave-one-tenant-out ROC-AUC: globex 0.71, northwind 0.67, **initech 0.53**), so for a small new tenant the
shared model barely helps. Against the spec's success criteria: **met** SC-001/002 (queue and evidence trail), SC-003, SC-007 (a full cycle over ~4,500 accounts in
about 105 s against a 15-minute interval), SC-008–SC-014. **Not met — SC-005 and SC-006:** ROC-AUC is far below the 0.8+ the generator allows, and the two planted
"lost renewal" accounts are **not flagged** at any point (`clarifications.md` B-15); I did not tune against the two fixtures, which would be overfitting the demo, so
**lead time is not reported** (`GET /model` says so). SC-004 (calibration tolerance) is reported as a reliability curve but its tolerance is not asserted.

**Not verified — stated so nobody assumes otherwise:**
- **No real email has ever been sent** by this system, and **no real language-model call has ever been made.** Both are exercised only against stand-ins (an in-process
  fake SMTP server; scripted model replies). The real SMTP path and the 15-line Anthropic adapter have never run against a real provider. **To verify real email in one minute:** set `PULSE_SMTP_HOST`,
  `PULSE_SMTP_PORT`, `PULSE_SMTP_USER`, `PULSE_SMTP_PASSWORD` for a provider you have an account with, then `python3 -m pulse.cli send-test --to <your own address> --sender <an address the provider lets you send from>` —
  it sends one labelled test message, touches no customer or database, and reports delivered / refused / unconfirmed.
- **The containers were run on one machine only** (arm64, Colima) — see *Containers* for what that did and did not cover; no amd64 build.
- The browser tests cover the main paths and the key refusals in **Chrome only** — no other browser, no mobile layout, no accessibility audit.
- The shared login limiter is tested with two limiter objects, not two real processes. Nothing has been load-tested; the 10× claim below is arithmetic from one measurement.

## Decisions (with reasons)

- **Draft, don't send — and when sending, be safe by default.** The request asked to email red accounts automatically. Red often means *we* failed the customer; a cheerful template to someone
  with a nine-day-old P1 does harm. A human approves; auto-send is opt-in per tenant per play, behind suppression and rate limits. Outbound is **off** until an operator verifies a sender;
  **demo mode is the default** (mail goes only to a test inbox, or is captured without delivery); an opted-out or contact-less account is never emailed.
- **A message that might have been sent is never sent again.** An ambiguous outcome (the body went out, no answer came back) becomes `send_unconfirmed` for a human — exactly-once is not
  achievable over a provider-neutral mail protocol, so the guarantee is "never *knowingly* twice".
- **A model ranks; a language model only writes** — from derived facts, never from ticket or email text, and its output is rejected if any number, link or claim does not trace to those facts.
  The system runs identically with it off, on, or failing.
- **Opaque server-side sessions, not JWTs; login by workspace.** Revocable, and a changed role bites on the next request; the same email can exist in two tenants. Tenant isolation is
  still enforced by the database, and now the tenant comes from a verified session rather than a header.
- **One shared model**, per-tenant slices reported but not fitted (most tenants have too few churn events to fit one — the cold-start result above is the cost of that choice).
- **No uplift modelling.** There is no intervention history to learn "did the call help" from; outcomes are recorded so it can be added.

## Gaps (not done — these are not decisions)

- **Sign-in:** no SSO/OIDC, MFA, self-service sign-up or email-driven password reset (operators reset passwords). Every demo user shares one generated password. `Secure` cookies are off by
  default (turn on behind HTTPS) and there is no TLS terminator. The application database roles' passwords are fixed in a migration (development defaults).
- **Email:** bounces, complaints and replies are not processed, so a hard bounce is unknown and an opt-out sent by reply must be entered by an operator. SMTP credentials are deployment-level, not
  per tenant. No contact import.
- **Model:** lead time is not reported and the planted retrospective accounts are missed (above); no per-tenant model; the cold-start result for small tenants is weak.
- **Data quality:** account names are not unique within a tenant (309 repeated names in the Northwind demo estate, as in a real CRM) and the queue shows no disambiguator; accounts the CRM has no record of are drafted
  for and greeted by their external reference ("Hi northwind-01261") — the send gate blocks them (no contact) but a CSM still sees such drafts, about 11% of the list.
- **Operations:** a whole-tenant cycle is one transaction (one bad account fails the tenant's cycle); a persistently failing tenant is retried every 30 s with no backoff; login attempts and
  the audit trail are not exported or paginated beyond the last 200 events.
- **Containers:** verified on arm64 only; no amd64 build, no scan, no timing of the clean-machine path (see *Containers*).
- **Presentation:** the deck is an `.pptx` built from `docs/DECK.md`; the Loom walkthrough is a **script** (`docs/LOOM_SCRIPT.md`) and has **not been recorded**; there is no hosted URL — the system runs locally.

## What breaks first at 10×

At 50,000 accounts the **cycle**, first. Scoring loads each account's events with its own
queries (~23 ms/account → ~19 minutes), which exceeds the 15-minute interval. The fixes are
already half-present: leases allow one worker per tenant, so the first step is more workers
and batched event loading; then change-driven rescoring (only accounts with new events).
Next is **training**: the panel builder is in-memory Python (~131k rows today, ~1.3M at 10×),
which will need chunked or columnar construction. Isolation, ranking and the API are not on the
critical path at this scale.
