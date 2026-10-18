"""The lead-time backtest flags accounts the way the product does: at each tenant's amber and red cut-offs
(clarifications B-33). With several tenants the loosest cut-off is used, so "flagged" never means less than it does for
the tenant that is most sensitive."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text

from pulse.db.session import elevated_session, owner_session
from pulse.ml.pipeline import lowest_tier_cutoffs
from tests.integration._agent_fixtures import seed_tenant

AS_OF = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def _tenant(amber: float, red: float):
    tenant_id, _ = seed_tenant(AS_OF)
    with owner_session() as s:
        s.execute(text("UPDATE tenant_config SET tier_amber_at = :a, tier_red_at = :r WHERE tenant_id = :t"),
                  {"a": amber, "r": red, "t": tenant_id})
    return tenant_id


def test_the_lowest_amber_and_red_cutoffs_across_the_given_tenants_are_used():
    a, b = _tenant(0.12, 0.30), _tenant(0.09, 0.25)
    with elevated_session() as s:
        assert lowest_tier_cutoffs(s, [a, b]) == {"amber": 0.09, "red": 0.25}


def test_one_tenant_gives_its_own_cutoffs():
    a = _tenant(0.1, 0.2)
    with elevated_session() as s:
        assert lowest_tier_cutoffs(s, [a]) == {"amber": 0.1, "red": 0.2}
