"""The optional LLM path behind ``drafter.draft()``'s interface (constitution
Principle II). Deliberately never imported at module scope by anything else
in the codebase -- ``drafter.draft()`` imports this lazily, only when
``llm_enabled`` and an API key are both configured -- so this module, and any
LLM SDK it would depend on, is unreachable from the scoring and ranking path
by construction, not by convention (FR-013).

This deliverable ships no real network-calling client: ``llm_enabled``
defaults to false and no key is configured, so this path is exercised by
nothing in the test suite or any demo script. What matters structurally is
the boundary -- an LLM may only ever produce prose from evidence already
computed, and the exact same ``Draft`` shape and grounding validation applies
to its output as to the template path.
"""

from __future__ import annotations

from pulse.agent.drafter import Draft


def draft_with_llm(play_key: str, *, account_name: str, csm_name: str, api_key: str) -> Draft:
    raise NotImplementedError(
        "no LLM client is wired into this deliverable; llm_enabled must stay false"
    )
