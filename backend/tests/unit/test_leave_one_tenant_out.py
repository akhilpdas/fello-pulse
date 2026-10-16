"""T207 (001/FR-018): leave-one-tenant-out tells a new tenant how the model will do on data it has
never been trained on -- the cold-start question the shared model (B-7) makes important.

Names the production change that makes it fail: ``evaluate.leave_one_tenant_out`` -- for each tenant,
train on the *other* tenants' rows from before the cutoff, score this tenant's rows from the cutoff on.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pulse.ml.evaluate import leave_one_tenant_out
from pulse.ml.panel import PanelRow

BASE = datetime(2025, 1, 6, tzinfo=UTC)
CUTOFF = BASE + timedelta(weeks=10)


def _rows():
    rows, tenants = [], []
    for tenant, positives in (("a", True), ("b", True), ("c", False)):  # c never has a positive
        for w in range(20):
            label = positives and w % 4 == 0
            rows.append(PanelRow(f"{tenant}{w}", BASE + timedelta(weeks=w), {"x": float(w)}, label))
            tenants.append(tenant)
    return rows, tenants


def test_each_tenant_is_held_out_and_the_future_never_trains():
    rows, tenants = _rows()
    seen = []

    def train_fn(train_rows):
        seen.append(train_rows)
        return len(train_rows)

    def predict_fn(model, held_rows):
        return [r.feature_values["x"] / 20 for r in held_rows]

    out = leave_one_tenant_out(rows, tenants, cutoff=CUTOFF, train_fn=train_fn, predict_fn=predict_fn, capacity=3)

    assert sorted(out) == ["a", "b", "c"]
    assert len(seen) == 3
    held_out = set()
    for train_rows in seen:
        present = {str(r.account_id)[0] for r in train_rows}
        missing = {"a", "b", "c"} - present
        assert len(missing) == 1, "exactly one tenant must be absent from each training set"
        held_out |= missing
        assert all(r.as_of < CUTOFF for r in train_rows), "rows from the held-out period leaked into training"
    assert held_out == {"a", "b", "c"}  # every tenant was held out once
    assert out["a"]["n_test"] == 10 and out["a"]["n_train"] == 20  # b and c, weeks 0-9


def test_metrics_are_reported_and_a_single_class_tenant_reports_null_not_zero():
    rows, tenants = _rows()
    out = leave_one_tenant_out(rows, tenants, cutoff=CUTOFF, train_fn=lambda r: None,
                               predict_fn=lambda m, held: [r.feature_values["x"] for r in held], capacity=3)
    assert 0.0 <= out["a"]["roc_auc"] <= 1.0
    assert out["a"]["precision_at_capacity"] is not None
    # tenant c has no positives in the held-out period: AUC is undefined -- say so, never report 0.
    assert out["c"]["roc_auc"] is None
