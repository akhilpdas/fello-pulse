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

## Containers — UNVERIFIED

`docker-compose.yml` + `infra/docker/` define the database, API, the unattended worker and the web app. **Treat this as
unverified: none of it has ever been built or run** (Docker is not installed on the dev machine). What *is* checked,
without a container runtime, by `tests/unit/test_container_files.py`: dependency ordering and healthchecks, the
database in a named volume and not published to the network, no secrets or generated data baked into an image,
a non-root user, and a build context that excludes data, models, `.env` and credentials. To try it:

```bash
docker compose up --build
docker compose run --rm api python3 -m pulse.cli bootstrap-demo     # builds the demo estate; prints the sign-in
# open http://localhost:5173
```

When someone runs this on a machine with Docker, record the outcome in `HANDOFF.md` and remove this label. Known limits:
the application roles' passwords are fixed by migration 0002 (development defaults — change before exposing anything);
images are not scanned or pinned by digest; no TLS terminator is included.

## Layout

```
backend/pulse/   features/ ml/ scoring/ domain/ agent/ ingest/ api/ db/    (FastAPI + SQLAlchemy + scikit-learn)
backend/tests/   unit/ integration/ isolation/ leakage/ contract/
generator/       the simulated estate: 3 tenants, ~5,000 accounts, ~350k events, five sources, 12 data pathologies
frontend/        React 19 + Vite + TypeScript (queue, account, drafts, run log, low confidence)
infra/scripts/   pg_bootstrap.sh, run_all.sh
specs/001-…/     spec, plan, data model, contracts (incl. openapi.yaml), tasks, clarifications
```

## What was verified, and what was not

Backend suite and frontend tests are green (`python3 -m pytest -q`; `npm test`). The
OpenAPI contract is guarded by a test that fails if the API changes without regenerating it.
`run_all.sh` was run against an empty database (see `HANDOFF.md` for the numbers).

Against the spec's success criteria — stated plainly, including the misses:

- **Met:** SC-001/002 (queue and evidence trail), SC-003 (precision@100 0.20 vs 0.02 for the heuristic baseline, seed 7), SC-007 (a full cycle over ~4,500 accounts in about 105 s against a 15-minute interval), SC-008–SC-014.
- **Not met — SC-005 and SC-006.** ROC-AUC on the held-out block is **0.68**, below the 0.8+ the generator was designed to allow, and the two planted retrospective accounts (the stand-ins for "the two renewals we lost") are **not flagged** at any point in their history. Their individual features do show decline; the support-degradation story is carried by response time while the model leans on ticket volume. This is investigated in `clarifications.md` B-15. I did not tune against the two fixtures, which would be overfitting to the demo. **The lead-time distribution is therefore not reported** (`GET /model` says so rather than omitting it).
- **SC-004 (calibration tolerance)** is reported as a reliability curve; the tolerance check itself is not asserted.

## Deliberately skipped

- **Real email transport and a live LLM.** Transport is a recording stub; the LLM drafting path exists behind the same interface but is lazily imported only when enabled, and is unreachable by default.
- **Authentication.** Tenant and user come from headers; isolation does not depend on how the caller was identified, but a real deployment needs a session in front of it.
- **Treatment-effect (uplift) modelling.** No intervention history exists (B4); risk only. Play outcomes are recorded so uplift is possible later.
- **Per-tenant models.** One shared model (B-7); per-tenant slices are reported, not fitted.
- **`docker-compose.yml` / `Makefile` (T004).** The compose file and Dockerfiles now exist (see *Containers* below) but are **unverified** — they have never been built or run, because Docker is not installed on the machine this was built on. There is no `Makefile`; `run_all.sh` remains the verified one-command path.
- **Lead-time backtest** — see above.

## What breaks first at 10×

At 50,000 accounts the **cycle**, first. Scoring loads each account's events with its own
queries (~23 ms/account → ~19 minutes), which exceeds the 15-minute interval. The fixes are
already half-present: leases allow one worker per tenant, so the first step is more workers
and batched event loading; then change-driven rescoring (only accounts with new events).
Next is **training**: the panel builder is in-memory Python (~131k rows today, ~1.3M at 10×),
which will need chunked or columnar construction. Isolation, ranking and the API are not on the
critical path at this scale.
