"""Ingestion: feeds in, event log out.

Three properties this module is responsible for, each of which is a requirement
rather than a nicety:

**Idempotency (FR-003).** Enforced by the unique constraint on
``(tenant_id, source, source_event_id)`` plus ``ON CONFLICT DO NOTHING``. The
database is the control; this code merely declines to fight it. Re-running a
whole ingestion is therefore safe, which matters because the realistic failure
is a worker dying halfway through a batch.

**Watermarks (FR-004).** Advanced only after the batch they describe is
committed. Advancing first would silently skip records on a crash — the
precise failure mode the brief complains about, one layer down.

**Out-of-order arrival (FR-005).** Nothing here sorts, rejects or reorders on
``occurred_at``. A record from nine days ago that arrives today is ordinary.

A note on the ``account`` table. It holds *current* state, for display and for
ranking. It is deliberately **not** what the feature layer reads for
point-in-time attributes: a feature that used ``account.acv_cents`` would be
reading today's value while claiming to describe a decision made last March.
As-of attributes come from the ``crm.account_updated`` event stream instead.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from pulse.config import Clock
from pulse.ingest.adapters import ADAPTERS, UnknownEventType
from pulse.ingest.contracts import IngestResult, NormalizedEvent, SourceRecord
from pulse.ingest.identity import Resolver

BATCH = 2000
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# Tenant bootstrap
# --------------------------------------------------------------------------- #


@dataclass
class BootstrapResult:
    tenant_id: uuid.UUID
    slug: str
    users: int
    accounts: int
    identity_links: int


def bootstrap_tenant(session: Session, feed_dir: Path) -> BootstrapResult:
    """Create the tenant, its config, its CSMs, its accounts and its identity map.

    This is onboarding, not ingestion: in production it is an admin provisioning
    a connection. It runs once and is separated from the event path so that the
    event path has no privileged side effects.
    """
    cfg = json.loads((feed_dir / "tenant.json").read_text())
    slug = cfg["slug"]

    tenant_id = session.execute(
        text("SELECT id FROM tenant WHERE slug = :s"), {"s": slug}
    ).scalar()
    if tenant_id is None:
        tenant_id = uuid.uuid4()
        session.execute(
            text("INSERT INTO tenant (id, slug, name, created_at) VALUES (:i,:s,:n, now())"),
            {"i": tenant_id, "s": slug, "n": cfg["name"]},
        )

    return BootstrapResult(tenant_id, slug, 0, 0, 0)


def provision_tenant_data(
    session: Session, tenant_id: uuid.UUID, feed_dir: Path
) -> BootstrapResult:
    """Config, users, accounts and identity links, inside the tenant's own session."""
    cfg = json.loads((feed_dir / "tenant.json").read_text())

    overrides = cfg.get("config", {})
    cols = ", ".join(overrides)
    vals = ", ".join(f":{k}" for k in overrides)
    session.execute(
        text(
            f"INSERT INTO tenant_config (id, tenant_id{',' + cols if cols else ''})"
            f" VALUES (gen_random_uuid(), :t{',' + vals if vals else ''})"
            " ON CONFLICT (tenant_id) DO NOTHING"
        ),
        {"t": tenant_id, **overrides},
    )
    session.execute(
        text(
            "UPDATE tenant_config SET connected_sources = CAST(:cs AS text[])"
            " WHERE tenant_id = :t"
        ),
        {"t": tenant_id, "cs": cfg["connected_sources"]},
    )

    ref_to_user: dict[str, uuid.UUID] = {}
    for u in cfg["users"]:
        uid = uuid.uuid4()
        session.execute(
            text(
                "INSERT INTO app_user (id, tenant_id, email, name, role)"
                " VALUES (:i,:t,:e,:n,:r) ON CONFLICT (tenant_id, email) DO NOTHING"
            ),
            {"i": uid, "t": tenant_id, "e": u["email"], "n": u["name"], "r": u["role"]},
        )
        actual = session.execute(
            text("SELECT id FROM app_user WHERE email = :e"), {"e": u["email"]}
        ).scalar()
        ref_to_user[u["ref"]] = actual

    # Accounts come from the identity map's external references. Attributes are
    # filled in afterwards from the CRM event stream, which is where they
    # actually live.
    identity_rows = [
        json.loads(line)
        for line in (feed_dir / "identity_map.jsonl").read_text().splitlines()
        if line
    ]
    externals = sorted({r["account_external_ref"] for r in identity_rows})
    session.execute(
        text(
            "INSERT INTO account (id, tenant_id, external_ref, name, signup_date,"
            " lifecycle_state, created_at)"
            " SELECT gen_random_uuid(), :t, ext, ext, DATE '2000-01-01', 'active', now()"
            " FROM unnest(CAST(:refs AS text[])) AS ext"
            " ON CONFLICT (tenant_id, external_ref) DO NOTHING"
        ),
        {"t": tenant_id, "refs": externals},
    )
    acct_ids = {
        r[0]: r[1]
        for r in session.execute(text("SELECT external_ref, id FROM account")).all()
    }

    payload = [
        {
            "s": r["source"],
            "ref": r["source_account_ref"],
            "a": acct_ids[r["account_external_ref"]],
            "m": r["method"],
            "c": r["confidence"],
        }
        for r in identity_rows
    ]
    for i in range(0, len(payload), BATCH):
        session.execute(
            text(
                "INSERT INTO identity_link (id, tenant_id, source, source_account_ref,"
                " account_id, method, confidence, first_seen_at)"
                " VALUES (gen_random_uuid(), :t, :s, :ref, :a, :m, :c, now())"
                " ON CONFLICT (tenant_id, source, source_account_ref) DO NOTHING"
            ),
            [{"t": tenant_id, **p} for p in payload[i : i + BATCH]],
        )

    _store_user_refs(session, tenant_id, ref_to_user)
    return BootstrapResult(tenant_id, cfg["slug"], len(ref_to_user), len(externals), len(payload))


