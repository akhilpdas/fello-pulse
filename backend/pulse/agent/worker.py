"""The tick loop (T066): for every tenant due for a cycle, claim its lease,
run one cycle, release the lease. Crash-safe -- a worker that dies mid-cycle
leaves an expired lease a later tick reclaims (T068) -- and overlap-safe --
two workers racing for the same tenant's lease, only one wins (T069).

``run_once`` is the unit a test or a single scheduler tick calls for one
tenant. ``tick`` is the loop over every due tenant; ``serve`` is the unattended
``sleep``-driven loop around it (``pulse serve``), with no decision logic of its own.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Callable
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
log = logging.getLogger(__name__)


def due_tenants(now: datetime, *, cycle_interval_minutes: int) -> list[uuid.UUID]:
    """Tenants with no running or succeeded run started within the interval.
    A tenant whose last run *failed* is due again immediately -- a failure
    must not silently gate the next attempt behind the same cooldown as a
    healthy cycle. Recency is judged on ``as_of`` -- the injected clock's own domain -- not on
    the wall-clock ``started_at``, so a simulated or frozen clock gates correctly."""
    cutoff = now - timedelta(minutes=cycle_interval_minutes)
    with owner_session() as s:
        rows = s.execute(
            text(
                "SELECT t.id FROM tenant t WHERE NOT EXISTS ("
                "  SELECT 1 FROM agent_run r WHERE r.tenant_id = t.id"
                "    AND r.as_of > :cutoff AND r.status IN ('running', 'succeeded')"
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
            settings = get_settings()
            result = run_cycle(
                s, tenant_id=tenant_id, model=model, model_version=model_version,
                tenant_config=tenant_config, as_of=as_of, transport=transport,
                llm_enabled=settings.llm_enabled, llm_api_key=settings.llm_api_key,
            )
        with owner_session() as lease_s:
            lease.release(lease_s, kind=LEASE_KIND, key=str(tenant_id))
        return result
    except Exception as exc:
        with owner_session() as lease_s:
            lease.release(lease_s, kind=LEASE_KIND, key=str(tenant_id), error=str(exc))
        # The cycle is one transaction, so its own 'running' row rolled back with the failure.
        # Record the failure separately: a run that left no trace is the worst kind.
        _record_failed_run(tenant_id, as_of, f"{type(exc).__name__}: {exc}")
        raise


def _record_failed_run(tenant_id: uuid.UUID, as_of: datetime, error: str) -> None:
    with owner_session() as s:
        s.execute(
            text(
                "INSERT INTO agent_run (id, tenant_id, trigger, started_at, finished_at, status, as_of,"
                " stage_counts, decisions_declined, errors) VALUES (:i, :t, 'schedule', now(), now(),"
                " 'failed', :ao, '{}'::jsonb, '[]'::jsonb, CAST(:e AS jsonb))"
            ),
            {"i": uuid.uuid4(), "t": tenant_id, "ao": as_of, "e": json.dumps([{"error": error}])},
        )


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


def build_runtime(
    tenant_id: uuid.UUID, *, model: TrainedModel, model_version: str, transport: Transport
) -> TenantRuntime:
    """A tenant's runtime from its own ``tenant_config`` row."""
    with owner_session() as s:
        row = s.execute(
            text(
                "SELECT connected_sources, min_days_history, min_sources_with_data, tier_red_at,"
                " tier_amber_at, material_delta, suppression_days, max_sends_per_cycle"
                " FROM tenant_config WHERE tenant_id = :t"
            ),
            {"t": tenant_id},
        ).one()
    cfg = {
        "connected_sources": frozenset(row[0]), "min_days_history": row[1],
        "min_sources_with_data": row[2], "tier_red_at": float(row[3]), "tier_amber_at": float(row[4]),
        "material_delta": float(row[5]), "suppression_days": row[6], "max_sends_per_cycle": row[7],
    }
    return TenantRuntime(tenant_id=tenant_id, model=model, model_version=model_version,
                         tenant_config=cfg, transport=transport)


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
        try:
            result = run_once(
                tenant_id=rt.tenant_id, model=rt.model, model_version=rt.model_version,
                tenant_config=rt.tenant_config, as_of=now, transport=rt.transport,
                worker_id=worker_id, lease_seconds=lease_seconds,
            )
        except Exception:
            # Already recorded as a failed run by run_once; one tenant's failure must not
            # starve the tenants behind it or kill the worker.
            log.exception("cycle failed for tenant %s", rt.tenant_id)
            continue
        if result is not None:
            results.append(result)
    return results


def serve(
    runtimes: list[TenantRuntime], *, clock: Clock | None = None,
    sleep: Callable[[float], None] = time.sleep, max_ticks: int | None = None,
) -> None:
    """The unattended loop: tick, sleep, repeat. No decision logic of its own -- which tenants
    are due, and whether a cycle may start, is ``tick``'s and the lease's business.
    ``max_ticks`` and ``sleep`` exist so the loop can be run under test."""
    clock = clock or SystemClock()
    settings = get_settings()
    ticks = 0
    while max_ticks is None or ticks < max_ticks:
        tick(
            runtimes, clock=clock, worker_id=settings.worker_id,
            lease_seconds=settings.lease_seconds,
            cycle_interval_minutes=settings.cycle_interval_minutes,
        )
        ticks += 1
        if max_ticks is None or ticks < max_ticks:
            sleep(settings.worker_tick_seconds)
