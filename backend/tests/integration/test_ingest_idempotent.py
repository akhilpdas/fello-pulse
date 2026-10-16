"""T024 (FR-003, FR-004): replaying a feed neither duplicates rows nor advances the
watermark's counters twice."""

from __future__ import annotations

from sqlalchemy import text

from pulse.db.session import owner_session
from tests.integration.conftest import record

TICKETS = [record(f"z{i}", "zd-1", "ticket.created", f"2026-09-0{i}T09:00:00Z", f"2026-09-0{i}T10:00:00Z",
                  {"ticket_ref": f"t{i}"}) for i in (1, 2, 3)]


def test_second_replay_inserts_nothing_and_advances_the_watermark_once(ingest_tenant):
    feed = ingest_tenant.feed("zendesk", TICKETS)
    first = ingest_tenant.ingest("zendesk", feed)
    second = ingest_tenant.ingest("zendesk", feed)
    assert (first.inserted, second.inserted) == (3, 0)
    assert ingest_tenant.scalar("SELECT count(*) FROM source_event") == 3
    assert ingest_tenant.scalar("SELECT events_ingested FROM ingestion_watermark WHERE source='zendesk'") == 3


def test_the_unique_constraint_alone_prevents_duplicates_when_the_watermark_is_lost(ingest_tenant):
    # A crash that loses the watermark must still be safe: the database is the control.
    feed = ingest_tenant.feed("zendesk", TICKETS)
    ingest_tenant.ingest("zendesk", feed)
    with owner_session() as s:
        s.execute(text("DELETE FROM ingestion_watermark WHERE tenant_id = :t"), {"t": ingest_tenant.tenant_id})
    again = ingest_tenant.ingest("zendesk", feed)
    assert again.inserted == 0
    assert ingest_tenant.scalar("SELECT count(*) FROM source_event") == 3

