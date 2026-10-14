"""The generated estate is adversarial, and these assertions prove it.

This suite reads the *feed files* rather than importing the generator. That is
deliberate: it validates the data contract the application consumes, so it would
still be meaningful if the feeds came from somewhere else entirely, and it keeps
the boundary between simulator and application honest.

Each assertion maps to a requirement that claims to survive the pathology. If a
pathology silently disappeared from the generator, a test here fails and the
corresponding ingestion or feature test downstream quietly stops proving
anything — which is the failure this file exists to prevent.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path

import pytest

FEEDS = Path(os.environ.get("PULSE_FEEDS", "../data/feeds")).resolve()
pytestmark = pytest.mark.skipif(
    not (FEEDS / "manifest.json").exists(),
    reason="feeds not generated; run generator/main.py",
)


def _rows(tenant: str, source: str, limit: int | None = None):
    path = FEEDS / tenant / f"{source}.jsonl"
    with path.open() as fh:
        for i, line in enumerate(fh):
            if limit is not None and i >= limit:
                return
            yield json.loads(line)


def _manifest() -> dict:
    return json.loads((FEEDS / "manifest.json").read_text())


# --------------------------------------------------------------------------- #
# Scale
# --------------------------------------------------------------------------- #


def test_estate_is_the_size_the_brief_asked_for():
    m = _manifest()
    assert m["totals"]["accounts"] == 5000
    assert 200_000 <= m["totals"]["events"] <= 500_000, m["totals"]


def test_three_tenants_with_different_shapes():
    m = _manifest()
    slugs = {t["slug"] for t in m["tenants"]}
    assert slugs == {"northwind", "globex", "initech"}


# --------------------------------------------------------------------------- #
# Arrival order — the property everything else rests on
# --------------------------------------------------------------------------- #


def test_feeds_are_ordered_by_arrival_not_by_occurrence():
    """The defining property of this dataset.

    A feed sorted by ``occurred_at`` would let a feature layer that filters on
    the wrong timestamp pass every downstream test by accident. Sorted by
    ``received_at``, out-of-order arrival is the default case.
    """
    rows = list(_rows("northwind", "zendesk", limit=6000))
    received = [datetime.fromisoformat(r["received_at"]) for r in rows]
    occurred = [datetime.fromisoformat(r["occurred_at"]) for r in rows]

    assert received == sorted(received), "feed is not in arrival order"
    assert occurred != sorted(occurred), (
        "occurrence order matches arrival order — out-of-order arrival is absent, "
        "so the point-in-time tests downstream would prove nothing"
    )


def test_arrival_is_never_before_occurrence():
    for tenant, source in (("northwind", "stripe"), ("globex", "product")):
        for r in _rows(tenant, source, limit=4000):
            assert datetime.fromisoformat(r["received_at"]) >= datetime.fromisoformat(
                r["occurred_at"]
            ), r["source_event_id"]


def test_delivery_lag_has_a_heavy_tail():
    """A tail that never produces a multi-day delay is not a tail."""
    lags = []
    for r in _rows("northwind", "zendesk", limit=20000):
        delta = datetime.fromisoformat(r["received_at"]) - datetime.fromisoformat(
            r["occurred_at"]
        )
        lags.append(delta.total_seconds() / 3600.0)
    lags.sort()
    median = lags[len(lags) // 2]
    p999 = lags[int(len(lags) * 0.999)]
    assert median < 6, f"median lag {median:.2f}h is implausibly long"
    assert p999 > 24, f"p99.9 lag only {p999:.1f}h — no heavy tail present"


# --------------------------------------------------------------------------- #
# Idempotency, drift, timezones
# --------------------------------------------------------------------------- #


def test_duplicate_deliveries_are_present():
    """FR-003 has nothing to prove if the feed contains no duplicates."""
    ids = Counter(r["source_event_id"] for r in _rows("northwind", "stripe"))
    dupes = sum(c - 1 for c in ids.values() if c > 1)
    rate = dupes / max(sum(ids.values()), 1)
    assert dupes > 0, "no duplicate deliveries in the feed"
    assert 0.001 < rate < 0.02, f"duplicate rate {rate:.4f} outside the intended band"


def test_renamed_field_appears_in_both_spellings():
    """``plan`` became ``plan_name`` partway through the history (FR-007)."""
    seen = set()
    for r in _rows("northwind", "salesforce"):
        if "plan" in r["payload"]:
            seen.add("plan")
        if "plan_name" in r["payload"]:
            seen.add("plan_name")
        if len(seen) == 2:
            break
    assert seen == {"plan", "plan_name"}, (
        f"only saw {seen} — an adapter reading one spelling would silently lose "
        "part of the history without raising anything"
    )


def test_event_type_case_drift_is_present():
    types = Counter(r["event_type"] for r in _rows("northwind", "salesforce"))
    assert types["Account.updated"] > 0 and types["Account.Updated"] > 0, types


def test_timestamps_arrive_in_mixed_utc_offsets():
    offsets = set()
    for r in _rows("northwind", "gmail", limit=3000):
        offsets.add(r["occurred_at"][-6:])
    assert len(offsets) >= 3, f"only {offsets} — no timezone normalisation to test"


# --------------------------------------------------------------------------- #
# Missing data
# --------------------------------------------------------------------------- #


def test_a_whole_tenant_is_missing_a_source():
    """Globex has no Gmail at all.

    The most valuable tenant in the dataset. Imputing zero for its email
    features would read as "every customer has gone silent" and would mark an
    entire organisation red.
    """
    assert not (FEEDS / "globex" / "gmail.jsonl").exists()
    assert (FEEDS / "northwind" / "gmail.jsonl").exists()
    cfg = json.loads((FEEDS / "globex" / "tenant.json").read_text())
    assert "gmail" not in cfg["connected_sources"]


def test_identity_map_is_incomplete():
    """An unresolved identifier must be a visible state, not a dropped record."""
    m = _manifest()
    for t in m["tenants"]:
        assert 1.0 < t["identity_gap_pct"] < 6.0, t


def test_nullable_fields_are_actually_null_sometimes():
    csat = [
        r["payload"].get("satisfaction_score")
        for r in _rows("northwind", "zendesk", limit=40000)
        if r["event_type"] == "satisfaction.rated"
    ]
    assert csat, "no CSAT records found"
    null_rate = sum(1 for c in csat if c is None) / len(csat)
    assert 0.15 < null_rate < 0.6, f"CSAT null rate {null_rate:.2f}"

    sentiments = [
        r["payload"].get("sentiment") for r in _rows("northwind", "gmail", limit=20000)
    ]
    s_null = sum(1 for s in sentiments if s is None) / len(sentiments)
    assert 0.12 < s_null < 0.35, f"sentiment null rate {s_null:.2f}"


def test_commercial_fields_are_sometimes_absent():
    """ACV and seats go missing, so the ranking must degrade rather than invent."""
    acv_null = seats_null = total = 0
    for r in _rows("northwind", "salesforce", limit=20000):
        if not r["event_type"].lower().startswith("account.updated"):
            continue
        total += 1
        acv_null += r["payload"].get("acv_cents") is None
        seats_null += r["payload"].get("seats") is None
    assert total > 100
    assert 0.02 < acv_null / total < 0.15, acv_null / total
    assert 0.03 < seats_null / total < 0.2, seats_null / total


# --------------------------------------------------------------------------- #
# Backfill
# --------------------------------------------------------------------------- #


def test_a_backfill_burst_exists():
    """Globex connected Zendesk late and backfilled.

    Many records sharing one arrival instant. The watermark must advance past
    the batch, and the arrival spike must not be read as customer behaviour.
    """
    arrivals = Counter(
        datetime.fromisoformat(r["received_at"]).isoformat()
        for r in _rows("globex", "zendesk")
    )
    biggest = arrivals.most_common(1)[0]
    assert biggest[1] > 200, f"largest simultaneous arrival was only {biggest[1]} records"


# --------------------------------------------------------------------------- #
# Signal, seasonality, cold start
# --------------------------------------------------------------------------- #


def test_weekend_usage_is_visibly_lower_than_weekday():
    """Seasonality strong enough to fool a trailing-window feature.

    This is why every week-over-week feature compares aligned whole weeks. A
    naive trailing 7-day window spanning a weekend reports a decline for
    perfectly healthy accounts, every Monday.
    """
    weekday = weekend = 0
    wd_n = we_n = 0
    for r in _rows("northwind", "product", limit=4000):
        for day in r["payload"].get("daily", []):
            d = datetime.fromisoformat(day["date"])
            if d.weekday() >= 5:
                weekend += day["active_users"]
                we_n += 1
            else:
                weekday += day["active_users"]
                wd_n += 1
    assert wd_n and we_n
    ratio = (weekend / we_n) / max(weekday / wd_n, 1e-9)
    assert ratio < 0.5, f"weekend/weekday activity ratio {ratio:.2f} — seasonality too weak"


def _truth(tenant: str) -> list[dict]:
    with (FEEDS / tenant / "_truth.jsonl").open() as fh:
        return [json.loads(line) for line in fh]


def test_cold_start_accounts_exist():
    rows = _truth("northwind")
    from datetime import date

    end = date.fromisoformat(_manifest()["dataset_end"])
    ages = [(end - date.fromisoformat(r["signup"])).days for r in rows]
    thin = sum(1 for a in ages if a < 30)
    assert thin / len(ages) > 0.02, (
        f"only {thin}/{len(ages)} accounts under 30 days — the abstain path is untested"
    )


def test_outcome_rate_is_plausible():
    """Neither so rare the model cannot learn, nor so common it is not churn."""
    for tenant in ("northwind", "globex"):
        rows = _truth(tenant)
        lost = sum(1 for r in rows if r["outcome"])
        rate = lost / len(rows)
        assert 0.05 < rate < 0.35, f"{tenant} outcome rate {rate:.3f}"


def test_a_meaningful_share_of_loss_is_unpredictable():
    """Irreducible noise, deliberately.

    Budget cuts and acquisitions leave no trace in behavioural data. Without
    them the label would be a near-deterministic function of the latent state,
    the model would score implausibly well, and nobody should believe it.
    """
    rows = _truth("northwind")
    lost = [r for r in rows if r["outcome"]]
    exogenous = sum(1 for r in lost if r["cause"] == "exogenous")
    share = exogenous / max(len(lost), 1)
    assert 0.05 < share < 0.4, f"exogenous share of loss {share:.3f}"


def test_health_separates_churned_from_retained():
    """There must be learnable signal — but not a clean threshold."""
    rows = _truth("northwind")
    churned = [r["mean_health_final_90d"] for r in rows if r["outcome"] == "churn"]
    kept = [r["mean_health_final_90d"] for r in rows if not r["outcome"]]
    assert churned and kept
    mc, mk = sum(churned) / len(churned), sum(kept) / len(kept)
    assert mk - mc > 0.05, f"no separation: churned {mc:.3f} vs retained {mk:.3f}"

    # Overlap is required. If the healthiest churner were below the unhealthiest
    # retained account, the label would be a threshold and the task trivial.
    assert max(churned) > sorted(kept)[len(kept) // 10], (
        "no overlap between churned and retained health — the problem is too easy"
    )


def test_retrospective_fixtures_are_planted():
    """The analogues of the two renewals lost with no warning (A7)."""
    rows = _truth("northwind")
    fixtures = {r["retro_fixture"] for r in rows if r["retro_fixture"]}
    assert fixtures == {"slow_support_decline", "champion_collapse"}, fixtures
    for r in rows:
        if r["retro_fixture"]:
            assert r["outcome"] == "churn", (r["retro_fixture"], r["outcome"])


def test_shock_types_all_occur():
    seen: Counter = Counter()
    for r in _truth("northwind"):
        for _, kind in r["shocks"]:
            seen[kind] += 1
    expected = {
        "champion_departure", "support_failure", "competitive_eval",
        "qbr_success", "price_increase", "sponsor_change",
    }
    assert expected <= set(seen), f"missing shock types: {expected - set(seen)}"
