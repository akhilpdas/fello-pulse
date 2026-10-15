"""T052: priority = p x value_at_risk x urgency (clarifications B-2). Nearer
renewal outranks equal probability and value; suppression removes an account
entirely; the capacity cut is respected and the overflow counted."""

from __future__ import annotations

from pulse.domain.ranking import ScoreInput, rank_accounts


def _row(account_id, probability, value_at_risk_cents, days_to_renewal, suppressed=False):
    return ScoreInput(
        account_id=account_id, probability=probability,
        value_at_risk_cents=value_at_risk_cents, days_to_renewal=days_to_renewal,
        suppressed=suppressed,
    )


def test_nearer_renewal_outranks_equal_probability_and_value():
    rows = [
        _row("far", probability=0.5, value_at_risk_cents=100_000, days_to_renewal=200),
        _row("near", probability=0.5, value_at_risk_cents=100_000, days_to_renewal=10),
    ]
    ranked, below_cut = rank_accounts(rows, capacity=10)
    assert [r.account_id for r in ranked] == ["near", "far"]


def test_suppression_removes_the_account_from_the_ranked_list_entirely():
    rows = [
        _row("suppressed", probability=0.99, value_at_risk_cents=1_000_000, days_to_renewal=5, suppressed=True),
        _row("normal", probability=0.1, value_at_risk_cents=1_000, days_to_renewal=300),
    ]
    ranked, below_cut = rank_accounts(rows, capacity=10)
    assert [r.account_id for r in ranked] == ["normal"]


def test_capacity_cut_is_respected_and_overflow_is_counted():
    rows = [_row(f"a{i}", probability=0.9 - i * 0.01, value_at_risk_cents=1000, days_to_renewal=100)
            for i in range(15)]
    ranked, below_cut = rank_accounts(rows, capacity=10)
    assert len(ranked) == 10
    assert below_cut == 5
    assert [r.account_id for r in ranked] == [f"a{i}" for i in range(10)]


def test_ranking_math_is_emitted_and_reconstructs_the_priority():
    rows = [_row("a", probability=0.4, value_at_risk_cents=200_000, days_to_renewal=20)]
    ranked, _ = rank_accounts(rows, capacity=10)
    row = ranked[0]
    math_ = row.ranking_math
    assert math_["probability"] == 0.4
    reconstructed = math_["probability"] * math_["value_at_risk_cents"] * math_["urgency_multiplier"]
    assert abs(reconstructed - row.priority) < 1e-9
