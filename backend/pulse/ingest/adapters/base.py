from __future__ import annotations

from typing import Any

from pulse.ingest.contracts import NormalizedEvent, SourceRecord


class UnknownEventType(ValueError):
    """A source sent a type we have no mapping for.

    Raised rather than skipped. A source quietly introducing a new event type is
    information — it may be the one that matters — and swallowing it means the
    first anyone hears of it is a feature that stopped moving.
    """


class Adapter:
    source: str = ""
    # source-native type (lowercased) -> internal type
    TYPE_MAP: dict[str, str] = {}
    # payload key aliases -> canonical internal key
    FIELD_ALIASES: dict[str, str] = {}

    def normalize(self, record: SourceRecord) -> NormalizedEvent:
        key = record.event_type.lower()
        internal = self.TYPE_MAP.get(key)
        if internal is None:
            raise UnknownEventType(f"{self.source}: {record.event_type}")
        return NormalizedEvent(
            source=self.source,
            source_event_id=record.source_event_id,
            event_type=internal,
            source_account_ref=record.source_account_ref,
            occurred_at=record.occurred_at,
            received_at=record.received_at,
            payload=self.normalize_payload(record.payload),
        )

    def normalize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.FIELD_ALIASES:
            return payload
        out = dict(payload)
        for alias, canonical in self.FIELD_ALIASES.items():
            if alias in out and canonical not in out:
                out[canonical] = out.pop(alias)
        return out

    def known_types(self) -> set[str]:
        return set(self.TYPE_MAP.values())
