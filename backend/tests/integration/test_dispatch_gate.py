"""agent/cycle.py (T070): an un-allowlisted play cannot self-send, and the
withholding is recorded with its reason on the Action row (constitution
Principle III).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text

from pulse.agent.cycle import run_cycle
from pulse.agent.transport import RecordingTransport
from pulse.db.session import owner_session, tenant_session
from tests.integration._agent_fixtures import seed_account, seed_tenant, toy_support_model

AS_OF = datetime(2026, 7, 8, 9, 0, tzinfo=UTC)


def test_no_action_is_ever_auto_sent_without_an_allowlist_row():
    tenant_id, tenant_config = seed_tenant(AS_OF)
    with owner_session() as s:
        seed_account(s, tenant_id, AS_OF, "risky-acct", n_tickets=15)
        no_allowlist = s.execute(
            text("SELECT count(*) FROM play_allowlist WHERE tenant_id = :t"), {"t": tenant_id},
        ).scalar()
    assert no_allowlist == 0

    model = toy_support_model(seed=13)
    transport = RecordingTransport()

    with tenant_session(tenant_id) as s:
        result = run_cycle(
            s, tenant_id=tenant_id, model=model, model_version="test-dispatch-gate",
            tenant_config=tenant_config, as_of=AS_OF, transport=transport,
        )

    assert result.stage_counts["sent"] == 0
    assert transport.sent == []
    assert result.stage_counts["drafted"] > 0, "fixture assumption: the risky account drafts"

    with owner_session() as s:
        drafted = s.execute(
            text("SELECT state, state_reason FROM action WHERE agent_run_id = :r AND state = 'drafted'"),
            {"r": result.run_id},
        ).mappings().all()

    assert len(drafted) == result.stage_counts["drafted"]
    for row in drafted:
        assert row["state_reason"] == "not_allowlisted_for_auto_send"
