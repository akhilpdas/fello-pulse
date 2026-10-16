"""Found while building T207 (leave-one-tenant-out): the pipeline paired the *time-sorted* test
block with the *tenant-ordered* slug list (``tenant_slugs[-len(split.test):]``), so every model
card attributed the whole test block to one tenant ('northwind', 13,086 of 13,086 rows) and the
"per-tenant performance" report was wrong.

Names the production change that makes it fail: ``pipeline.split_with_tenants`` -- the split must
carry each row's tenant through the sort.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pulse.ml.panel import PanelRow
from pulse.ml.pipeline import split_with_tenants


def _rows():
    base = datetime(2025, 1, 6, tzinfo=UTC)
    rows, slugs = [], []
    # Tenant order in the list is a, a, a, b, b, b -- NOT time order: tenant a's rows are
    # the latest, tenant b's the earliest, so the sorted test block must be all tenant a.
    for i in range(3):
        rows.append(PanelRow(f"a{i}", base + timedelta(weeks=100 + i), {"x": 1.0}, False)); slugs.append("a")
    for i in range(3):
        rows.append(PanelRow(f"b{i}", base + timedelta(weeks=i), {"x": 1.0}, False)); slugs.append("b")
    return rows, slugs


def test_every_split_block_keeps_each_rows_own_tenant():
    rows, slugs = _rows()
    split, tenants = split_with_tenants(rows, slugs, train=0.5, val=0.0, calib=0.0)
    for block_name in ("train", "test"):
        block = getattr(split, block_name)
        assert [t for t in getattr(tenants, block_name)] == [
            "a" if str(r.account_id).startswith("a") else "b" for r in block
        ], block_name
    assert set(tenants.test) == {"a"}  # the latest rows belong to tenant a, whatever the input order
