"""The unattended loop (non-negotiable: something runs without a human triggering it).

Until now ``serve`` was an untested ``sleep`` wrapper nobody could start, ``tick`` let one
tenant's exception kill every tenant behind it, and "is this tenant due?" compared the
wall-clock ``started_at`` to the injected clock -- so under a simulated clock every tenant
was always due. Each test below names the production change that makes it fail.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from pulse.agent.transport import RecordingTransport
from pulse.agent.worker import TenantRuntime, due_tenants, serve, tick
from pulse.config import FrozenClock
from pulse.db.session import owner_session


@pytest.fixture
def world():
    """A clock in a year no real data reaches (so no run recorded by other tests is ever
    'recent' to it), an empty tenant that cycles trivially, and cleanup of everything made."""
    start = datetime(2040, 1, 1, tzinfo=UTC) + timedelta(days=random.randrange(0, 20000))
    clock = FrozenClock(start)
    tenant_id = uuid.uuid4()
    with owner_session() as s:
        s.execute(text("INSERT INTO tenant (id, slug, name, created_at) VALUES (:i,:s,'w', now())"),
                  {"i": tenant_id, "s": f"serve-{uuid.uuid4().hex[:8]}"})
        s.execute(text("INSERT INTO tenant_config (id, tenant_id) VALUES (:i,:t)"),
                  {"i": uuid.uuid4(), "t": tenant_id})
    yield clock, tenant_id
    with owner_session() as s:
        s.execute(text("DELETE FROM agent_run WHERE tenant_id = :t OR as_of >= '2040-01-01'"),
                  {"t": tenant_id})
        s.execute(text("DELETE FROM work_lease WHERE key = :t"), {"t": str(tenant_id)})
        s.execute(text("DELETE FROM tenant_config WHERE tenant_id = :t"), {"t": tenant_id})
        s.execute(text("DELETE FROM tenant WHERE id = :t"), {"t": tenant_id})


def _config() -> dict:
    return {
        "connected_sources": frozenset(), "min_days_history": 30, "min_sources_with_data": 1,
        "tier_red_at": 0.4, "tier_amber_at": 0.15, "material_delta": 0.1,
        "suppression_days": 14, "max_sends_per_cycle": 5,
    }


def _runtime(tenant_id, config=None) -> TenantRuntime:
    # model=None: an empty tenant has no accounts, so the model is never consulted.
    return TenantRuntime(tenant_id=tenant_id, model=None, model_version="t-1",
                         tenant_config=config if config is not None else _config(),
                         transport=RecordingTransport())


def _runs(tenant_id) -> list[tuple[str, datetime]]:
    with owner_session() as s:
        return [(r[0], r[1]) for r in s.execute(
            text("SELECT status, as_of FROM agent_run WHERE tenant_id = :t ORDER BY as_of"),
            {"t": tenant_id}).all()]


def _insert_run(tenant_id, as_of, status="succeeded"):
    with owner_session() as s:
        s.execute(text(
            "INSERT INTO agent_run (id, tenant_id, trigger, started_at, status, as_of,"
            " stage_counts, decisions_declined, errors)"
            " VALUES (:i,:t,'schedule', now(), :st, :ao, '{}'::jsonb, '[]'::jsonb, '[]'::jsonb)"),
            {"i": uuid.uuid4(), "t": tenant_id, "st": status, "ao": as_of})


# Fails today because due_tenants compares agent_run.started_at (wall clock, ~now) to the
# injected clock: with a clock in 2040 every run looks ancient, so the tenant is "due" 5
# minutes after it ran. Fix: judge recency in the clock's own domain (agent_run.as_of).
def test_a_tenant_that_just_ran_is_not_due_even_when_the_clock_is_not_the_wall_clock(world):
    clock, tenant_id = world
    _insert_run(tenant_id, clock.now())
    assert tenant_id not in due_tenants(clock.now() + timedelta(minutes=5), cycle_interval_minutes=15)
    assert tenant_id in due_tenants(clock.now() + timedelta(minutes=16), cycle_interval_minutes=15)


# Fails today because tick re-raises: the first broken tenant aborts the loop, so the
# healthy tenant behind it is never cycled -- and nothing records that anything failed
# (the cycle is one transaction, so the 'running' row rolls back with it).
def test_one_failing_tenant_neither_stops_the_others_nor_vanishes_from_the_run_log(world):
    clock, healthy = world
    with owner_session() as s:
        broken = s.execute(text("SELECT id FROM tenant WHERE slug = 'northwind'")).scalar()
    # {} lacks every key a cycle reads -> KeyError on northwind's first account.
    runtimes = [_runtime(broken, config={}), _runtime(healthy)]

    results = tick(runtimes, clock=clock, worker_id="t", lease_seconds=60, cycle_interval_minutes=15)

    assert [r.stage_counts["scored"] for r in results] == [0]  # the healthy, empty tenant ran
    assert [s for s, _ in _runs(healthy)] == ["succeeded"]
    broken_runs = [r for r in _runs(broken) if r[1] == clock.now()]
    assert [s for s, _ in broken_runs] == ["failed"]
    with owner_session() as s:
        err = s.execute(text("SELECT errors FROM agent_run WHERE tenant_id = :t AND status = 'failed'"
                             " AND as_of = :a"), {"t": broken, "a": clock.now()}).scalar()
    assert err and "KeyError" in err[0]["error"]


# Fails today because serve takes no stopping condition or sleep: it cannot be run in a test
# at all, and nothing starts it.
def test_serve_cycles_a_tenant_every_interval_with_nobody_asking(world):
    clock, tenant_id = world
    serve([_runtime(tenant_id)], clock=clock, max_ticks=3,
          sleep=lambda _seconds: clock.advance(minutes=20))
    assert [s for s, _ in _runs(tenant_id)] == ["succeeded"] * 3


def test_serve_does_not_cycle_again_inside_the_interval(world):
    clock, tenant_id = world
    serve([_runtime(tenant_id)], clock=clock, max_ticks=3,
          sleep=lambda _seconds: clock.advance(minutes=5))
    assert [s for s, _ in _runs(tenant_id)] == ["succeeded"]


# Fails today because OffsetClock does not exist. The demo data's "now" (its newest event)
# is later than the wall clock, so a worker scoring "as of now" would ignore the newest weeks;
# the worker needs a clock that is the simulated present and keeps moving.
def test_offset_clock_is_the_base_clock_shifted_by_a_fixed_amount():
    from pulse.config import OffsetClock

    base = FrozenClock(datetime(2026, 10, 16, 9, 0, tzinfo=UTC))
    shifted = OffsetClock(base=base, offset=timedelta(days=25))
    assert shifted.now() == datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
    base.advance(minutes=30)
    assert shifted.now() == datetime(2026, 11, 10, 9, 30, tzinfo=UTC)
