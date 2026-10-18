"""Red/amber cut-offs must sit on the scale the model actually outputs (clarifications B-32, B-33).

The model's probabilities are calibrated to a base rate of a few percent: an average account scores ~4%. Cut-offs of
0.32-0.38, chosen before any model existed, marked ~0.3% of accounts red and left whole workspaces with none, so the
queue looked like the product saw nothing. Cut-offs are now stated in the model's own terms -- amber is a 10% chance of a
loss within 90 days, red 20% (roughly 2.5x and 5x an average account) -- and this guards against drifting back to
numbers the model can barely reach.

Reads the feed's ``tenant.json`` (the data contract), like the rest of the generator suite.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

FEEDS = Path(os.environ.get("PULSE_FEEDS", "../data/feeds")).resolve()
pytestmark = pytest.mark.skipif(not (FEEDS / "manifest.json").exists(), reason="feeds not generated")

TENANTS = ["northwind", "globex", "initech"]


@pytest.mark.parametrize("slug", TENANTS)
def test_cutoffs_are_reachable_by_a_calibrated_probability(slug):
    cfg = json.loads((FEEDS / slug / "tenant.json").read_text())["config"]
    assert cfg["tier_red_at"] <= 0.25, "the model rarely scores above this, so a tenant would never see a red account"
    assert 0 < cfg["tier_amber_at"] < cfg["tier_red_at"]
