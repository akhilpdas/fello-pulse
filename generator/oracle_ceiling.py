"""How good could any model be on this data? An oracle that is handed each account's hidden health.

    python3 generator/oracle_ceiling.py          # needs the demo database built (run_all.sh); ~3 minutes

The generator draws every loss from a latent health path (``simulate.py``). Replaying it with the same seeds gives that
path back, so we can score each weekly panel row with the formula the generator itself uses -- renewal-day churn from
the mean health over the 90 days before, a health-dependent contraction hazard, and exogenous churn -- using the health
known *at* the row's date, which no real system could see. That is the best a model could do with perfect knowledge of
how healthy every account is, and the yardstick for the model's rolling out-of-sample numbers (clarifications B-33).
Reported: ROC-AUC per fold, and lead time at the alert rates the model's amber and red lines produce.

Analysis tooling only: nothing in ``backend/pulse`` imports this, and it reads the latent path, which the product never sees.
"""

from __future__ import annotations

import hashlib
import math
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "generator"))
sys.path.insert(0, str(ROOT / "backend"))

import main as gen  # noqa: E402
from simulate import CHURN_PIVOT, CHURN_SLOPE, CONTRACTION_ANNUAL_RATE, EXOGENOUS_ANNUAL_CHURN, SEGMENT_BASE_CHURN  # noqa: E402
from spec import TENANTS  # noqa: E402
from sqlalchemy import text  # noqa: E402

from pulse.config import SystemClock, get_settings  # noqa: E402
from pulse.db.session import elevated_session  # noqa: E402
from pulse.ml.backtest import rolling_origin_scores  # noqa: E402
from pulse.ml.evaluate import lead_time_report, roc_auc  # noqa: E402
from pulse.ml.pipeline import BACKTEST_FOLDS, BACKTEST_WEEKS, build_full_panel, lowest_tier_cutoffs, trainable_tenants  # noqa: E402
from pulse.ml.train import predict_proba, time_based_split, train  # noqa: E402


def replay_latent_health(seed: int = 20261015) -> dict[str, dict]:
    """account external_ref -> start date, daily health, segment, by replaying the generator in a scratch directory."""
    import tempfile

    out: dict[str, dict] = {}
    original = gen.simulate_account

    def recording(acct, rng, retro=None):
        sim = original(acct, rng, retro=retro)
        out[acct.external_ref] = {"start": sim.dates[0], "health": sim.health, "segment": acct.segment}
        return sim

    gen.simulate_account = recording
    try:
        with tempfile.TemporaryDirectory() as tmp:
            for t in TENANTS:
                tenant_seed = int(hashlib.sha256(f"{seed}:{t.slug}".encode()).hexdigest()[:8], 16)
                gen.generate_tenant(t, tenant_seed, Path(tmp))
    finally:
        gen.simulate_account = original
    return out


def oracle_probability(latent: dict, as_of) -> float:
    """P(a loss within 90 days) under the generator's own rules, from the health known at ``as_of``."""
    sigmoid = lambda x: 1 / (1 + math.exp(-x))  # noqa: E731
    start, health = latent["start"], latent["health"]
    now = (as_of.date() - start).days

    def mean_before(idx: int, days: int) -> float:
        lo = max(0, idx - days)
        return float(health[lo:idx].mean()) if idx > lo else float(health[0])

    base = SEGMENT_BASE_CHURN[latent["segment"]]
    survive = 1.0
    for k in (1, 2, 3):
        days_to_anniversary = (start + timedelta(days=365 * k) - as_of.date()).days
        if 0 < days_to_anniversary <= 90:
            hbar = mean_before(now + 1, 90)
            survive *= 1 - sigmoid(CHURN_SLOPE * (CHURN_PIVOT - hbar) + math.log(base / (1 - base)))
    hazard = (CONTRACTION_ANNUAL_RATE / 365) * (1 + 3.2 * max(0.0, 0.6 - mean_before(now + 1, 60)))
    survive *= (1 - hazard) ** 90 * (1 - EXOGENOUS_ANNUAL_CHURN / 365) ** 90
    return 1 - survive


def main() -> None:
    settings = get_settings()
    rows, _ = build_full_panel(SystemClock(), settings.horizon_days)
    latent = replay_latent_health()
    with elevated_session() as s:
        ref = {r[0]: r[1] for r in s.execute(text("SELECT id, external_ref FROM account")).all()}
    scored, scores, folds = rolling_origin_scores(
        rows, horizon_days=settings.horizon_days, eval_weeks=BACKTEST_WEEKS, n_folds=BACKTEST_FOLDS,
        train_fn=lambda r: train(time_based_split(r), seed=settings.model_seed),
        predict_fn=lambda m, r: list(predict_proba(m, [x.feature_values for x in r])))
    oracle = [oracle_probability(latent[ref[r.account_id]], r.as_of) for r in scored]
    y = [bool(r.label) for r in scored]
    print("ROC-AUC per out-of-sample fold          model   oracle")
    for f in range(BACKTEST_FOLDS):
        idx = [i for i, k in enumerate(folds) if k == f]
        print(f"  fold {f}                               {roc_auc([y[i] for i in idx], [scores[i] for i in idx]):.3f}   "
              f"{roc_auc([y[i] for i in idx], [oracle[i] for i in idx]):.3f}")
    with elevated_session() as s:
        cutoffs = lowest_tier_cutoffs(s, [tid for tid, _ in trainable_tenants(s)])
    for name, threshold in cutoffs.items():
        mine = lead_time_report(scored, scores, threshold=threshold)
        cut = float(np.quantile(oracle, 1 - mine["alert_rate"]))
        theirs = lead_time_report(scored, oracle, threshold=cut)
        print(f"{name} line ({threshold}), alert rate {mine['alert_rate']:.1%}: recall model {mine['recall']:.1%} vs oracle {theirs['recall']:.1%}; "
              f"median lead model {mine['median_days']:.0f}d vs oracle {theirs['median_days']:.0f}d")


if __name__ == "__main__":
    main()
