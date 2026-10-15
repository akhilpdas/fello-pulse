"""The ranking layer: priority = p x value_at_risk x urgency (clarifications
B-2). Renewal proximity enters here, as an explicit multiplier a CSM can
check, never as a model feature secretly encoding business policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ScoreInput:
    account_id: object
    probability: float
    value_at_risk_cents: float
    days_to_renewal: float | None
    suppressed: bool = False


@dataclass(frozen=True, slots=True)
class RankedRow:
    account_id: object
    probability: float
    value_at_risk_cents: float
    urgency_multiplier: float
    priority: float
    ranking_math: dict = field(default_factory=dict)


def urgency_multiplier(days_to_renewal: float | None) -> float:
    """Nearer renewals carry more urgency at an equal probability and value --
    the whole reason this is a multiplier rather than left to the model
    (clarifications B-2)."""
    if days_to_renewal is None:
        return 1.0
    if days_to_renewal <= 30:
        return 2.0
    if days_to_renewal <= 90:
        return 1.5
    return 1.0


def rank_accounts(rows: list[ScoreInput], capacity: int) -> tuple[list[RankedRow], int]:
    """Returns the ranked, capacity-bound queue and the count of accounts that
    would have qualified but fell below the cut."""
    eligible = [r for r in rows if not r.suppressed]

    ranked_rows = []
    for r in eligible:
        urgency = urgency_multiplier(r.days_to_renewal)
        priority = r.probability * r.value_at_risk_cents * urgency
        ranked_rows.append(RankedRow(
            account_id=r.account_id, probability=r.probability,
            value_at_risk_cents=r.value_at_risk_cents, urgency_multiplier=urgency,
            priority=priority,
            ranking_math={
                "probability": r.probability,
                "value_at_risk_cents": r.value_at_risk_cents,
                "urgency_multiplier": urgency,
                "days_to_renewal": r.days_to_renewal,
                "priority": priority,
            },
        ))

    ranked_rows.sort(key=lambda r: -r.priority)
    below_cut = max(0, len(ranked_rows) - capacity)
    return ranked_rows[:capacity], below_cut
