"""T231 GUARD (FR-005; plan R-6): CSM account scoping is only meaningful if accounts in an ingested
estate actually have owners who are users. This pins that precondition for the data ``run_all.sh``
builds. It passes on the first run -- it records a fact about the data, it is not test-first.

If this ever fails, FR-005 degrades to tenant-wide visibility for CSMs and that must be written in
clarifications.md, not hidden.
"""

from __future__ import annotations

from sqlalchemy import text

from pulse.db.session import owner_session


def test_most_accounts_of_every_ingested_tenant_have_an_owner_who_is_a_csm_user():
    with owner_session() as s:
        rows = s.execute(text(
            "SELECT t.slug, count(*) AS accounts, count(a.owner_user_id) AS owned,"
            "       count(DISTINCT a.owner_user_id) FILTER (WHERE u.role = 'csm') AS csm_owners"
            " FROM account a JOIN tenant t ON t.id = a.tenant_id"
            " LEFT JOIN app_user u ON u.id = a.owner_user_id"
            " WHERE EXISTS (SELECT 1 FROM ingestion_watermark w WHERE w.tenant_id = t.id)"
            " GROUP BY t.slug")).all()
    assert rows, "no ingested tenants found: build the test database (see README)"
    for slug, accounts, owned, csm_owners in rows:
        assert owned / accounts >= 0.9, f"{slug}: only {owned}/{accounts} accounts have an owner"
        assert csm_owners >= 2, f"{slug}: needs at least two CSM owners to make scoping observable"
