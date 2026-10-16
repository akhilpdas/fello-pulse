"""Versioned model artefacts, model cards, and the promotion gate (FR-020).

A candidate is promoted only by beating the heuristic baseline at the
operating point the business uses -- precision@capacity, not an aggregate AUC
a candidate could win on while losing where it matters.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import joblib

from pulse.ml.train import TrainedModel


def decide_promotion(
    *, candidate_precision_at_capacity: float, baseline_precision_at_capacity: float, min_lift: float
) -> tuple[bool, str]:
    lift = candidate_precision_at_capacity - baseline_precision_at_capacity
    if lift >= min_lift:
        return True, (
            f"beat heuristic baseline: {candidate_precision_at_capacity:.3f} vs "
            f"{baseline_precision_at_capacity:.3f} (lift {lift:+.3f} >= required {min_lift:.3f})"
        )
    return False, (
        f"did not beat heuristic baseline by enough: {candidate_precision_at_capacity:.3f} vs "
        f"{baseline_precision_at_capacity:.3f} (lift {lift:+.3f} < required {min_lift:.3f})"
    )


@dataclass(frozen=True, slots=True)
class ModelCard:
    version: str
    algorithm: str
    feature_set_version: str
    feature_names: list[str]
    trained_at: str
    train_window_start: str
    train_window_end: str
    horizon_days: int
    seed: int
    data_version: str
    metrics: dict
    artifact_path: str
    promoted: bool
    promotion_note: str | None


def save_artifact(model: TrainedModel, directory: Path, version: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{version}.pkl"
    joblib.dump(model, path)
    return path


def load_artifact(path: Path) -> TrainedModel:
    return joblib.load(path)


def write_model_card(card: ModelCard, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{card.version}.json"
    path.write_text(json.dumps(asdict(card), indent=2, default=str))
    return path


def make_version(data_version: str, seed: int) -> str:
    return f"m-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{data_version[-8:]}-s{seed}"


def load_promoted_model(directory: Path) -> tuple[TrainedModel, str]:
    """The newest promoted artefact in ``directory`` -- what serving uses. A
    candidate that lost to the baseline has a card but is never returned."""
    cards = [json.loads(p.read_text()) for p in directory.glob("*.json")] if directory.exists() else []
    promoted = [c for c in cards if c.get("promoted")]
    if not promoted:
        raise LookupError(f"no promoted model in {directory}; run `python3 -m pulse.ml.pipeline`")
    newest = max(promoted, key=lambda c: c["trained_at"])
    return load_artifact(Path(newest["artifact_path"])), newest["version"]
