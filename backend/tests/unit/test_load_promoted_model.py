"""The serving side loads the newest *promoted* artefact from the card directory;
an unpromoted candidate (it lost to the baseline) is never served."""

from __future__ import annotations

import pytest

from pulse.ml.registry import ModelCard, load_promoted_model, save_artifact, write_model_card
from tests.integration._agent_fixtures import toy_support_model


def _card(version: str, promoted: bool, trained_at: str, path) -> ModelCard:
    return ModelCard(version=version, algorithm="HGB", feature_set_version="fs-1", feature_names=[],
                     trained_at=trained_at, train_window_start="a", train_window_end="b", horizon_days=90,
                     seed=1, data_version="dv", metrics={}, artifact_path=str(path), promoted=promoted,
                     promotion_note=None)


def test_loads_the_newest_promoted_model_and_ignores_unpromoted(tmp_path):
    for version, promoted, when in [("m-old", True, "2026-09-01"), ("m-new", True, "2026-10-01"),
                                    ("m-cand", False, "2026-10-09")]:
        path = save_artifact(toy_support_model(3), tmp_path, version)
        write_model_card(_card(version, promoted, when, path), tmp_path)
    model, version = load_promoted_model(tmp_path)
    assert version == "m-new"
    assert hasattr(model, "feature_names")


def test_raises_a_clear_error_when_nothing_is_promoted(tmp_path):
    path = save_artifact(toy_support_model(3), tmp_path, "m-cand")
    write_model_card(_card("m-cand", False, "2026-10-01", path), tmp_path)
    with pytest.raises(LookupError, match="no promoted model"):
        load_promoted_model(tmp_path)
