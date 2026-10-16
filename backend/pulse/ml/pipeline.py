"""End-to-end training orchestration: build the full cross-tenant panel, split,
fit, calibrate, evaluate against baselines, gate promotion, save the artefact.

Cross-tenant by design (clarifications B-7: one shared model). Runs under
``elevated_session`` -- the explicitly named, reviewed path for work that
legitimately crosses tenant boundaries (constitution Principle IV).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text

from pulse.config import Clock, SystemClock, get_settings
from pulse.db.session import elevated_session
from pulse.features.repository import (
    identity_unresolved_for_account,
    load_account_feature_input,
    load_events,
)
from pulse.ml.evaluate import (
    brier,
    captured_acv_at_capacity,
    check_plausibility,
    heuristic_baseline_score,
    leave_one_tenant_out,
    per_tenant_metrics,
    pr_auc,
    precision_at_capacity,
    reliability_curve,
    roc_auc,
    trivial_baseline,
)
from pulse.ml.panel import PanelRow, build_account_panel
from pulse.ml.registry import (
    ModelCard,
    decide_promotion,
    make_version,
    save_artifact,
    write_model_card,
)
from pulse.ml.train import Split, predict_proba, time_based_split, train


def trainable_tenants(session) -> list[tuple]:
    """Tenants whose data arrived through ingestion (they have a watermark).
    Tenants seeded directly -- test fixtures, consoles -- are excluded so they
    can never leak into the production model or its per-tenant report."""
    return list(session.execute(
        text("SELECT id, slug FROM tenant WHERE EXISTS"
             " (SELECT 1 FROM ingestion_watermark w WHERE w.tenant_id = tenant.id)"
             " ORDER BY slug")
    ).all())


@dataclass(frozen=True, slots=True)
class TenantBlocks:
    """The tenant of every row in each split block, aligned row-for-row with ``Split``."""

    train: list[str]
    val: list[str]
    calib: list[str]
    test: list[str]


def split_with_tenants(rows: list[PanelRow], tenants: list[str], **fractions) -> tuple[Split, TenantBlocks]:
    """``time_based_split`` that carries each row's tenant through the sort. Pairing the
    time-sorted test block with the tenant-ordered slug list (as this module once did) attributes
    rows to the wrong tenants."""
    order = sorted(range(len(rows)), key=lambda i: rows[i].as_of)
    split = time_based_split([rows[i] for i in order], **fractions)
    ordered_tenants = [tenants[i] for i in order]
    a, b, c = len(split.train), len(split.val), len(split.calib)
    return split, TenantBlocks(
        train=ordered_tenants[:a], val=ordered_tenants[a:a + b],
        calib=ordered_tenants[a + b:a + b + c], test=ordered_tenants[a + b + c:],
    )


def build_full_panel(clock: Clock, horizon_days: int) -> tuple[list[PanelRow], list[str]]:
    """Every tenant, every account. Returns the panel plus a parallel list of
    tenant slugs -- PanelRow itself stays tenant-agnostic and pure."""
    dataset_end = clock.now()
    rows: list[PanelRow] = []
    tenant_slugs: list[str] = []

    with elevated_session() as s:
        tenants = trainable_tenants(s)
        for tenant_id, slug in tenants:
            cfg = s.execute(
                text(
                    "SELECT connected_sources, contraction_threshold FROM tenant_config"
                    " WHERE tenant_id = :t"
                ),
                {"t": tenant_id},
            ).one()
            connected = frozenset(cfg[0])
            threshold = float(cfg[1])
            account_ids = [r[0] for r in s.execute(
                text("SELECT id FROM account WHERE tenant_id = :t"), {"t": tenant_id}
            ).all()]

            for account_id in account_ids:
                events = load_events(s, account_id)
                if not events:
                    continue
                account_input = load_account_feature_input(s, account_id)
                unresolved = identity_unresolved_for_account(s, account_id)
                account_rows = build_account_panel(
                    account_id=account_id, connected_sources=connected,
                    account_input=account_input, events=events,
                    contraction_threshold=threshold, horizon_days=horizon_days,
                    dataset_end=dataset_end, identity_unresolved=unresolved,
                )
                rows.extend(account_rows)
                tenant_slugs.extend([slug] * len(account_rows))

    return rows, tenant_slugs


def run(clock: Clock | None = None, out_dir: Path = Path("../artifacts")) -> dict:
    clock = clock or SystemClock()
    settings = get_settings()
    t0 = time.time()

    rows, tenant_slugs = build_full_panel(clock, settings.horizon_days)
    print(f"panel: {len(rows)} rows across {len(set(tenant_slugs))} tenants "
          f"({time.time() - t0:.1f}s)")
    positive_rate = sum(1 for r in rows if r.label) / len(rows)
    print(f"positive rate: {positive_rate:.4f}")

    split, tenant_blocks = split_with_tenants(rows, tenant_slugs)
    model = train(split, seed=settings.model_seed)
    print(f"fitted on {len(split.train)} rows, {len(model.feature_names)} features "
          f"({len(model.dropped_features)} dropped as all-missing in train)")

    y_test = [bool(r.label) for r in split.test]
    x_test_values = [r.feature_values for r in split.test]
    proba = predict_proba(model, x_test_values)

    capacity = 100  # a representative weekly-queue-sized slice across the estate
    value_at_risk = [(r.feature_values.get("acv_cents") or 0) for r in split.test]

    heuristic_scores = [heuristic_baseline_score(v) for v in x_test_values]
    trivial_scores = trivial_baseline(y_test, len(y_test))

    metrics = {
        "n_test": len(split.test),
        "positive_rate_test": float(sum(y_test) / len(y_test)),
        "roc_auc": roc_auc(y_test, proba),
        "pr_auc": pr_auc(y_test, proba),
        "brier": brier(y_test, proba),
        "operating_point": {"capacity": capacity},
        "reliability": reliability_curve(y_test, proba),
        "precision_at_capacity": precision_at_capacity(y_test, proba, capacity),
        "captured_acv_at_capacity": captured_acv_at_capacity(y_test, proba, value_at_risk, capacity),
        "baseline_trivial": {
            "roc_auc": roc_auc(y_test, trivial_scores),
            "precision_at_capacity": precision_at_capacity(y_test, trivial_scores, capacity),
        },
        "baseline_heuristic": {
            "roc_auc": roc_auc(y_test, heuristic_scores),
            "precision_at_capacity": precision_at_capacity(y_test, heuristic_scores, capacity),
        },
    }
    for tm in per_tenant_metrics(tenant_blocks.test, y_test, proba):
        metrics.setdefault("per_tenant", {})[tm.tenant] = {
            "n": tm.n, "positive_rate": tm.positive_rate, "pr_auc": tm.pr_auc, "roc_auc": tm.roc_auc,
        }

    # Cold start (001/FR-018): fit on the other tenants before the test period, score this one after it.
    t_loto = time.time()
    metrics["leave_one_tenant_out"] = leave_one_tenant_out(
        [*split.train, *split.val, *split.calib, *split.test],
        [*tenant_blocks.train, *tenant_blocks.val, *tenant_blocks.calib, *tenant_blocks.test],
        cutoff=split.test[0].as_of,
        train_fn=lambda r: train(time_based_split(r), seed=settings.model_seed),
        predict_fn=lambda m, held: predict_proba(m, [x.feature_values for x in held]),
        capacity=capacity,
    )
    metrics["leave_one_tenant_out_seconds"] = round(time.time() - t_loto, 1)

    try:
        check_plausibility(metrics["roc_auc"], settings.auc_plausibility_ceiling)
        metrics["plausibility_check"] = "passed"
    except Exception as exc:  # noqa: BLE001 - reported, not fatal to the artefact
        metrics["plausibility_check"] = f"FAILED: {exc}"

    promoted, note = decide_promotion(
        candidate_precision_at_capacity=metrics["precision_at_capacity"],
        baseline_precision_at_capacity=metrics["baseline_heuristic"]["precision_at_capacity"],
        min_lift=settings.promotion_min_lift,
    )
    metrics["promotion_note"] = note

    version = make_version(data_version="dv-local", seed=settings.model_seed)
    artifact_path = save_artifact(model, out_dir, version)
    card = ModelCard(
        version=version, algorithm="HistGradientBoostingClassifier",
        feature_set_version=settings.feature_set_version, feature_names=model.feature_names,
        trained_at=clock.now().isoformat(),
        train_window_start=split.train[0].as_of.isoformat(),
        train_window_end=split.train[-1].as_of.isoformat(),
        horizon_days=settings.horizon_days, seed=settings.model_seed, data_version="dv-local",
        metrics=metrics, artifact_path=str(artifact_path), promoted=promoted, promotion_note=note,
    )
    card_path = write_model_card(card, out_dir)

    print(json.dumps(metrics, indent=2, default=str))
    print(f"promoted={promoted}: {note}")
    print(f"artifact={artifact_path} card={card_path}")
    print(f"total time: {time.time() - t0:.1f}s")
    return metrics


if __name__ == "__main__":
    run()