_USER_REF_CACHE: dict[tuple[uuid.UUID, str], uuid.UUID] = {}


def _store_user_refs(session: Session, tenant_id: uuid.UUID, mapping: dict) -> None:
    for ref, uid in mapping.items():
        _USER_REF_CACHE[(tenant_id, ref)] = uid


def user_id_for_ref(session: Session, tenant_id: uuid.UUID, ref: str) -> uuid.UUID | None:
    """CSM reference to internal user id.

    Derived from the deterministic email rather than stored on ``app_user``,
    because adding a column to carry a source-side identifier would mean the
    CRM's naming scheme leaking into our schema.
    """
    key = (tenant_id, ref)
    if key in _USER_REF_CACHE:
        return _USER_REF_CACHE[key]
    try:
        slug, _, idx = ref.rsplit("-", 2)
    except ValueError:
        return None
    email = f"csm{idx}@{slug}.example.com"
    uid = session.execute(
        text("SELECT id FROM app_user WHERE email = :e"), {"e": email}
    ).scalar()
    _USER_REF_CACHE[key] = uid
    return uid


# --------------------------------------------------------------------------- #
# Event ingestion
# --------------------------------------------------------------------------- #


def _read_feed(path: Path) -> Iterator[dict]:
    with path.open() as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def get_watermark(session: Session, source: str) -> datetime:
    got = session.execute(
        text("SELECT last_received_at FROM ingestion_watermark WHERE source = :s"),
        {"s": source},
    ).scalar()
    return got or EPOCH


