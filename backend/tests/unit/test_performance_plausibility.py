"""T045: a test-block AUC above settings.auc_plausibility_ceiling (0.95) is
evidence of a broken harness, not a good model, and must fail the build."""

from __future__ import annotations

import pytest

from pulse.config import get_settings, reset_settings
from pulse.ml.evaluate import ImplausiblePerformance, check_plausibility


def test_auc_below_ceiling_is_accepted():
    check_plausibility(0.84, ceiling=0.95)  # must not raise


def test_auc_above_ceiling_raises():
    with pytest.raises(ImplausiblePerformance):
        check_plausibility(0.99, ceiling=0.95)


def test_the_configured_ceiling_is_what_gates_training():
    reset_settings()
    settings = get_settings()
    assert settings.auc_plausibility_ceiling == 0.95
    with pytest.raises(ImplausiblePerformance):
        check_plausibility(0.97, ceiling=settings.auc_plausibility_ceiling)
