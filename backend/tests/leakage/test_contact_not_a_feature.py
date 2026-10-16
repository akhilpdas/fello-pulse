"""T253 GUARD (constitution I; plan R-8): the customer contact is data for *writing to* an account, never for
*scoring* it. Nothing under ``features/``, ``ml/`` or ``scoring/`` may reference the contact columns.

Passes on the first run -- it records a fact and protects it; it is not test-first.
"""

from __future__ import annotations

from pathlib import Path

PULSE = Path(__file__).resolve().parents[2] / "pulse"


def test_no_feature_model_or_scoring_code_touches_the_contact_columns():
    offenders = []
    for package in ("features", "ml", "scoring"):
        for path in (PULSE / package).rglob("*.py"):
            text = path.read_text()
            if "contact_email" in text or "contact_name" in text or "primary_contact" in text:
                offenders.append(str(path.relative_to(PULSE)))
    assert not offenders, f"contact data reachable from the scoring path: {offenders}"
