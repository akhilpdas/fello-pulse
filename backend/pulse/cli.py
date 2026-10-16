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
    with owner_session() as s:
        as_of = (datetime.fromisoformat(args.as_of) if args.as_of
                 else s.execute(text("SELECT max(received_at) FROM source_event")).scalar())
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

    def newest_event():
        with owner_session() as s:
            return s.execute(text("SELECT max(received_at) FROM source_event")).scalar()

    clock = LazyOffsetClock(SystemClock(), newest_event) if args.simulate_present else SystemClock()
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


def main() -> int:
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
    bd = sub.add_parser("bootstrap-demo"); bd.add_argument("--feeds", default="../data/feeds")
    bd.add_argument("--seed", type=int, default=20261015); bd.add_argument("--artifacts", default="../artifacts")
    bd.add_argument("--demo-password", default=None); bd.set_defaults(fn=cmd_bootstrap_demo)
    st = sub.add_parser("send-test", help="send one test message through the configured SMTP provider")
    st.add_argument("--to", required=True); st.add_argument("--sender", default=None); st.set_defaults(fn=cmd_send_test)
    sv = sub.add_parser("serve"); sv.add_argument("--artifacts", default="../artifacts")
    sv.add_argument("--simulate-present", action="store_true")
    sv.add_argument("--max-ticks", type=int, default=None); sv.set_defaults(fn=cmd_serve)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
