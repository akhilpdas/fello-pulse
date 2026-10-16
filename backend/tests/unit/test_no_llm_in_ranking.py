"""FR-013 (constitution Principle II): no LLM module is reachable from the
ranking or scoring path. Checked in a fresh subprocess, not the current
interpreter -- this test file, and everything else pytest has already
imported this session, must not contaminate what we're actually proving:
that importing *only* the ranking/scoring modules never pulls in anything
LLM-related.
"""

from __future__ import annotations

import subprocess
import sys

_PROBE = (
    "import sys\n"
    "import pulse.domain.ranking\n"
    "import pulse.scoring.service\n"
    "hits = [m for m in sys.modules if 'llm' in m.lower() or 'anthropic' in m.lower()]\n"
    "print(repr(hits))\n"
)


def test_ranking_and_scoring_import_nothing_llm_related():
    result = subprocess.run(
        [sys.executable, "-c", _PROBE], capture_output=True, text=True, check=True,
    )
    hits = eval(result.stdout.strip())  # noqa: S307 - trusted, our own probe's output
    assert hits == [], f"LLM-related modules reachable from the ranking path: {hits}"


def test_ranking_module_source_contains_no_llm_import():
    """Static check too, for the case a future refactor imports an LLM module
    only inside a branch that this process never executes."""
    import ast

    import pulse.domain.ranking as ranking_mod
    import pulse.scoring.service as scoring_mod

    for mod in (ranking_mod, scoring_mod):
        with open(mod.__file__) as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [n.name for n in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                assert "llm" not in name.lower(), f"{mod.__name__} imports {name}"


# T285 GUARD (002 / FR-025): the new drafting modules did not widen the boundary. Importing the cycle, the
# drafter, the grounding facts, feature computation, training and scoring loads nothing LLM-related -- the model
# client is imported only inside ``_make_llm``, only when a key is configured. Passes on first run: it protects
# a fact, it is not test-first.
_WIDER_PROBE = (
    "import sys\n"
    "import pulse.agent.cycle, pulse.agent.drafter, pulse.agent.grounding, pulse.agent.delivery\n"
    "import pulse.features.compute, pulse.ml.pipeline, pulse.ml.train, pulse.scoring.service\n"
    "print(repr([m for m in sys.modules if 'llm' in m.lower() or 'anthropic' in m.lower()]))\n"
)


def test_the_drafting_cycle_and_training_paths_load_no_llm_module_until_a_key_is_configured():
    result = subprocess.run([sys.executable, "-c", _WIDER_PROBE], capture_output=True, text=True, check=True)
    assert eval(result.stdout.strip()) == []  # noqa: S307 - our own probe's output


def test_no_feature_ml_or_scoring_source_mentions_the_model_client():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "pulse"
    offenders = [str(p.relative_to(root)) for pkg in ("features", "ml", "scoring", "domain")
                 for p in (root / pkg).rglob("*.py") if "llm_drafter" in p.read_text() or "anthropic" in p.read_text()]
    assert not offenders, offenders
