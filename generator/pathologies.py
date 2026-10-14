"""Deliberate data pathologies.

Every pathology here exists because a specific requirement claims to handle it.
The generator is, in effect, the adversary for the ingestion and feature layers:
if a pathology is removed, a test somewhere should stop proving anything.

| Pathology                  | Requirement it tests |
|----------------------------|----------------------|
| Heavy-tailed delivery lag  | FR-005 out-of-order acceptance |
| Write order by received_at | FR-008, SC-009 point-in-time correctness |
| Duplicate delivery         | FR-003 idempotency |
| Backfill burst             | FR-004 watermark advancement |
| Field rename mid-history   | FR-007 schema normalisation |
| Event-type case drift      | FR-007 schema normalisation |
| Mixed UTC offsets          | timestamp normalisation |
| Incomplete identity map    | FR-006 unresolved identity is a state |

The single most important one is the write order. Feeds are written sorted by
``received_at``, not ``occurred_at``, because that is the order a real poller
sees them. Out-of-order arrival is therefore the *default* case in this dataset
rather than an injected anomaly, which is the only way to be confident the
feature layer never quietly filters on the wrong timestamp.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

import numpy as np

from emit import Record

# Per-source delivery lag in minutes: (lognormal mu, sigma). Chosen so the
# medians are plausible and the tails are long — a tail that never produces a
# multi-day delay is not a tail.
LAG_PARAMS = {
    "salesforce": (4.4, 1.5),   # median ~1.4h, tail to days (batch sync)
    "gmail": (3.1, 1.2),        # median ~22m
    "zendesk": (3.6, 1.6),      # median ~36m, webhook retries stretch it
    "product": (5.0, 0.9),      # median ~2.5h, nightly pipeline
    "stripe": (2.4, 1.1),       # median ~11m, near-realtime webhooks
}

# A small share of Zendesk webhooks fail and are replayed days later.
ZENDESK_REPLAY_RATE = 0.04
ZENDESK_REPLAY_DAYS = (1.0, 5.0)

DUPLICATE_RATE = 0.006

# The same instant, written with different offsets by different systems.
OFFSETS = (0, -5, -8, 1, 5.5, -7)

# Field renamed partway through the history.
PLAN_RENAME_AFTER = datetime(2025, 1, 1, tzinfo=UTC)
# Event type recased partway through the history.
CASE_DRIFT_AFTER = datetime(2024, 6, 1, tzinfo=UTC)

IDENTITY_GAP_RATE = 0.03


@dataclass
class Delivered:
    """A record as it lands in the feed, now carrying an arrival time."""

    source: str
    source_event_id: str
    event_type: str
    source_account_ref: str
    occurred_at: datetime
    received_at: datetime
    payload: dict


def _offset_isoformat(dt: datetime, rng: np.random.Generator) -> str:
    """Serialise the same instant under a randomly chosen UTC offset."""
    hours = float(rng.choice(OFFSETS))
    tz = timezone(timedelta(hours=hours))
    return dt.astimezone(tz).isoformat()


def apply_lag(
    records: list[Record], rng: np.random.Generator, backfill: dict | None = None
) -> list[Delivered]:
    """Assign arrival times, then duplicate, drift and recase a sample."""
    out: list[Delivered] = []
    for r in records:
        mu, sigma = LAG_PARAMS[r.source]
        lag_min = float(np.clip(rng.lognormal(mu, sigma), 1.0, 60 * 24 * 9))
        received = r.occurred_at + timedelta(minutes=lag_min)

        if r.source == "zendesk" and rng.random() < ZENDESK_REPLAY_RATE:
            received = received + timedelta(
                days=float(rng.uniform(*ZENDESK_REPLAY_DAYS))
            )

        # A source connected late backfills its history in one batch. The
        # watermark must advance past the batch without the ingestion layer
        # reading the arrival spike as customer behaviour.
        if backfill and r.source == backfill["source"] and r.occurred_at < backfill["before"]:
            if r.occurred_at < backfill["earliest_kept"]:
                continue  # that history simply does not exist for this tenant
            received = backfill["batch_at"]

        payload = _drift_payload(r, rng)
        event_type = _drift_event_type(r)

        out.append(
            Delivered(r.source, r.source_event_id, event_type, r.source_account_ref,
                      r.occurred_at, received, payload)
        )

        # Duplicate delivery: identical natural key, later arrival. Ingestion
        # must store it once and count it once.
        if rng.random() < DUPLICATE_RATE:
            dup_received = received + timedelta(minutes=float(rng.uniform(5, 2880)))
            out.append(
                Delivered(r.source, r.source_event_id, event_type, r.source_account_ref,
                          r.occurred_at, dup_received, copy.deepcopy(payload))
            )
    return out


def _drift_payload(r: Record, rng: np.random.Generator) -> dict:
    """Rename ``plan`` to ``plan_name`` for records after the cutover.

    Both spellings therefore exist in the history and the adapter must map them
    to one internal field. A feature that reads ``plan`` directly silently loses
    two years of the dataset — and would do so without raising anything.
    """
    payload = dict(r.payload)
    if "plan" in payload and r.occurred_at >= PLAN_RENAME_AFTER:
        payload["plan_name"] = payload.pop("plan")
    return payload


def _drift_event_type(r: Record) -> str:
    """Salesforce recased its event names partway through the history."""
    if r.source == "salesforce" and r.occurred_at >= CASE_DRIFT_AFTER:
        if r.event_type == "Account.updated":
            return "Account.Updated"
    return r.event_type


def to_feed_rows(
    delivered: list[Delivered], rng: np.random.Generator
) -> list[dict]:
    """Serialise, sorted by arrival.

    Sorting by ``received_at`` is the whole point. A feed sorted by
    ``occurred_at`` would let a feature layer that filters on the wrong column
    pass every test by accident.
    """
    delivered.sort(key=lambda d: (d.received_at, d.source_event_id))
    rows = []
    for d in delivered:
        rows.append(
            {
                "source_event_id": d.source_event_id,
                "source_account_ref": d.source_account_ref,
                "event_type": d.event_type,
                "occurred_at": _offset_isoformat(d.occurred_at, rng),
                "received_at": _offset_isoformat(d.received_at, rng),
                "payload": d.payload,
            }
        )
    return rows


def build_identity_map(accounts, sources, rng: np.random.Generator) -> list[dict]:
    """The mapping table that joins five identifier schemes — incomplete.

    About 3% of (account, source) pairs are missing. Those source identifiers
    will arrive with events and resolve to nothing. The requirement is that they
    are stored as *unresolved* and surfaced, not silently dropped and not used to
    conjure a second account — because a phantom account is worse than a visible
    gap.
    """
    attr = {
        "salesforce": "sf_ref", "zendesk": "zd_ref", "stripe": "stripe_ref",
        "gmail": "gmail_domain", "product": "product_ref",
    }
    rows = []
    for a in accounts:
        for src in sources:
            if rng.random() < IDENTITY_GAP_RATE:
                continue
            rows.append(
                {
                    "source": src,
                    "source_account_ref": getattr(a, attr[src]),
                    "account_external_ref": a.external_ref,
                    "method": "mapping_table",
                    "confidence": 1.0,
                }
            )
    return rows
