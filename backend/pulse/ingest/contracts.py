"""The wire contract for an incoming source record, and its normalised form.

Validation happens at the boundary and nowhere else. Once a record is a
``NormalizedEvent`` the rest of the system can assume both timestamps are
timezone-aware UTC, the event type is from the internal vocabulary, and the
payload is a dict. Anything that fails those checks is rejected here with its
source identifier, rather than becoming a null three layers in.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

SOURCES = frozenset({"salesforce", "gmail", "zendesk", "product", "stripe"})


class SourceRecord(BaseModel):
    """Exactly what a feed line contains. Nothing inferred, nothing defaulted."""

    source_event_id: str = Field(min_length=1, max_length=255)
    source_account_ref: str = Field(min_length=1, max_length=255)
    event_type: str = Field(min_length=1, max_length=96)
    occurred_at: datetime
    received_at: datetime
    payload: dict[str, Any]

    @field_validator("occurred_at", "received_at")
    @classmethod
    def _to_utc(cls, v: datetime) -> datetime:
        """Normalise the offset the source happened to use.

        Five systems write the same instant five ways. Everything downstream
        compares timestamps, so they are converted once, here, and a naive
        datetime is rejected rather than guessed at — assuming a timezone is how
        a point-in-time system acquires an off-by-hours bug that nothing catches.
        """
        if v.tzinfo is None:
            raise ValueError("timestamp has no timezone offset")
        return v.astimezone(UTC)

    @field_validator("received_at")
    @classmethod
    def _not_before_occurrence(cls, v: datetime, info) -> datetime:
        occurred = info.data.get("occurred_at")
        if occurred is not None and v < occurred:
            raise ValueError("received_at precedes occurred_at")
        return v


@dataclass(slots=True)
class NormalizedEvent:
    """A record after its adapter has mapped it into internal vocabulary."""

    source: str
    source_event_id: str
    event_type: str
    source_account_ref: str
    occurred_at: datetime
    received_at: datetime
    payload: dict[str, Any]


@dataclass(slots=True)
class IngestResult:
    source: str
    read: int = 0
    inserted: int = 0
    duplicates: int = 0
    unresolved: int = 0
    rejected: int = 0
    watermark: datetime | None = None
    rejects: list[str] | None = None
