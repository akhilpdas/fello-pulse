"""``docs/DEMO_GUIDE.md`` is what someone uses to run and present the system, so its load-bearing facts must not drift from
the code: the sign-in emails, how the password is set, which language model is used (read from the settings default, not
retyped by hand), the real-versus-stand-in table, and that the README points to it.

Names the production change that makes it fail: the guide does not exist yet.
"""

from __future__ import annotations

import re
from pathlib import Path

from pulse.config import Settings

ROOT = Path(__file__).resolve().parents[2].parent
GUIDE = ROOT / "docs" / "DEMO_GUIDE.md"


def _text() -> str:
    return GUIDE.read_text()


def test_the_guide_gives_every_workspace_and_its_operator_and_csm_sign_in():
    t = _text()
    for ws in ("northwind", "globex", "initech"):
        assert f"csm00@{ws}.example.com" in t and f"csm01@{ws}.example.com" in t, ws


def test_it_says_how_the_password_is_set_found_and_chosen_without_putting_it_in_git():
    t = _text()
    assert "PULSE_DEMO_PASSWORD" in t and ".demo-credentials.pulse" in t and "run_all.sh" in t
    assert "bootstrap-demo" in t  # the container route prints it too
    assert "git-ignored" in t.replace("gitignored", "git-ignored")


def test_it_names_the_language_model_exactly_as_the_code_defaults_it_and_says_what_it_is_for():
    t = _text()
    assert Settings(_env_file=None).llm_model in t, "the guide's model id has drifted from the settings default"
    assert "PULSE_LLM_MODEL" in t and "PULSE_LLM_API_KEY" in t and "PULSE_LLM_ENABLED" in t
    low = t.lower()
    assert "only writes" in low or "only to write" in low or "never ranks" in low  # the boundary, stated
    assert "gradient" in low and "shap" in low  # and what *does* rank


def test_it_is_honest_about_what_is_real_and_what_is_a_stand_in():
    t = _text().lower()
    assert "send-test" in t
    assert re.search(r"no real (email|message)", t) and re.search(r"no real (model|llm|language-model)", t)


def test_it_has_a_guided_tour_and_the_readme_points_to_it():
    t = _text()
    assert "Guided tour" in t and "Troubleshooting" in t
    assert "docs/DEMO_GUIDE.md" in (ROOT / "README.md").read_text()
    assert "DEMO_GUIDE" in (ROOT / "HANDOFF.md").read_text()
