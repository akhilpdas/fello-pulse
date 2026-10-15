"""SC-013: the full pipeline runs end to end with no LLM configured.
Constitution Principle II: degraded prose is acceptable, degraded ranking is
not -- the run must succeed and every draft must come from the template
path, not silently skip accounts because no LLM was available.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text

from pulse.agent.cycle import run_cycle
from pulse.agent.transport import RecordingTransport
from pulse.config import get_settings
from pulse.db.session import owner_session, tenant_session
from tests.integration._agent_fixtures import seed_account, seed_tenant, toy_support_model

AS_OF = datetime(2026, 7, 15, 9, 0, tzinfo=UTC)


def test_settings_default_has_no_llm_configured():
    s = get_settings()
    assert s.llm_enabled is False
    assert s.llm_api_key is None


def test_full_cycle_succeeds_and_every_draft_is_template_sourced():
    tenant_id, tenant_config = seed_tenant(AS_OF)
    with owner_session() as s:
        seed_account(s, tenant_id, AS_OF, "risky-acct", n_tickets=15)

    model = toy_support_model(seed=31)
    transport = RecordingTransport()
    settings = get_settings()

    with tenant_session(tenant_id) as s:
        result = run_cycle(
            s, tenant_id=tenant_id, model=model, model_version="test-no-llm",
            tenant_config=tenant_config, as_of=AS_OF, transport=transport,
            llm_enabled=settings.llm_enabled, llm_api_key=settings.llm_api_key,
        )

    with owner_session() as s:
        run_status = s.execute(
            text("SELECT status FROM agent_run WHERE id = :i"), {"i": result.run_id},
        ).scalar()
        draft_sources = s.execute(
            text("SELECT DISTINCT draft_source FROM action WHERE agent_run_id = :i"), {"i": result.run_id},
        ).scalars().all()

    assert run_status == "succeeded"
    assert result.stage_counts["drafted"] > 0, "fixture assumption: the risky account drafts"
    assert draft_sources == ["template"]
