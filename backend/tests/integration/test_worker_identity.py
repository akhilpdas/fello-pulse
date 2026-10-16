"""T242 (FR-010): the unattended worker acts under a system identity -- not a person's session -- and
its cycles are attributed to the system in the audit trail. No route lets a user start, alter or
re-run a cycle: the run log is read-only over the API.

Names the production change that makes it fail: ``run_cycle`` writes a ``cycle_run`` audit event with
``actor_kind='system'`` and no user.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text

from pulse.agent.transport import RecordingTransport
from pulse.agent.worker import run_once
from pulse.api.main import app
from pulse.db.session import owner_session
from tests.integration._agent_fixtures import seed_account, seed_tenant, toy_support_model

AS_OF = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def test_a_cycle_is_attributed_to_the_system_with_no_user():
    tenant_id, cfg = seed_tenant(AS_OF)
    with owner_session() as s:
        seed_account(s, tenant_id, AS_OF, "sys-a", n_tickets=12)

    result = run_once(tenant_id=tenant_id, model=toy_support_model(3), model_version="t", tenant_config=cfg,
                      as_of=AS_OF, transport=RecordingTransport(), worker_id="w", lease_seconds=60)

    assert result is not None
    with owner_session() as s:
        ev = s.execute(text("SELECT actor_kind, actor_user_id, subject, detail FROM audit_event"
                            " WHERE tenant_id = :t AND event = 'cycle_run'"), {"t": tenant_id}).mappings().all()
        decided = s.execute(text("SELECT count(*) FROM action WHERE tenant_id = :t AND decided_by_user_id IS NOT NULL"),
                            {"t": tenant_id}).scalar()
    assert len(ev) == 1
    assert ev[0]["actor_kind"] == "system" and ev[0]["actor_user_id"] is None
    assert ev[0]["subject"] == str(result.run_id)
    assert ev[0]["detail"]["scored"] == 1
    assert decided == 0  # nothing the worker made is attributed to a person


def test_no_route_lets_a_user_start_or_change_a_cycle():
    for path, ops in app.openapi()["paths"].items():
        if path.startswith("/runs"):
            assert set(ops) == {"get"}, f"{path} allows {set(ops) - {'get'}}: the run log must be read-only"
    assert not [p for p in app.openapi()["paths"] if "cycle" in p.lower()]
