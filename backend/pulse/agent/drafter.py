"""Drafts customer-facing language from evidence already computed
(constitution Principle II: a language model only writes, it never scores,
ranks, tiers, filters or re-orders, and nothing here is ever an input back
into a feature or a score).

Deterministic templates are the default and the only thing required for
correctness. An optional LLM sits behind the exact same ``draft()`` interface
and is imported lazily, only when ``llm_enabled`` is true -- so the module
that would carry an LLM dependency is never even imported, let alone
reachable, from the scoring or ranking path when no LLM is configured
(FR-013, tests/unit/test_no_llm_in_ranking.py).
"""

from __future__ import annotations

from dataclasses import dataclass

_TEMPLATES: dict[str, dict] = {
    "support_recovery": {
        "subject": "Checking in on your recent support experience",
        "body": (
            "Hi {account_name},\n\n"
            "I wanted to follow up on the support you've received recently -- "
            "I know it hasn't been fast enough, and that's on us. I'd like to "
            "set up time this week to walk through what happened and make it right.\n\n"
            "Best,\n{csm_name}"
        ),
        "claims": ["support_experience"],
    },
    "adoption_nudge": {
        "subject": "A few things in the product you might have missed",
        "body": (
            "Hi {account_name},\n\n"
            "I noticed your team's usage has dropped off recently, and wanted to "
            "check in -- happy to walk through anything that's gotten in the way, "
            "or show a few things that might help.\n\n"
            "Best,\n{csm_name}"
        ),
        "claims": ["usage_decline"],
    },
    "billing_resolution": {
        "subject": "Let's sort out your recent billing issue",
        "body": (
            "Hi {account_name},\n\n"
            "I saw there's been some friction with recent payments on your account "
            "and wanted to reach out directly to get it resolved.\n\n"
            "Best,\n{csm_name}"
        ),
        "claims": ["payment_friction"],
    },
    "relationship_rebuild": {
        "subject": "Checking in",
        "body": (
            "Hi {account_name},\n\n"
            "It's been a while since we last connected -- I'd love to get some time "
            "on the calendar to hear how things are going.\n\n"
            "Best,\n{csm_name}"
        ),
        "claims": ["relationship_engagement"],
    },
    "commercial_review": {
        "subject": "Getting ahead of your upcoming renewal",
        "body": (
            "Hi {account_name},\n\n"
            "Your renewal is coming up, and I wanted to get ahead of it with a quick "
            "review of how things are going and what your plan should look like next.\n\n"
            "Best,\n{csm_name}"
        ),
        "claims": ["commercial_signals"],
    },
}


@dataclass(frozen=True, slots=True)
class Draft:
    subject: str
    body: str
    draft_source: str  # "template" | "llm"
    claims: list[str]


def draft_template(play_key: str, *, account_name: str, csm_name: str) -> Draft:
    t = _TEMPLATES[play_key]
    return Draft(
        subject=t["subject"],
        body=t["body"].format(account_name=account_name, csm_name=csm_name),
        draft_source="template",
        claims=list(t["claims"]),
    )


def draft(
    play_key: str, *, account_name: str, csm_name: str, llm_enabled: bool, llm_api_key: str | None = None,
) -> Draft:
    """The single entry point every caller uses. Degraded (template) prose is
    acceptable; an unconfigured or disabled LLM must never block a draft."""
    if llm_enabled and llm_api_key:
        from pulse.agent.llm_drafter import draft_with_llm  # local: see module docstring

        return draft_with_llm(play_key, account_name=account_name, csm_name=csm_name, api_key=llm_api_key)
    return draft_template(play_key, account_name=account_name, csm_name=csm_name)


def validate_grounding(d: Draft, available_evidence_drivers: set[str]) -> tuple[bool, str | None]:
    """Reject a draft before a human (or an auto-send) ever sees it if any
    claim it makes isn't backed by evidence actually gathered for this
    account's score (T074). ``available_evidence_drivers`` is the set of
    driver groups whose evidence list was non-empty for this FeatureResult --
    see features/compute.py's per-driver evidence accumulator."""
    missing = [c for c in d.claims if c not in available_evidence_drivers]
    if missing:
        return False, f"unsupported_claim:{','.join(missing)}"
    return True, None
