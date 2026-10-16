"""Found by rebuilding the demo database on identical data: precision@100 came out 0.252, where earlier builds gave
0.196, 0.288, 0.326. The panel was built from ``SELECT id FROM account`` with no ORDER BY, so row order followed the
table's physical layout -- which differs on every rebuild -- and the fitted model followed the row order. A headline
metric that moves ±0.06 because of Postgres heap order is not a result.

Names the production change that makes it fail: ``pipeline.panel_account_ids`` returning accounts ordered by their
stable external reference, not by physical layout.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text

from pulse.db.session import owner_session
from pulse.ml.pipeline import panel_account_ids


def test_accounts_come_back_in_external_ref_order_whatever_their_ids_or_insertion_order():
    tenant_id = uuid.uuid4()
    refs = ["zz-00003", "zz-00001", "zz-00002", "zz-00000"]          # inserted in this (scrambled) order ...
    ids = sorted((uuid.uuid4() for _ in refs), reverse=True)           # ... with ids that sort the other way
    with owner_session() as s:
        s.execute(text("INSERT INTO tenant (id, slug, name, created_at) VALUES (:i,:s,'t', now())"),
                  {"i": tenant_id, "s": f"order-{uuid.uuid4().hex[:8]}"})
        for ref, aid in zip(refs, ids, strict=True):
            s.execute(text("INSERT INTO account (id, tenant_id, external_ref, name, signup_date, lifecycle_state, created_at)"
                           " VALUES (:i,:t,:r,:r,DATE '2024-01-01','active', now())"), {"i": aid, "t": tenant_id, "r": ref})
        # an UPDATE moves a row's physical position -- exactly what the ingestion step does to every account
        s.execute(text("UPDATE account SET name = name || '!' WHERE external_ref = 'zz-00000'"))
    try:
        with owner_session() as s:
            got = [s.execute(text("SELECT external_ref FROM account WHERE id = :i"), {"i": a}).scalar()
                   for a in panel_account_ids(s, tenant_id)]
        assert got == ["zz-00000", "zz-00001", "zz-00002", "zz-00003"]
    finally:
        with owner_session() as s:
            s.execute(text("DELETE FROM tenant WHERE id = :i"), {"i": tenant_id})
