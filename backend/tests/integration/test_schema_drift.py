"""T026: both spellings of a renamed field and both casings of an event type
normalise to the same stored shape -- the invisible failure is a history that
silently loses everything after (or before) the cutover."""

from __future__ import annotations

from tests.integration.conftest import record


def test_both_type_casings_and_both_field_names_normalise_identically(ingest_tenant):
    feed = ingest_tenant.feed("sf", [
        record("s1", "sf-1", "account.updated", "2024-03-01T09:00:00Z", "2024-03-01T10:00:00Z", {"plan": "pro"}),
        record("s2", "sf-1", "Account.Updated", "2025-03-01T09:00:00Z", "2025-03-01T10:00:00Z", {"plan_name": "pro"}),
    ])
    result = ingest_tenant.ingest("salesforce", feed)
    assert result.inserted == 2 and result.rejected == 0
    assert ingest_tenant.scalar(
        "SELECT count(DISTINCT event_type) FROM source_event WHERE source = 'salesforce'") == 1
    assert ingest_tenant.scalar(
        "SELECT count(*) FROM source_event WHERE payload->>'plan' = 'pro' AND NOT payload ? 'plan_name'") == 2


def test_an_unknown_event_type_is_rejected_loudly_not_dropped_silently(ingest_tenant):
    feed = ingest_tenant.feed("sf", [record("s1", "sf-1", "contract.teleported", "2025-03-01T09:00:00Z",
                                            "2025-03-01T10:00:00Z")])
    result = ingest_tenant.ingest("salesforce", feed)
    assert result.rejected == 1 and result.inserted == 0
    assert "contract.teleported" in result.rejects[0]
