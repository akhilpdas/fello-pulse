"""A tenant's runtime (what a cycle needs) is built from its own tenant_config."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text

from pulse.agent.transport import RecordingTransport
from pulse.agent.worker import build_runtime
from pulse.db.session import owner_session
from tests.integration._agent_fixtures import seed_tenant, toy_support_model


def test_runtime_carries_that_tenants_config_not_defaults():
    tenant_id, _ = seed_tenant(datetime(2026, 10, 1, tzinfo=UTC))  # connected: zendesk, stripe
    with owner_session() as s:
        s.execute(text("UPDATE tenant_config SET suppression_days = 3, max_sends_per_cycle = 7"
                       " WHERE tenant_id = :t"), {"t": tenant_id})
    rt = build_runtime(tenant_id, model=toy_support_model(3), model_version="m", transport=RecordingTransport())
    assert rt.tenant_config["connected_sources"] == frozenset({"zendesk", "stripe"})
    assert rt.tenant_config["suppression_days"] == 3
    assert rt.tenant_config["max_sends_per_cycle"] == 7
    assert isinstance(rt.tenant_config["tier_red_at"], float)
