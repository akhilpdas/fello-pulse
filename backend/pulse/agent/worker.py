"""The tick loop (T066): for every tenant due for a cycle, claim its lease,
run one cycle, release the lease. Crash-safe -- a worker that dies mid-cycle
leaves an expired lease a later tick reclaims (T068) -- and overlap-safe --
two workers racing for the same tenant's lease, only one wins (T069).

``run_once`` is the unit a test or a single scheduler tick calls for one
tenant. ``tick`` is the loop over every due tenant; the infinite
``sleep``-driven ``serve`` wrapper around it is not itself under test -- it
has no decision logic of its own, only timing.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text

from pulse.agent import lease
from pulse.agent.cycle import CycleResult, run_cycle
from pulse.agent.transport import Transport
from pulse.config import Clock, SystemClock, get_settings
from pulse.db.session import owner_session, tenant_session
from pulse.ml.train import TrainedModel

LEASE_KIND = "agent_cycle"


def due_tenants(now: datetime, *, cycle_interval_minutes: int) -> list[uuid.UUID]:
    """Tenants with no running or succeeded run started within the interval.
    A tenant whose last run *failed* is due again immediately -- a failure
    must not silently gate the next attempt behind the same cooldown as a
    healthy cycle."""
    cutoff = now - timedelta(minutes=cycle_interval_minutes)
    with owner_session() as s:
        rows = s.execute(
            text(
                "SELECT t.id FROM tenant t WHERE NOT EXISTS ("
                "  SELECT 1 FROM agent_run r WHERE r.tenant_id = t.id"
                "    AND r.started_at > :cutoff AND r.status IN ('running', 'succeeded')"
                ")"
            ),
            {"cutoff": cutoff},
        ).all()
    return [r[0] for r in rows]


def run_once(
    *,
    tenant_id: uuid.UUID,
    model: TrainedModel,
    model_version: str,
    tenant_config: dict,
    as_of: datetime,
    transport: Transport,
    worker_id: str,
    lease_seconds: int,
) -> CycleResult | None:
    """Claim the lease, run exactly one cycle for this tenant, release.
    Returns ``None`` if the lease could not be claimed (another worker
    already holds it, or it isn't due)."""
    with owner_session() as lease_s:
        claimed = lease.claim(
            lease_s, kind=LEASE_KIND, key=str(tenant_id), owner=worker_id,
            lease_seconds=lease_seconds, now=as_of,
        )
    if not claimed:
        return None

    try:
        with tenant_session(tenant_id) as s:
            result = run_cycle(
                s, tenant_id=tenant_id, model=model, model_version=model_version,
                tenant_config=tenant_config, as_of=as_of, transport=transport,
            )
        with owner_session() as lease_s:
            lease.release(lease_s, kind=LEASE_KIND, key=str(tenant_id))
        return result
    except Exception as exc:
        with owner_session() as lease_s:
            lease.release(lease_s, kind=LEASE_KIND, key=str(tenant_id), error=str(exc))
        raise


@dataclass(frozen=True, slots=True)
class TenantRuntime:
    """What a tick needs per tenant to actually run a cycle -- supplied by
    the caller (a real scheduler loads the promoted model and tenant_config
    once per tick; a test constructs this directly)."""

    tenant_id: uuid.UUID
    model: TrainedModel
    model_version: str
    tenant_config: dict
    transport: Transport


def tick(
    runtimes: list[TenantRuntime], *, clock: Clock, worker_id: str, lease_seconds: int,
    cycle_interval_minutes: int,
) -> list[CycleResult]:
    now = clock.now()
    due = set(due_tenants(now, cycle_interval_minutes=cycle_interval_minutes))
    results = []
    for rt in runtimes:
        if rt.tenant_id not in due:
            continue
        result = run_once(
            tenant_id=rt.tenant_id, model=rt.model, model_version=rt.model_version,
            tenant_config=rt.tenant_config, as_of=now, transport=rt.transport,
            worker_id=worker_id, lease_seconds=lease_seconds,
        )
        if result is not None:
            results.append(result)
    return results


def serve(runtimes: list[TenantRuntime], *, clock: Clock | None = None) -> None:  # pragma: no cover
    """The real, infinite loop. Not exercised by the test suite -- it has no
    decision logic beyond calling ``tick`` on a timer."""
    clock = clock or SystemClock()
    settings = get_settings()
    while True:
        tick(
            runtimes, clock=clock, worker_id=settings.worker_id,
            lease_seconds=settings.lease_seconds,
            cycle_interval_minutes=settings.cycle_interval_minutes,
        )
        time.sleep(settings.worker_tick_seconds)
