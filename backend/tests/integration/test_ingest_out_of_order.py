"""T025 (FR-005): a record that happened long ago but arrives today is ordinary --
accepted, kept at its true time, and it does not disturb the history around it."""

from __future__ import annotations

from tests.integration.conftest import record


def test_a_late_arriving_old_record_is_accepted_at_its_true_occurred_time(ingest_tenant):
    on_time = [record("z1", "zd-1", "ticket.created", "2026-09-10T09:00:00Z", "2026-09-10T09:05:00Z")]
    late = [record("z0", "zd-1", "ticket.created", "2026-09-01T09:00:00Z", "2026-09-12T09:00:00Z")]  # 11 days late

    ingest_tenant.ingest("zendesk", ingest_tenant.feed("pass1", on_time))
    result = ingest_tenant.ingest("zendesk", ingest_tenant.feed("pass2", on_time + late))

    assert result.inserted == 1  # the late record, past the watermark by arrival time
    order = ingest_tenant.scalar(
        "SELECT string_agg(source_event_id, ',' ORDER BY occurred_at) FROM source_event")
    assert order == "z0,z1"  # history reads in true order although z0 arrived last
    assert ingest_tenant.scalar("SELECT occurred_at::date::text FROM source_event WHERE source_event_id='z0'") == "2026-09-01"


def test_the_on_time_record_is_untouched_by_the_late_arrival(ingest_tenant):
    ingest_tenant.ingest("zendesk", ingest_tenant.feed("pass1", [
        record("z1", "zd-1", "ticket.created", "2026-09-10T09:00:00Z", "2026-09-10T09:05:00Z")]))
    before = ingest_tenant.scalar("SELECT received_at::text FROM source_event WHERE source_event_id='z1'")
    ingest_tenant.ingest("zendesk", ingest_tenant.feed("pass2", [
        record("z1", "zd-1", "ticket.created", "2026-09-10T09:00:00Z", "2026-09-10T09:05:00Z"),
        record("z0", "zd-1", "ticket.created", "2026-09-01T09:00:00Z", "2026-09-12T09:00:00Z")]))
    assert ingest_tenant.scalar("SELECT received_at::text FROM source_event WHERE source_event_id='z1'") == before
