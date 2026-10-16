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

import re
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
    model: str | None = None  # which model wrote it, when draft_source == "llm"
    fallback_reason: str | None = None  # why a template was used where an LLM draft was wanted


def draft_template(play_key: str, *, account_name: str, csm_name: str) -> Draft:
    t = _TEMPLATES[play_key]
    return Draft(
        subject=t["subject"],
        body=t["body"].format(account_name=account_name, csm_name=csm_name),
        draft_source="template",
        claims=list(t["claims"]),
    )


def draft(
    play_key: str, *, account_name: str, csm_name: str, llm_enabled: bool = False, llm_api_key: str | None = None,
    facts: list[str] | None = None, llm=None,
) -> Draft:
    """The single entry point every caller uses. A language-model drafter (``llm``) is tried when one is
    supplied; on any failure -- or none supplied -- the deterministic template is used and the reason recorded.
    Degraded prose is acceptable; an unconfigured, disabled or failing model must never block a draft.
    (``llm_enabled`` / ``llm_api_key`` are kept for older callers and are not what enables the model: a
    constructed ``LlmDrafter`` is.)"""
    template = draft_template(play_key, account_name=account_name, csm_name=csm_name)
    if llm is None:
        return template
    drafted, reason = llm.draft(play_key, account_name=account_name, csm_name=csm_name, facts=list(facts or []))
    if drafted is not None:
        return drafted
    return Draft(subject=template.subject, body=template.body, draft_source="template",
                 claims=template.claims, fallback_reason=reason)


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


# --------------------------------------------------------------------------- #
# Validating model-written drafts (FR-026)
# --------------------------------------------------------------------------- #

_MAX_SUBJECT, _MAX_BODY = 120, 1500
_LINK = re.compile(r"https?://|www\.|\b[\w-]+(?:\.[\w-]+)*\.(?:com|net|org|io|co|ai|app)\b", re.I)
_MARKUP = re.compile(r"<\s*/?\s*[a-zA-Z]|\*\*|__|`|\]\(|^\s*#{1,6}\s", re.M)
_INSTRUCTION = re.compile(
    r"ignore (?:all |any )?(?:the )?(?:previous|prior|above)|as an ai\b|language model|system prompt"
    r"|\bpassword\b|\bwire (?:money|funds|transfer)\b|gift card|reply with your|click (?:here|the link)", re.I)
_DIGITS = re.compile(r"\d[\d,]*(?:\.\d+)?")
_WORDS = {w: n for n, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
    "seventeen eighteen nineteen twenty".split())}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_BIG = {"hundred": 100, "thousand": 1000, "million": 1_000_000, "dozen": 12}
# "one" is deliberately not treated as a number: it is ordinary prose ("no one", "one of our team").
_NUMBER_WORD = re.compile(
    r"\b(?:(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)[- ](?:one|two|three|four|five|six|seven|eight|nine)"
    r"|zero|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen"
    r"|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|dozen)\b", re.I)


def _numbers(text: str) -> set[float]:
    """Every number a reader could take from the text: digits, and number words (``seven``, ``twenty-eight``)."""
    found = {round(float(m.replace(",", "")), 2) for m in _DIGITS.findall(text)}
    for m in _NUMBER_WORD.findall(text):
        w = m.lower().replace("-", " ").split()
        val = _TENS[w[0]] + (_WORDS[w[1]] if len(w) > 1 else 0) if w[0] in _TENS else _BIG.get(w[0], _WORDS.get(w[0]))
        if val is not None:
            found.add(float(val))
    return found


def _fmt(n: float) -> str:
    return str(int(n)) if n == int(n) else str(n)


def validate_llm_output(
    draft: object, *, facts: list[str], allowed_claims: set[str], account_name: str, csm_name: str,
) -> tuple[bool, str | None]:
    """Accept a model-written draft only if everything concrete in it traces to the grounding.

    Rejected -- and the caller falls back to the template -- on: a wrong shape; empty or over-long text; a link,
    markup or instruction-like text; a claim outside what this play may say; or **any number (digits or words)
    that is not in the facts, the account name or the CSM name**. Dates are numbers, so an invented date fails
    here too. Returns ``(ok, reason)``.
    """
    if not isinstance(draft, dict) or not all(k in draft for k in ("subject", "body", "claims")):
        return False, "malformed"
    subject, body, claims = draft["subject"], draft["body"], draft["claims"]
    if not isinstance(subject, str) or not isinstance(body, str) or not isinstance(claims, list):
        return False, "malformed"
    if not subject.strip():
        return False, "empty_subject"
    if not body.strip():
        return False, "empty_body"
    if len(subject) > _MAX_SUBJECT:
        return False, "subject_too_long"
    if len(body) > _MAX_BODY:
        return False, "body_too_long"
    text = f"{subject}\n{body}"
    if _LINK.search(text):
        return False, "link"
    if _MARKUP.search(text):
        return False, "markup"
    if _INSTRUCTION.search(text):
        return False, "instruction"
    if not claims:
        return False, "no_claims"
    stray = sorted(str(c) for c in claims if c not in allowed_claims)
    if stray:
        return False, f"unsupported_claim:{stray[0]}"
    allowed = _numbers(" ".join(facts)) | _numbers(account_name) | _numbers(csm_name)
    unsupported = sorted(_numbers(text) - allowed)
    if unsupported:
        return False, f"unsupported_number:{_fmt(unsupported[0])}"
    return True, None
