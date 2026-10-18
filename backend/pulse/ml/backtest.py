"""Rolling-origin backtest: out-of-sample scores for a long evaluation window (clarifications B-33).

``pipeline.run`` fits on the early rows and tests on the latest block, so only a few weeks carry honest scores -- too
few to see how early a loss was foreseen. Here the evaluation window is cut into consecutive chunks and each chunk is
scored by a model refitted on the rows whose outcome had already played out when the chunk began (``as_of`` at least
``horizon_days`` before it), exactly the situation a deployed model is in. Fitting and predicting are injected so the
time logic is testable without fitting anything.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

import numpy as np

from pulse.ml.evaluate import lead_time_report, roc_auc
from pulse.ml.panel import PanelRow


def rolling_origin_scores(
    rows: list[PanelRow], *, horizon_days: int, eval_weeks: int, n_folds: int,
    train_fn: Callable[[list[PanelRow]], object], predict_fn: Callable[[object, list[PanelRow]], list[float]],
) -> tuple[list[PanelRow], list[float], list[int]]:
    """Score the last ``eval_weeks`` weeks of ``rows`` in ``n_folds`` consecutive chunks; returns the scored rows,
    their scores and the fold each belongs to, aligned."""
    weeks = sorted({r.as_of for r in rows})
    window = weeks[-eval_weeks:]
    size, extra = divmod(len(window), n_folds)
    scored: list[PanelRow] = []
    scores: list[float] = []
    folds: list[int] = []
    start = 0
    for fold in range(n_folds):
        chunk_weeks = window[start:start + size + (1 if fold < extra else 0)]
        start += len(chunk_weeks)
        chunk_start = chunk_weeks[0]
        known = [r for r in rows if r.as_of <= chunk_start - timedelta(days=horizon_days)]
        if not known:
            raise ValueError(f"no history to train on before {chunk_start.date()} once the {horizon_days}-day "
                             "horizon is respected; shorten the evaluation window")
        model = train_fn(known)
        chunk = [r for r in rows if chunk_weeks[0] <= r.as_of <= chunk_weeks[-1]]
        scored.extend(chunk)
        scores.extend(predict_fn(model, chunk))
        folds.extend([fold] * len(chunk))
    return scored, scores, folds


def backtest_report(
    rows: list[PanelRow], *, horizon_days: int, eval_weeks: int, n_folds: int, thresholds: dict[str, float],
    train_fn: Callable[[list[PanelRow]], object], predict_fn: Callable[[object, list[PanelRow]], list[float]],
) -> dict:
    """What the rolling backtest says: ROC-AUC per fold (each fold is scored by its own model, so folds are not
    pooled -- calibrators differ and pooling would mix their scales) and lead time at each named threshold."""
    scored, scores, folds = rolling_origin_scores(
        rows, horizon_days=horizon_days, eval_weeks=eval_weeks, n_folds=n_folds, train_fn=train_fn, predict_fn=predict_fn)
    aucs: list[float | None] = []
    for f in range(n_folds):
        y = [bool(r.label) for r, k in zip(scored, folds, strict=True) if k == f]
        sc = [s for s, k in zip(scores, folds, strict=True) if k == f]
        aucs.append(roc_auc(y, sc) if any(y) and not all(y) else None)
    known = [a for a in aucs if a is not None]
    return {
        "method": f"rolling origin: {n_folds} folds over the last {eval_weeks} weeks, each scored by a model fitted only "
                  f"on rows whose {horizon_days}-day outcome was already known when the fold began",
        "eval_weeks": eval_weeks, "n_folds": n_folds, "n_scored": len(scored),
        "auc_by_fold": aucs, "auc_mean": float(np.mean(known)) if known else None,
        "lead_time": {name: lead_time_report(scored, scores, threshold=t) for name, t in thresholds.items()},
    }
