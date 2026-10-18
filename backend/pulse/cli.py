"""Operational entry points.

    python3 -m pulse.cli bootstrap --feeds ../data/feeds
    python3 -m pulse.cli ingest --feeds ../data/feeds [--until ISO8601]
    python3 -m pulse.cli status

``--until`` holds back the most recent arrivals so the autonomous worker has
real work to do on its first cycle. A demonstration of an unattended system
whose run log is a column of zeros demonstrates nothing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from sqlalchemy import text

from pulse.auth.passwords import validate_password
from pulse.config import SystemClock, get_settings
from pulse.db.session import owner_session, tenant_session
from pulse.ingest.dimension import refresh_accounts
from pulse.ingest.service import (
    bootstrap_tenant,
    ingest_source,
    provision_tenant_data,
)


def _tenant_dirs(feeds: Path) -> list[Path]:
    return sorted(p for p in feeds.iterdir() if p.is_dir() and (p / "tenant.json").exists())


def cmd_bootstrap(args) -> int:
    feeds = Path(args.feeds).resolve()
    demo_password = args.demo_password or os.environ.get("PULSE_DEMO_PASSWORD") or None
    if demo_password:
        validate_password(demo_password, "demo@example.test")  # fail loudly, not with a user nobody can sign in as
    for d in _tenant_dirs(feeds):
        with owner_session() as s:
            res = bootstrap_tenant(s, d)
        with tenant_session(res.tenant_id) as s:
            out = provision_tenant_data(s, res.tenant_id, d, demo_password=demo_password)
        print(f"  {out.slug:10s} tenant={res.tenant_id} users={out.users} "
              f"accounts={out.accounts} identity_links={out.identity_links}")
    return 0


def cmd_ingest(args) -> int:
    feeds = Path(args.feeds).resolve()
    clock = SystemClock()
    until = datetime.fromisoformat(args.until) if args.until else None
    grand = 0
    for d in _tenant_dirs(feeds):
        cfg = json.loads((d / "tenant.json").read_text())
        tid = _tenant_id(cfg["slug"])
        if tid is None:
            print(f"  {cfg['slug']}: not bootstrapped, skipping")
            continue
        t0 = time.time()
        totals = {}
        with tenant_session(tid) as s:
            for source in cfg["connected_sources"]:
                path = d / f"{source}.jsonl"
                if not path.exists():
                    continue
                r = ingest_source(s, tid, source, path, clock, until=until)
                totals[source] = {"read": r.read, "inserted": r.inserted,
                                  "unresolved": r.unresolved, "rejected": r.rejected}
            dim = refresh_accounts(s, tid)
        ins = sum(v["inserted"] for v in totals.values())
        grand += ins
        print(f"  {cfg['slug']:10s} inserted={ins:7d} in {time.time()-t0:6.1f}s  dim={dim}")
        for src, v in totals.items():
            print(f"      {src:11s} read={v['read']:7d} inserted={v['inserted']:7d} "
                  f"unresolved={v['unresolved']:6d} rejected={v['rejected']}")
    print(f"TOTAL inserted: {grand}")
    return 0


def _tenant_id(slug: str):
    with owner_session() as s:
        return s.execute(text("SELECT id FROM tenant WHERE slug = :s"), {"s": slug}).scalar()


def cmd_status(args) -> int:
    with owner_session() as s:
        rows = s.execute(
            text(
                "SELECT t.slug, count(DISTINCT a.id) AS accounts,"
                " (SELECT count(*) FROM source_event e WHERE e.tenant_id = t.id) AS events,"
                " count(*) FILTER (WHERE a.lifecycle_state = 'churned') AS churned,"
                " count(*) FILTER (WHERE a.lifecycle_state = 'contracted') AS contracted,"
                " count(*) FILTER (WHERE a.acv_cents IS NULL) AS no_acv"
                " FROM tenant t LEFT JOIN account a ON a.tenant_id = t.id"
                " GROUP BY t.id, t.slug ORDER BY t.slug"
            )
        ).all()
        for r in rows:
            print(f"  {r.slug:10s} accounts={r.accounts:5d} events={r.events:7d} "
                  f"churned={r.churned:4d} contracted={r.contracted:4d} no_acv={r.no_acv:4d}")
        unresolved = s.execute(
            text("SELECT source, count(*) n FROM identity_link WHERE account_id IS NULL"
                 " GROUP BY source ORDER BY n DESC")
        ).all()
        print("  unresolved identities:", {r.source: r.n for r in unresolved} or "none")
    return 0


def cmd_cycle(args) -> int:
    """One autonomous cycle for every ingested tenant, as of ``--as-of`` (default:
    the newest event received). Thin wrapper over agent.worker.tick -- no decisions here."""
    from pulse.agent.transport import select_transport
    from pulse.agent.worker import build_runtime, tick
    from pulse.config import FrozenClock, get_settings
    from pulse.db.session import elevated_session
    from pulse.ml.pipeline import trainable_tenants
    from pulse.ml.registry import load_promoted_model

    model, version = load_promoted_model(Path(args.artifacts))
    with elevated_session() as s:
        tenants = trainable_tenants(s)
    as_of = datetime.fromisoformat(args.as_of) if args.as_of else _data_present()
    runtimes = [build_runtime(tid, model=model, model_version=version, transport=select_transport(get_settings()))
                for tid, _ in tenants]
    settings = get_settings()
    t0 = time.time()
    results = tick(runtimes, clock=FrozenClock(as_of), worker_id="cli", lease_seconds=settings.lease_seconds,
                   cycle_interval_minutes=settings.cycle_interval_minutes)
    print(f"model {version}, as_of {as_of.isoformat()}, {len(results)}/{len(runtimes)} tenants ran "
          f"in {time.time() - t0:.1f}s")
    for r in results:
        print(f"  run {r.run_id}: {r.stage_counts} declined={len(r.decisions_declined)}")
    return 0


def cmd_backfill(args) -> int:
    """Weekly score history before each tenant's newest snapshot, so the queue has something to browse and compare.
    Scores only -- no drafts, no sends, no run records (see scoring/backfill.py for the in-sample caveat)."""
    from pulse.agent.transport import select_transport
    from pulse.agent.worker import build_runtime
    from pulse.config import get_settings
    from pulse.db.session import elevated_session
    from pulse.ml.pipeline import trainable_tenants
    from pulse.scoring.backfill import backfill_snapshots

    model, version = _load_promoted(args.artifacts)
    with elevated_session() as s:
        tenants = trainable_tenants(s)
    for tenant_id, slug in tenants:
        with owner_session() as s:
            anchor = s.execute(text("SELECT max(as_of) FROM score WHERE tenant_id = :t"), {"t": tenant_id}).scalar()
        if anchor is None:
            print(f"  {slug:10s} no snapshot to anchor on -- run a cycle first")
            continue
        rt = build_runtime(tenant_id, model=model, model_version=version, transport=select_transport(get_settings()))
        with tenant_session(tenant_id) as s:
            done = backfill_snapshots(s, tenant_id=tenant_id, model=model, model_version=version,
                                      tenant_config=rt.tenant_config, anchor=anchor, weeks=args.weeks)
        print(f"  {slug:10s} {len(done)} weekly snapshots before {anchor.date()}, {sum(done.values())} scores")
    return 0


def _data_present():
    """The simulated "now": the newest moment every source of the ingested tenants has reported (B-30)."""
    from pulse.db.session import elevated_session
    from pulse.ingest.present import data_present
    from pulse.ml.pipeline import trainable_tenants

    with elevated_session() as s:
        tenant_ids = [tid for tid, _ in trainable_tenants(s)]
    with owner_session() as s:
        return data_present(s, tenant_ids)


def _load_promoted(artifacts: str):
    from pulse.ml.registry import load_promoted_model

    return load_promoted_model(Path(artifacts))


def cmd_serve(args) -> int:
    """The unattended worker: tick every few seconds, cycle each tenant when it is due.

    Runtimes are resolved every tick (the promoted model, the ingested tenants), so a worker started before the first
    bootstrap *waits* and then picks everything up with no restart. ``--simulate-present`` runs on the data's present
    (its newest event) and lets it advance in real time -- the demo data is dated later than the wall clock. Thin wrapper
    over worker.serve."""
    from pulse.agent.transport import select_transport
    from pulse.agent.worker import build_runtime, serve
    from pulse.config import LazyOffsetClock, SystemClock, get_settings
    from pulse.db.session import elevated_session
    from pulse.ml.pipeline import trainable_tenants

    def resolve():
        model, version = _load_promoted(args.artifacts)  # LookupError until a model has been promoted
        with elevated_session() as s:
            tenants = trainable_tenants(s)
        if not tenants:
            raise LookupError("no ingested tenants yet")
        transport = select_transport(get_settings())
        return [build_runtime(tid, model=model, model_version=version, transport=transport) for tid, _ in tenants]

    clock = LazyOffsetClock(SystemClock(), _data_present) if args.simulate_present else SystemClock()
    settings = get_settings()
    try:
        ready = resolve()
        status = f"{len(ready)} tenants, model ready"
    except LookupError as exc:
        status = f"waiting ({exc}); will keep checking"
    print(f"pulse worker: {status}; cycle every {settings.cycle_interval_minutes} min, "
          f"tick {settings.worker_tick_seconds}s  (Ctrl-C to stop)", flush=True)
    try:
        serve(resolve, clock=clock, max_ticks=args.max_ticks)
    except KeyboardInterrupt:
        print("stopped")
    return 0


def _feeds_present(feeds: Path) -> bool:
    return (feeds / "manifest.json").exists()


def _generate(feeds: Path, seed: int) -> None:
    """Run the simulator (a separate script, deliberately not part of the application package)."""
    import subprocess

    script = Path(os.environ.get("PULSE_GENERATOR", "../generator/main.py"))
    subprocess.run([sys.executable, str(script), "--out", str(feeds), "--seed", str(seed)], check=True)


def _train() -> None:
    from pulse.ml import pipeline

    pipeline.run()


def _operators() -> list[tuple[str, str]]:
    with owner_session() as s:
        return [(r[0], r[1]) for r in s.execute(text(
            "SELECT t.slug, u.email FROM tenant t JOIN app_user u ON u.tenant_id = t.id AND u.role = 'operator'"
            " WHERE EXISTS (SELECT 1 FROM ingestion_watermark w WHERE w.tenant_id = t.id) ORDER BY t.slug")).all()]


def cmd_bootstrap_demo(args) -> int:
    """The container path's ``run_all.sh``: generate (if needed) -> bootstrap -> ingest -> train -> one cycle, then
    say how to sign in. Idempotent -- re-running fills in only what is missing."""
    import secrets

    feeds = Path(args.feeds).resolve()
    password = args.demo_password or os.environ.get("PULSE_DEMO_PASSWORD") or None
    generated = password is None
    if generated:
        password = secrets.token_urlsafe(12)
    if not _feeds_present(feeds):
        print("generating the simulated estate ...", flush=True)
        _generate(feeds, args.seed)
    cmd_bootstrap(argparse.Namespace(feeds=args.feeds, demo_password=password))
    cmd_ingest(argparse.Namespace(feeds=args.feeds, until=None))
    _train()
    cmd_cycle(argparse.Namespace(as_of=None, artifacts=args.artifacts))
    print("\nSign in at http://localhost:5173 (workspace = the tenant name):")
    for slug, email in _operators():
        print(f"  workspace {slug:10s} operator {email}")
    if generated:
        print(f"  password: {password}   (shown once; set PULSE_DEMO_PASSWORD to choose your own)")
    else:
        print("  password: the one you supplied")
    print("  Note: if the worker is running it starts scoring as soon as the model exists, so the queue may still be "
          "filling in -- give it a couple of minutes if it looks empty.")
    return 0


def _libpq_dsn() -> str:
    from pulse.config import get_settings
    return get_settings().database_url_owner.replace("postgresql+psycopg://", "postgresql://")


def _seed_tables(session) -> list[str]:
    from pulse.seed import EXCLUDED_TABLES
    names = [r[0] for r in session.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1")).all()]
    return [n for n in names if n not in EXCLUDED_TABLES]


def _seed_row_counts(session) -> dict[str, int]:
    return {t: session.execute(text(f'SELECT count(*) FROM "{t}"')).scalar() for t in _seed_tables(session)}


def cmd_export_seed(args) -> int:
    """Dump the built demo database (data only; no sessions, no login attempts) with a manifest that describes the file."""
    import subprocess
    from datetime import date

    from pulse.seed import SeedError, export_seed

    with owner_session() as s:
        revision = s.execute(text("SELECT version_num FROM alembic_version")).scalar()
        counts = _seed_row_counts(s)
        outbound = s.execute(text("SELECT count(*) FROM tenant_config WHERE outbound_enabled")).scalar()
        by_source = dict(s.execute(text("SELECT draft_source, count(*) FROM action GROUP BY 1")).all())
        model = s.execute(text("SELECT draft_model FROM action WHERE draft_source <> 'template' AND draft_model IS NOT NULL"
                               " GROUP BY 1 ORDER BY count(*) DESC LIMIT 1")).scalar()
    today = date.today().isoformat()
    drafts = {"model": model, "date": today, "template": by_source.get("template", 0),
              "llm": sum(n for k, n in by_source.items() if k != "template")}
    try:
        m = export_seed(dsn=_libpq_dsn(), out=Path(args.out), revision=revision, row_counts=counts, drafts=drafts,
                        created=today, outbound_enabled_tenants=outbound, run=subprocess.run,
                        artifacts_dir=Path(args.artifacts))
    except SeedError as exc:
        print(f"not exported: {exc}")
        return 1
    size = Path(args.out).stat().st_size / 1048576
    print(f"wrote {args.out} ({size:.0f} MB) and {args.out}.json\n  schema revision {m.schema_revision}, sha256 {m.sha256[:16]}…, "
          f"{counts.get('account', 0)} accounts, {counts.get('score', 0)} scores\n  drafts: {drafts['llm']} model-written"
          f"{' by ' + drafts['model'] if drafts['model'] else ''}, {drafts['template']} template")
    return 0


def cmd_load_seed(args) -> int:
    """Load a seed into a migrated database in minutes. ``--overwrite`` replaces data already there (the owner's reset)."""
    import secrets
    import tempfile
    import urllib.request

    from pulse.auth.passwords import hash_password
    from pulse.seed import Manifest, SeedError, load_seed, restore_stream

    workdir = Path(tempfile.mkdtemp(prefix="seed-"))
    if args.url:
        if not args.url.startswith("https://"):
            print("--url must be an https:// address")
            return 1
        file = workdir / "seed.dump"
        print(f"downloading {args.url} …", flush=True)
        urllib.request.urlretrieve(args.url, file)                       # noqa: S310 - https only, checked above
        urllib.request.urlretrieve(args.url + ".json", workdir / "seed.dump.json")  # noqa: S310
        try:
            urllib.request.urlretrieve(args.url + ".artifacts.tar.gz", workdir / "seed.dump.artifacts.tar.gz")  # noqa: S310
        except OSError:
            pass                                                     # a seed without a model: the manifest says so
        manifest_path = workdir / "seed.dump.json"
    else:
        file = Path(args.file)
        manifest_path = file.with_name(file.name + ".json")
    manifest = Manifest.from_json(manifest_path.read_text())

    password = args.demo_password or os.environ.get("PULSE_DEMO_PASSWORD") or None
    generated = password is None
    if generated:
        password = secrets.token_urlsafe(12)

    session = owner_session().__enter__()                                  # one connection for the whole load
    try:
        tenants = session.execute(text("SELECT count(*) FROM tenant")).scalar()
        revision = session.execute(text("SELECT version_num FROM alembic_version")).scalar()

        def truncate():
            names = ", ".join(f'"{t}"' for t in [r[0] for r in session.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'")).all()])
            session.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
            session.commit()

        def set_passwords(pw):
            session.execute(text("UPDATE app_user SET password_hash = :h, password_changed_at = now()"), {"h": hash_password(pw)})
            session.commit()

        def counts():
            session.commit()                                               # see what pg_restore (another connection) wrote
            return _seed_row_counts(session)

        try:
            load_seed(file=file, manifest=manifest, dsn=_libpq_dsn(), tenant_count=tenants, db_revision=revision,
                      overwrite=args.overwrite, demo_password=password, restore=restore_stream, truncate=truncate,
                      set_passwords=set_passwords, row_counts=counts, artifacts_dest=Path(args.artifacts))
        except SeedError as exc:
            print(f"not loaded: {exc}")
            return 1
    finally:
        session.close()
    print(f"loaded: {manifest.row_counts.get('account', 0)} accounts, {manifest.row_counts.get('score', 0)} scores "
          f"(seed of {manifest.created}).")
    if manifest.drafts.get("llm"):
        print(f"  {manifest.drafts['llm']} drafts were written by {manifest.drafts.get('model')} on {manifest.drafts.get('date')}; "
              f"{manifest.drafts.get('template', 0)} are templates.")
    print("Sign in (workspace = northwind, globex or initech) as csm00@<workspace>.example.com; "
          + (f"password: {password}   (shown once)" if generated else "with the password you supplied"))
    return 0


def cmd_llm_check(args) -> int:
    """One real call through the configured language-model provider: does the key work, how fast, what limits."""
    from pulse.llm_check import check_llm

    s = get_settings()
    key = s.llm_api_key.get_secret_value() if s.llm_api_key else None
    r = check_llm(provider=s.llm_provider, base_url=s.llm_base_url, model=s.llm_model, api_key=key, timeout=30.0)
    print(f"provider {r.provider}, model {r.model}" + (f", endpoint {s.llm_base_url}" if s.llm_base_url else ""))
    if r.ok:
        print(f"OK in {r.latency_ms} ms; the model replied: {r.reply!r}")
        if r.limits:
            print("limits the provider reported (observed, not assumed):")
            for k, v in r.limits.items():
                print(f"  {k}: {v}")
        else:
            print("the provider sent no rate-limit headers")
        return 0
    print(f"FAILED ({r.kind}): {r.detail}")
    advice = {"no_key": "Set PULSE_LLM_API_KEY (a free Groq key is enough). See .env.example.",
              "unauthorized": "The key was rejected: check it, and that it is for this provider.",
              "rate_limited": "The free limit is used up for now; wait, or the drafts fall back to templates.",
              "timeout": "Too slow: a local model may still be loading; try again.",
              "unreachable": "Nothing answered: is the server running, and the URL right (Docker needs host.docker.internal)?"}
    if r.kind in advice:
        print(advice[r.kind])
    return 1


def cmd_send_test(args) -> int:
    """Send one clearly labelled test message through the configured mail provider and say exactly how it went.

    The one-command check that the *real* mail path works with real credentials (everything else in the test suite uses a
    fake SMTP server). Touches no database and no customer; the recipient is whoever you name -- use your own address.
    """
    from pulse.agent.transport import select_transport

    settings = get_settings()
    if not settings.smtp_host:
        print("PULSE_SMTP_HOST is not set, so there is no mail provider to test. Set PULSE_SMTP_HOST (and "
              "PULSE_SMTP_PORT, PULSE_SMTP_USER, PULSE_SMTP_PASSWORD) and try again.")
        return 2
    result = select_transport(settings).send(
        to=args.to, sender=args.sender or settings.smtp_user,
        subject="Pulse test message",
        body="This is a test message from Pulse, sent by `pulse send-test`. No customer was contacted and nothing in "
             "any account was changed. If you can read this, outbound email works from this deployment.\n",
    )
    if result.ok:
        print(f"delivered to the provider for {args.to} (message id: {result.provider_message_id or 'n/a'}). "
              "Check the inbox to confirm it arrived.")
        return 0
    advice = {"ambiguous": "Delivery could not be confirmed -- check the inbox and the provider's log before trying again.",
              "permanent": "The provider refused it and retrying will not help: fix the credentials, sender or address.",
              "transient": "A temporary failure: try again shortly."}[result.kind]
    print(f"FAILED ({result.kind}): {result.error}\n{advice}")
    return 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="pulse")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bootstrap"); b.add_argument("--feeds", default="../data/feeds")
    b.add_argument("--demo-password", default=None, help="set this password on users that have none (or PULSE_DEMO_PASSWORD)")
    b.set_defaults(fn=cmd_bootstrap)
    i = sub.add_parser("ingest"); i.add_argument("--feeds", default="../data/feeds")
    i.add_argument("--until", default=None); i.set_defaults(fn=cmd_ingest)
    st = sub.add_parser("status"); st.set_defaults(fn=cmd_status)
    c = sub.add_parser("cycle"); c.add_argument("--as-of", default=None)
    c.add_argument("--artifacts", default="../artifacts"); c.set_defaults(fn=cmd_cycle)
    bf = sub.add_parser("backfill", help="score weekly history before each tenant's newest snapshot (scores only)")
    bf.add_argument("--weeks", type=int, default=8); bf.add_argument("--artifacts", default="../artifacts")
    bf.set_defaults(fn=cmd_backfill)
    bd = sub.add_parser("bootstrap-demo"); bd.add_argument("--feeds", default="../data/feeds")
    bd.add_argument("--seed", type=int, default=20261015); bd.add_argument("--artifacts", default="../artifacts")
    bd.add_argument("--demo-password", default=None); bd.set_defaults(fn=cmd_bootstrap_demo)
    st = sub.add_parser("send-test", help="send one test message through the configured SMTP provider")
    st.add_argument("--to", required=True); st.add_argument("--sender", default=None); st.set_defaults(fn=cmd_send_test)
    sv = sub.add_parser("serve"); sv.add_argument("--artifacts", default="../artifacts")
    sv.add_argument("--simulate-present", action="store_true")
    sv.add_argument("--max-ticks", type=int, default=None); sv.set_defaults(fn=cmd_serve)
    lc = sub.add_parser("llm-check", help="one real call through the configured language-model provider")
    lc.set_defaults(fn=cmd_llm_check)
    es = sub.add_parser("export-seed", help="dump the built demo database to a seed file (data only, no secrets)")
    es.add_argument("--out", default="seed.dump"); es.add_argument("--artifacts", default="../artifacts")
    es.set_defaults(fn=cmd_export_seed)
    ls = sub.add_parser("load-seed", help="load a demo seed into a migrated database (minutes, instead of building for 10-46)")
    src = ls.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", default=None, help="a seed file; its manifest is <file>.json")
    src.add_argument("--url", default=None, help="download the seed from this URL (its manifest is <url>.json)")
    ls.add_argument("--artifacts", default="../artifacts", help="where to put the promoted model that travels with the seed")
    ls.add_argument("--overwrite", action="store_true", help="replace data already in the database (this is the reset)")
    ls.add_argument("--demo-password", default=None, help="password for every demo user (or PULSE_DEMO_PASSWORD; else one is generated)")
    ls.set_defaults(fn=cmd_load_seed)
    return ap


def main() -> int:
    args = build_parser().parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
