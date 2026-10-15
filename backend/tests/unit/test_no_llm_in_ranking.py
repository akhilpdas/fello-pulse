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
