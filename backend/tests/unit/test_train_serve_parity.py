"""T043: panel-time and serve-time feature vectors for the same (account,
as_of) must be identical. Both the panel builder and the scoring service load
an account's events via features/repository.py and hand them to the same
features/compute.py function -- this test proves that round trip is
deterministic against the real ingested database, independent of how many
times or in what order it's invoked. (Extended in Phase 7's scoring-service
tests to compare directly against the live serving path once it exists.)
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text

from pulse.db.session import owner_session
from pulse.features.compute import compute
from pulse.features.repository import (
    identity_unresolved_for_account,
    load_account_feature_input,
    load_events,
)


def _an_account_with_history():
    with owner_session() as s:
        tenant_id = s.execute(text("SELECT id FROM tenant WHERE slug = 'northwind'")).scalar()
        account_id = s.execute(
            text(
                "SELECT a.id FROM account a JOIN source_event e ON e.account_id = a.id"
                " WHERE a.tenant_id = :t GROUP BY a.id HAVING count(*) > 50 LIMIT 1"
            ),
            {"t": tenant_id},
        ).scalar()
        connected = s.execute(
            text("SELECT connected_sources FROM tenant_config WHERE tenant_id = :t"), {"t": tenant_id}
        ).scalar()
    return account_id, frozenset(connected)


def test_two_independent_loads_of_the_same_account_as_of_produce_identical_vectors():
    account_id, connected = _an_account_with_history()
    as_of = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)

    def _compute_once():
        with owner_session() as s:
            events = load_events(s, account_id)
            account_input = load_account_feature_input(s, account_id)
            unresolved = identity_unresolved_for_account(s, account_id)
        return compute(
            connected_sources=connected, account=account_input, events=events,
            as_of=as_of, identity_unresolved=unresolved,
        )

    result_a = _compute_once()
    result_b = _compute_once()
    assert result_a.values == result_b.values
    assert result_a.coverage == result_b.coverage
    assert result_a.days_of_history == result_b.days_of_history
