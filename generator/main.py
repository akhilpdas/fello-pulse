"""Generate the simulated estate.

    python3 generator/main.py --out data/feeds --seed 20261015

Writes, per tenant:

    data/feeds/<slug>/tenant.json        config and the CSM roster (admin setup)
    data/feeds/<slug>/identity_map.jsonl the incomplete join table
    data/feeds/<slug>/<source>.jsonl     one feed per connected source
    data/feeds/<slug>/_truth.jsonl       ground truth — generator tests only

``_truth.jsonl`` is underscore-prefixed and never read by anything under
``backend/``. The application has to derive labels from billing and CRM records
the way it would in production; handing it the answer would make every reported
number meaningless. The file exists so the *generator's own* tests can check
that the simulation produced what it intended, and so the evaluation can report
the planted retrospective fixtures.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from emit import EMITTERS  # noqa: E402
from pathologies import apply_lag, build_identity_map, to_feed_rows  # noqa: E402
from simulate import DATASET_END, build_accounts, simulate_account  # noqa: E402
from spec import TENANTS, TenantSpec  # noqa: E402

# The two accounts planted as analogues of the renewals the VP lost with no
# warning (clarifications A7). One is a slow support-driven decline, one a fast
# champion-departure collapse. The evaluation reports whether the backtest would
# have flagged each, and with how much lead time — which is the question that
# actually decides whether anyone adopts this.
RETRO_FIXTURES = ("slow_support_decline", "champion_collapse")


def _backfill_plan(tenant: TenantSpec) -> dict | None:
    """Globex connected Zendesk late and backfilled part of its history.

    Two consequences the system must survive: a large batch all arriving at one
    instant (the watermark must advance past it without the arrival spike being
    read as customer behaviour), and an older period for which support data
    simply does not exist (features must be absent, not zero).
    """
    if tenant.slug != "globex":
        return None
    from datetime import timedelta

    from simulate import DATASET_END as END

    batch_at = END - timedelta(days=365)
    return {
        "source": "zendesk",
        "before": _utc(batch_at),
        "batch_at": _utc(batch_at),
        "earliest_kept": _utc(END - timedelta(days=545)),
    }


def _utc(d):
    from datetime import UTC, datetime

    return datetime(d.year, d.month, d.day, 2, 0, tzinfo=UTC)


def generate_tenant(tenant: TenantSpec, seed: int, out_root: Path) -> dict:
    rng = np.random.default_rng(seed)
    out_dir = out_root / tenant.slug
    out_dir.mkdir(parents=True, exist_ok=True)

    accounts = build_accounts(tenant, rng)

    # Choose the retrospective fixtures from accounts with enough history to
    # show a decline rather than a cliff.
    retro_assign: dict[int, str] = {}
    if tenant.slug == "northwind":
        eligible = [a for a in accounts if (DATASET_END - a.signup).days > 520]
        for fixture, acct in zip(RETRO_FIXTURES, eligible[:2], strict=False):
            retro_assign[acct.index] = fixture

    backfill = _backfill_plan(tenant)
    by_source: dict[str, list] = {s: [] for s in tenant.connected_sources}
    truth: list[dict] = []
    outcome_counts: Counter = Counter()

    for acct in accounts:
        retro = retro_assign.get(acct.index)
        sim = simulate_account(acct, rng, retro=retro)
        outcome_counts[sim.outcome.kind] += 1

        raw = []
        for source in tenant.connected_sources:
            raw.extend(EMITTERS[source](sim, rng))
        delivered = apply_lag(raw, rng, backfill=backfill)
        for d in delivered:
            by_source[d.source].append(d)

        truth.append(
            {
                "account_external_ref": acct.external_ref,
                "segment": acct.segment,
                "seats": acct.seats,
                "acv_cents": acct.acv_cents,
                "signup": acct.signup.isoformat(),
                "outcome": sim.outcome.kind,
                "outcome_at": sim.outcome.at.isoformat() if sim.outcome.at else None,
                "cause": sim.outcome.cause,
                "champion_left": sim.champion_left.isoformat() if sim.champion_left else None,
                "retro_fixture": retro,
                "mean_health_final_90d": round(float(sim.health[-90:].mean()), 4),
                "shocks": [[d.isoformat(), k] for d, k in sim.shocks],
            }
        )

    counts = {}
    for source, delivered in by_source.items():
        rows = to_feed_rows(delivered, rng)
        path = out_dir / f"{source}.jsonl"
        with path.open("w") as fh:
            for row in rows:
                fh.write(json.dumps(row, separators=(",", ":")) + "\n")
        counts[source] = len(rows)

    identity = build_identity_map(accounts, tenant.connected_sources, rng)
    with (out_dir / "identity_map.jsonl").open("w") as fh:
        for row in identity:
            fh.write(json.dumps(row, separators=(",", ":")) + "\n")

    with (out_dir / "_truth.jsonl").open("w") as fh:
        for row in truth:
            fh.write(json.dumps(row, separators=(",", ":")) + "\n")

    (out_dir / "tenant.json").write_text(
        json.dumps(
            {
                "slug": tenant.slug,
                "name": tenant.name,
                "connected_sources": list(tenant.connected_sources),
                # Per-tenant policy differs on purpose, so "multiple customer
                # organisations" means more than a column on a table: capacity,
                # thresholds and allowlists all vary and all must be honoured.
                "config": _tenant_config(tenant),
                "users": [
                    {
                        "ref": f"{tenant.slug}-csm-{i:02d}",
                        "email": f"csm{i:02d}@{tenant.slug}.example.com",
                        "name": _csm_name(i),
                        "role": "operator" if i == 0 else "csm",
                    }
                    for i in range(tenant.n_csms)
                ],
            },
            indent=2,
        )
    )

    return {
        "slug": tenant.slug,
        "accounts": len(accounts),
        "events": counts,
        "events_total": sum(counts.values()),
        "identity_rows": len(identity),
        "identity_gap_pct": round(
            100 * (1 - len(identity) / (len(accounts) * len(tenant.connected_sources))), 2
        ),
        "outcomes": {str(k): v for k, v in outcome_counts.items()},
        "retro_fixtures": {accounts[i].external_ref: f for i, f in retro_assign.items()},
    }


def _tenant_config(tenant: TenantSpec) -> dict:
    """Deliberately different per tenant — see spec User Story 5."""
    if tenant.slug == "northwind":
        return {"weekly_capacity": 12, "tier_red_at": 0.20, "tier_amber_at": 0.10,
                "suppression_days": 14, "max_sends_per_cycle": 30}
    if tenant.slug == "globex":
        return {"weekly_capacity": 8, "tier_red_at": 0.20, "tier_amber_at": 0.10,
                "suppression_days": 21, "max_sends_per_cycle": 15}
    return {"weekly_capacity": 10, "tier_red_at": 0.20, "tier_amber_at": 0.10,
            "suppression_days": 14, "min_days_history": 21, "max_sends_per_cycle": 10}


FIRST = ("Dana", "Priya", "Marcus", "Chen", "Aisha", "Tomas", "Nina", "Omar", "Elena",
         "Jordan", "Kiara", "Luis", "Mei", "Samir", "Hana", "Diego", "Freya", "Noah",
         "Zara", "Ivan", "Ruth", "Kofi", "Lena", "Arjun")
LAST = ("Okafor", "Alvarez", "Nakamura", "Bennett", "Haddad", "Kowalski", "Mensah",
        "Rossi", "Lindqvist", "Patel", "Dubois", "Keller", "Osei", "Vargas", "Tanaka",
        "Moreau", "Brennan", "Silva", "Novak", "Rahman", "Fischer", "Costa", "Ivanov",
        "Sharma")


def _csm_name(i: int) -> str:
    return f"{FIRST[i % len(FIRST)]} {LAST[(i * 7) % len(LAST)]}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate the Pulse synthetic estate")
    ap.add_argument("--out", default="data/feeds")
    ap.add_argument("--seed", type=int, default=20261015)
    ap.add_argument("--only", default=None, help="restrict to one tenant slug")
    args = ap.parse_args()

    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)

    started = time.time()
    summaries = []
    for i, tenant in enumerate(TENANTS):
        if args.only and tenant.slug != args.only:
            continue
        t0 = time.time()
        # A seed derived from the master seed and the slug: each tenant is
        # independently reproducible, and adding a tenant does not shift the
        # others' data.
        tenant_seed = int(
            hashlib.sha256(f"{args.seed}:{tenant.slug}".encode()).hexdigest()[:8], 16
        )
        summary = generate_tenant(tenant, tenant_seed, out_root)
        summary["seconds"] = round(time.time() - t0, 1)
        summaries.append(summary)
        print(
            f"  {tenant.slug:10s} {summary['accounts']:5d} accounts  "
            f"{summary['events_total']:7d} events  {summary['seconds']:6.1f}s",
            flush=True,
        )

    config_hash = hashlib.sha256(
        json.dumps([t.__dict__ for t in TENANTS], sort_keys=True, default=str).encode()
    ).hexdigest()[:12]
    manifest = {
        "data_version": f"dv-{args.seed}-{config_hash}",
        "seed": args.seed,
        "dataset_end": DATASET_END.isoformat(),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tenants": summaries,
        "totals": {
            "accounts": sum(s["accounts"] for s in summaries),
            "events": sum(s["events_total"] for s in summaries),
        },
        "seconds": round(time.time() - started, 1),
    }
    (out_root / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest["totals"], indent=2))
    print(f"data_version: {manifest['data_version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
