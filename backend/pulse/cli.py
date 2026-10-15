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
import sys
import time
from datetime import datetime
from pathlib import Path

from sqlalchemy import text

from pulse.config import SystemClock
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
    for d in _tenant_dirs(feeds):
        with owner_session() as s:
            res = bootstrap_tenant(s, d)
        with tenant_session(res.tenant_id) as s:
            out = provision_tenant_data(s, res.tenant_id, d)
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


def main() -> int:
    ap = argparse.ArgumentParser(prog="pulse")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bootstrap"); b.add_argument("--feeds", default="../data/feeds")
    b.set_defaults(fn=cmd_bootstrap)
    i = sub.add_parser("ingest"); i.add_argument("--feeds", default="../data/feeds")
    i.add_argument("--until", default=None); i.set_defaults(fn=cmd_ingest)
    st = sub.add_parser("status"); st.set_defaults(fn=cmd_status)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
