"""T097 / SC-007: the run record carries the cycle's real wall-clock duration, so
"did the cycle fit inside the scheduling interval" is answerable from the run log."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text

from pulse.agent.transport import RecordingTransport
from pulse.agent.worker import run_once
from pulse.db.session import owner_session
from tests.integration._agent_fixtures import seed_account, seed_tenant, toy_support_model

AS_OF = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def test_run_record_has_a_real_duration_and_a_finish_after_the_start():
    tenant_id, cfg = seed_tenant(AS_OF)
    with owner_session() as s:
        seed_account(s, tenant_id, AS_OF, "dur-a", n_tickets=12)
    result = run_once(tenant_id=tenant_id, model=toy_support_model(3), model_version="t",
                      tenant_config=cfg, as_of=AS_OF, transport=RecordingTransport(),
                      worker_id="dur", lease_seconds=300)
    with owner_session() as s:
        row = s.execute(text("SELECT duration_ms, started_at, finished_at FROM agent_run WHERE id = :i"),
                        {"i": result.run_id}).one()
    assert row.duration_ms > 0
    assert row.finished_at > row.started_at
