"""Fixtures for ingestion tests: a throwaway tenant with one account and mapped
zendesk/salesforce references. It is deleted on teardown because ingestion writes
an ingestion_watermark, and a tenant with a watermark is *trainable* -- leaving one
behind would leak test data into the next model training run."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text

from pulse.config import FrozenClock
from pulse.db.session import owner_session, tenant_session
from pulse.ingest.service import ingest_source


@dataclass
class IngestTenant:
    tenant_id: uuid.UUID
    account_id: uuid.UUID
    tmp: Path

    def feed(self, name: str, records: list[dict]) -> Path:
        path = self.tmp / f"{name}.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
        return path

    def ingest(self, source: str, path: Path, until: datetime | None = None):
        with tenant_session(self.tenant_id) as s:
            return ingest_source(s, self.tenant_id, source, path,
                                 FrozenClock(datetime(2026, 10, 1, tzinfo=UTC)), until=until)

    def scalar(self, sql: str, **params):
        with tenant_session(self.tenant_id) as s:
            return s.execute(text(sql), params).scalar()


def record(sid: str, ref: str, etype: str, occurred: str, received: str, payload: dict | None = None) -> dict:
    return {"source_event_id": sid, "source_account_ref": ref, "event_type": etype,
            "occurred_at": occurred, "received_at": received, "payload": payload or {}}


@pytest.fixture
def ingest_tenant(tmp_path):
    tenant_id, account_id = uuid.uuid4(), uuid.uuid4()
    slug = f"ingest-{uuid.uuid4().hex[:8]}"
    with owner_session() as s:
        s.execute(text("INSERT INTO tenant (id, slug, name, created_at) VALUES (:i,:s,:n, now())"),
                  {"i": tenant_id, "s": slug, "n": slug})
        s.execute(text("INSERT INTO tenant_config (id, tenant_id) VALUES (:i,:t)"),
                  {"i": uuid.uuid4(), "t": tenant_id})
        s.execute(text("INSERT INTO account (id, tenant_id, external_ref, name, signup_date,"
                       " lifecycle_state, created_at) VALUES (:i,:t,'acct-1','Acme',DATE '2024-01-01','active', now())"),
                  {"i": account_id, "t": tenant_id})
        for source, ref in (("zendesk", "zd-1"), ("salesforce", "sf-1")):
            s.execute(text("INSERT INTO identity_link (id, tenant_id, source, source_account_ref, account_id,"
                           " method, confidence, first_seen_at) VALUES (:i,:t,:s,:r,:a,'mapping_table',1.0, now())"),
                      {"i": uuid.uuid4(), "t": tenant_id, "s": source, "r": ref, "a": account_id})
    try:
        yield IngestTenant(tenant_id, account_id, tmp_path)
    finally:
        with owner_session() as s:
            s.execute(text("DELETE FROM tenant WHERE id = :i"), {"i": tenant_id})
