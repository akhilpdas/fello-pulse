"""ml/evaluate.py: honest metrics at the operating point the business actually
uses, alongside a trivial and a heuristic baseline (constitution, Engineering
Standards: "Honest metrics")."""

from __future__ import annotations

import numpy as np

from pulse.ml.evaluate import (
    captured_acv_at_capacity,
    pr_auc,
    precision_at_capacity,
    reliability_curve,
    roc_auc,
    trivial_baseline,
)


def test_precision_at_capacity_only_counts_the_top_n_by_score():
    y_true = np.array([1, 0, 1, 0, 1, 0])
    y_prob = np.array([0.9, 0.8, 0.7, 0.6, 0.1, 0.05])
    # top 3 by score: indices 0,1,2 -> true labels 1,0,1 -> precision 2/3
    assert abs(precision_at_capacity(y_true, y_prob, capacity=3) - 2 / 3) < 1e-9


def test_captured_acv_at_capacity_is_fraction_of_total_at_risk_value_caught():
    y_true = np.array([1, 1, 0])
    y_prob = np.array([0.9, 0.1, 0.5])
    value_at_risk = np.array([100.0, 900.0, 50.0])
    # capacity=1 catches only index 0 (the top-scored), which is a true
    # positive worth 100 out of a total of 1000 at-risk value among positives.
    assert abs(captured_acv_at_capacity(y_true, y_prob, value_at_risk, capacity=1) - 0.1) < 1e-9


def test_a_perfect_ranker_scores_close_to_one_on_both_aucs():
    y_true = np.array([0, 0, 0, 1, 1, 1])
    y_prob = np.array([0.1, 0.2, 0.3, 0.7, 0.8, 0.9])
    assert roc_auc(y_true, y_prob) == 1.0
    assert pr_auc(y_true, y_prob) == 1.0


def test_trivial_baseline_predicts_the_base_rate_for_everyone():
    y_true = np.array([1, 1, 0, 0])
    preds = trivial_baseline(y_true, n=4)
    assert all(p == 0.5 for p in preds)


def test_reliability_curve_has_one_point_per_requested_bin_with_data():
    y_true = np.array([0, 0, 1, 1, 1, 1])
    y_prob = np.array([0.1, 0.15, 0.85, 0.9, 0.88, 0.92])
    curve = reliability_curve(y_true, y_prob, n_bins=5)
    assert len(curve) >= 1
    assert all("predicted" in p and "observed" in p for p in curve)


def test_precision_at_capacity_does_not_depend_on_row_order_when_scores_tie():
    # Isotonic calibration produces plateaus of tied scores; which tied rows land
    # "in the top N" must not depend on arbitrary row order.
    y_prob = [0.5] * 10
    positives_first = [1, 1, 0, 0, 0, 0, 0, 0, 0, 0]
    positives_last = list(reversed(positives_first))
    assert precision_at_capacity(positives_first, y_prob, capacity=2) == precision_at_capacity(
        positives_last, y_prob, capacity=2)
    # With no information in the scores, expected precision is the base rate.
    assert abs(precision_at_capacity(positives_first, y_prob, capacity=2) - 0.2) < 1e-9


def test_precision_at_capacity_takes_untied_leaders_whole_and_shares_the_tied_remainder():
    y_true = [1, 1, 0, 0, 0]
    y_prob = [0.9, 0.5, 0.5, 0.5, 0.1]  # one clear leader, then a 3-way tie for 2 slots
    # slot 1: the leader (positive). slots 2-3: expected positives in the tie = 2 * (1/3)
    assert abs(precision_at_capacity(y_true, y_prob, capacity=3) - (1 + 2 / 3) / 3) < 1e-9


def test_captured_acv_is_order_invariant_under_ties():
    value = [100.0, 100.0, 100.0, 100.0]
    y_prob = [0.5] * 4
    a = captured_acv_at_capacity([1, 0, 0, 1], y_prob, value, capacity=1)
    b = captured_acv_at_capacity([0, 1, 1, 0], y_prob, value, capacity=1)
    c = captured_acv_at_capacity([1, 0, 0, 1], y_prob[::-1], value, capacity=1)
    assert abs(a - 0.25) < 1e-9 and abs(a - c) < 1e-9
    assert abs(b - 0.25) < 1e-9  # one slot among four tied rows; half the tied value is positive
