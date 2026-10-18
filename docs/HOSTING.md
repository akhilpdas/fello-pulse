# Putting the demo in front of a reviewer — free hosting

The team said hosting need not be paid and suggested **Vercel, Railway or Render** "depending on your application's
requirements". Spec: `specs/003-hosted-demo/`. **Nothing here has been deployed yet**; each step says what was exercised.

## Recommendation

**Render first** (free web service + free Postgres + this repo's Dockerfile). **Railway if Render cannot run it** ($5 is
acceptable). **Vercel is not a fit** on its own: it is a serverless platform (no database, no long-running process); at most it
could serve the UI, and the API and database would still need a home.

| | Free? | Fits the app? | Catch |
|---|---|---|---|
| **Render** | Web service 750 h/month, Postgres 1 GB (expires after 30 days, 14-day grace), static sites free | Demo database is 564 MB (fits); app uses ~240 MB of the 512 MB RAM | sleeps after 15 idle minutes (about 1 minute to wake); **no free background worker**; **unknown whether its database user can create roles** (below) |
| **Railway** | one-off $5 trial credit, then Free ($1/month credit) or Hobby ($5/month) | real Postgres with a superuser, no sleeping, a worker is possible | Free/Trial volumes are 0.5 GB (the demo is 564 MB) so Hobby ($5, 5 GB) is the realistic choice; usage-based, so credit can run out and stop the service |
| **Vercel** | Hobby free | UI only | no database, no worker; serverless functions (300 s max) do not suit this API |

Limits are from each platform's documentation on 2026-10-18 ([Render](https://render.com/docs/free),
[Railway](https://docs.railway.com/reference/pricing/plans), [Vercel](https://vercel.com/docs/functions/limitations)); re-check at deploy time.

## What the hosted demo is — and is not

One web service serves the UI and the API on one address (`infra/docker/hosted.Dockerfile`, `pulse.api.hosted`). The data comes
from the **demo seed** (`docs/SEED_RELEASE.md`), loaded on first start. There is **no worker** on a free tier, so the "unattended
agent" is shown by the seeded run log and the recorded walkthrough, not live. The hosted demo is **writable**: reviewers can
approve, suppress and change settings; the owner resets it with one command (below). Demo mode is on, so no email reaches a
real person.

## Step 0 — the go/no-go check for Render (about 2 minutes, no code)

1. Create a free Render Postgres (database name `pulse`).
2. Copy its **external** URL and run `bash infra/render/probe.sh "<url>"`.
   - `GO` → continue below.
   - `NEEDS-CHANGES` → Render can host it only after spec 003 task T023 (skip the training role; lift FORCE row-level security for the
     length of the seed load). Ask for that change, or use Railway.
   - `NO-GO` → use Railway.

The probe is tested (4 tests) against a superuser, a CREATEROLE user and a plain user; it has not been run against Render.

## Render

1. Publish the seed (`docs/SEED_RELEASE.md`) and copy the URL of `seed.dump`.
2. Push this repo to GitHub, then in Render: **New → Blueprint** → pick the repo (it reads `render.yaml`).
3. In the service's environment set `PULSE_DEMO_PASSWORD` (12+ characters) and `PULSE_SEED_URL`. Deploy.
4. First start: migrates, downloads the seed over HTTPS, verifies its checksum, loads it (about 17 s locally), then serves.
5. Open the URL, sign in as `csm00@northwind.example.com` (workspaces `northwind`, `globex`, `initech`).
6. **Afterwards:** in the database's settings restrict external access (IP allow list) — the request-serving database login uses a
   development password fixed by the migration (a documented gap in the README), and a free Render database is reachable from
   anywhere with the right credentials until you do.

`render.yaml` is **unverified** against Render's own validator. Stated limits to tell the reviewer: the first request after idle takes
about a minute; the database expires 30 days after creation.

## Railway (fallback)

New project → deploy from the GitHub repo using `infra/docker/hosted.Dockerfile`; add the **PostgreSQL** plugin; set
`DATABASE_URL` to the plugin's connection URL, `PULSE_COOKIE_SECURE=true`, `PULSE_DEMO_PASSWORD`, `PULSE_SEED_URL`. Railway's Postgres
gives a superuser, so no code change is needed. Choose Hobby ($5) for the 5 GB volume. **Unverified**; record the credit actually
burned after a week.

## Reset the hosted demo (owner only)

From a shell with the same environment as the service (Render: the service's **Shell**, a paid feature — or run it from your
machine with the database's external URL): `python3 -m pulse.cli load-seed --url "$PULSE_SEED_URL" --overwrite`. There is no
route or button for this; it cannot be triggered from the web.

## What has and has not been exercised

| Claim | Status |
|---|---|
| The hosted image serves the UI and the API on one port; 13/13 browser scenarios pass against it | **Exercised** (Docker, local) |
| Empty database → migrate → download the seed over HTTPS → verify → load → serve in 17 s | **Exercised** (Docker, local; a throwaway certificate stood in for GitHub) |
| App memory after the full browser suite: 237 MB | **Measured** |
| The probe's verdicts | **Tested** locally against three kinds of user |
| Render accepts `render.yaml`; the database user's privileges; free-tier cold start of ~1 minute | **Not exercised** |
| Railway deploy, cost and credit burn | **Not exercised** |
| Reviewers using the URL at the same time | **Not exercised** |

## Doing it from your own laptop instead (no hosting account)

`docker compose up -d --build db api web`, load the seed, then expose port 5173 with a Cloudflare quick tunnel
(`cloudflared tunnel --url http://localhost:5173`). Free, but the link changes each time and dies when the laptop sleeps.