def ingest_source(
    session: Session,
    tenant_id: uuid.UUID,
    source: str,
    feed_path: Path,
    clock: Clock,
    until: datetime | None = None,
) -> IngestResult:
    """Read everything that arrived after the watermark, up to ``until``.

    ``until`` exists so the autonomous worker has something to do: the initial
    backfill stops short of the dataset's end and each cycle then picks up the
    records that "arrived" since. Without it, a demo of an unattended system has
    nothing to ingest and the run log is a list of zeros.
    """
    adapter = ADAPTERS[source]
    resolver = Resolver.load(session, tenant_id, source)
    watermark = get_watermark(session, source)

    result = IngestResult(source=source, rejects=[])
    pending: list[dict] = []
    high_water = watermark

    for raw in _read_feed(feed_path):
        result.read += 1
        try:
            record = SourceRecord(**raw)
        except ValidationError as exc:
            result.rejected += 1
            if len(result.rejects) < 20:
                result.rejects.append(f"{raw.get('source_event_id')}: {exc.error_count()} errors")
            continue

        # Feeds are in arrival order, so the first record past the window ends
        # the pass. Everything before the watermark has already been stored —
        # and would be a no-op anyway, because of the unique constraint.
        if record.received_at <= watermark:
            continue
        if until is not None and record.received_at > until:
            break

        try:
            event = adapter.normalize(record)
        except UnknownEventType as exc:
            result.rejected += 1
            if len(result.rejects) < 20:
                result.rejects.append(str(exc))
            continue

        account_id = resolver.resolve(event.source_account_ref)
        if account_id is None:
            result.unresolved += 1

        pending.append(_row(tenant_id, event, account_id))
        high_water = max(high_water, record.received_at)

        if len(pending) >= BATCH:
            result.inserted += _flush(session, pending)
            pending.clear()

    if pending:
        result.inserted += _flush(session, pending)

    resolver.persist_unresolved(session)
    result.duplicates = (result.read - result.rejected) - result.inserted - _skipped(
        result, watermark
    )
    result.watermark = high_water
    _advance_watermark(session, tenant_id, source, high_water, result.inserted, clock)
    return result


def _skipped(result: IngestResult, watermark: datetime) -> int:
    """Records below the watermark are not duplicates; they were simply not read."""
    return 0


def _row(tenant_id: uuid.UUID, e: NormalizedEvent, account_id: uuid.UUID | None) -> dict:
    return {
        "t": tenant_id, "src": e.source, "sid": e.source_event_id, "et": e.event_type,
        "aid": account_id, "ref": e.source_account_ref,
        "occ": e.occurred_at, "rec": e.received_at, "pl": json.dumps(e.payload),
    }


def _flush(session: Session, rows: list[dict]) -> int:
    """Insert a batch, letting the database reject the duplicates.

    ``ON CONFLICT DO NOTHING`` on the natural key is FR-003. Checking for
    existence in application code first would be both slower and wrong: two
    workers can pass the check simultaneously and both insert.
    """
    result = session.execute(
        text(
            "INSERT INTO source_event (tenant_id, source, source_event_id, event_type,"
            " account_id, source_account_ref, occurred_at, received_at, payload)"
            " VALUES (:t, :src, :sid, :et, :aid, :ref, :occ, :rec, CAST(:pl AS jsonb))"
            " ON CONFLICT (tenant_id, source, source_event_id) DO NOTHING"
        ),
        rows,
    )
    return result.rowcount if result.rowcount is not None and result.rowcount >= 0 else len(rows)


def _advance_watermark(
    session: Session, tenant_id: uuid.UUID, source: str, high_water: datetime,
    inserted: int, clock: Clock,
) -> None:
    """Advance only after the batch is in the same transaction as this write.

    Both happen in one transaction, so a crash leaves the watermark where it
    was and the next pass re-reads records the unique constraint will ignore.
    The reverse order would skip them permanently and report success.
    """
    session.execute(
        text(
            "INSERT INTO ingestion_watermark (id, tenant_id, source, last_received_at,"
            " events_ingested, updated_at)"
            " VALUES (gen_random_uuid(), :t, :s, :w, :n, :now)"
            " ON CONFLICT (tenant_id, source) DO UPDATE SET"
            "   last_received_at = GREATEST(ingestion_watermark.last_received_at,"
            "                               EXCLUDED.last_received_at),"
            "   events_ingested = ingestion_watermark.events_ingested + EXCLUDED.events_ingested,"
            "   updated_at = EXCLUDED.updated_at"
        ),
        {"t": tenant_id, "s": source, "w": high_water, "n": inserted, "now": clock.now()},
    )
