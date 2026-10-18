# The demo seed

A pre-built copy of the demo database, so a reviewer sees the populated product in about a minute instead of waiting
8 minutes for `bootstrap-demo` plus 10 to 46 for `backfill --weeks 8` (measured in a clean-clone dry run, 2026-10-18).
All data is simulated (`@example.com` addresses). The seed is a **shortcut, not a replacement**: building from scratch
still works and is documented in the README.

## What is in it

| File (release assets) | What |
|---|---|
| `seed.dump` | the database's **data only** (custom-format `pg_dump`, about 51 MB): tenants, users, accounts, 348k events, nine weekly score snapshots, evidence, drafts, run log |
| `seed.dump.json` | the manifest: schema revision, sha256 of the file, row counts to verify the load against, and how the drafts were written (model, date, model-written vs template counts) |
| `seed.dump.artifacts.tar.gz` | the promoted model (card + pickle, about 60 KB). The model is files, not rows; without it there would be scores but no `/model` report and no worker |

**Deliberately not in it:** sign-in sessions, login attempts, worker leases and the schema version (a seed must not carry the
publisher's live state), and any credential. The users' password hashes in it belong to the publisher's password, so
**loading always sets a password for the person loading** — yours, or one generated and shown once. An export is refused if any
tenant has outbound email enabled: a seed can never ship in a sending state.

## Load it (Docker)

```bash
docker compose up -d --build db api web          # the schema is created when the api starts
docker compose run --rm api python3 -m pulse.cli load-seed --url <the release URL of seed.dump>
# prints the sign-in once; open http://localhost:5173
docker compose up -d worker                       # optional: the unattended agent
```

`--file /path/seed.dump` loads a file you already have (its manifest and model archive sit beside it). The load is one
transaction: if anything fails, nothing is left half-loaded. It refuses a database that already holds tenants unless you pass
`--overwrite`, which is also **the reset**: it empties the demo data and restores the seed. Measured: 15 seconds on a laptop.

## Build and publish one (the owner)

```bash
cd backend && source .venv/bin/activate && export PGTZ=UTC
python3 -m pulse.cli export-seed --out seed.dump --artifacts ../artifacts   # needs pg_dump on the machine; writes the .json and .artifacts.tar.gz beside it
```
Then create a GitHub Release and attach the three files (web upload, or `gh release create`). Put this in the release notes:

> Seed of the demo database built on YYYY-MM-DD from schema revision `<revision>`. N drafts were written by `<model>` on `<date>`
> and M are templates (the model-written drafts come from one real cycle and are not reproducible bit for bit).
> sha256 of `seed.dump`: `<sha256>`.

A seed only loads into a database at the **same schema revision**; rebuild and re-publish it whenever a migration lands.
