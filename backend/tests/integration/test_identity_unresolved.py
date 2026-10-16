"""T027: an unmapped source reference is stored, flagged unresolved and surfaced --
and never creates a phantom account."""

from __future__ import annotations

from tests.integration.conftest import record


def test_unmapped_ref_is_stored_unresolved_and_creates_no_account(ingest_tenant):
    accounts_before = ingest_tenant.scalar("SELECT count(*) FROM account")
    feed = ingest_tenant.feed("zendesk", [
        record("z1", "zd-1", "ticket.created", "2026-09-01T09:00:00Z", "2026-09-01T10:00:00Z"),
        record("z2", "zd-GHOST", "ticket.created", "2026-09-02T09:00:00Z", "2026-09-02T10:00:00Z"),
    ])
    result = ingest_tenant.ingest("zendesk", feed)

    assert result.inserted == 2 and result.unresolved == 1
    assert ingest_tenant.scalar("SELECT account_id IS NULL FROM source_event WHERE source_event_id='z2'") is True
    assert ingest_tenant.scalar("SELECT account_id IS NOT NULL FROM source_event WHERE source_event_id='z1'") is True
    # surfaced as an explicit, queryable state
    assert ingest_tenant.scalar(
        "SELECT method FROM identity_link WHERE source_account_ref = 'zd-GHOST'") == "unresolved"
    assert ingest_tenant.scalar("SELECT count(*) FROM account") == accounts_before
