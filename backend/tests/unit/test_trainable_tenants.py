"""The training pipeline must learn only from tenants whose data arrived through
ingestion (they have a watermark). Tenants seeded directly -- test fixtures,
consoles -- must never leak into the production model or its per-tenant report."""

from __future__ import annotations

import uuid

from sqlalchemy import text

from pulse.db.session import elevated_session, owner_session
from pulse.ml.pipeline import trainable_tenants


def _tenant(s, with_watermark: bool) -> str:
    tid, slug = uuid.uuid4(), f"trainsel-{uuid.uuid4().hex[:8]}"
    s.execute(text("INSERT INTO tenant (id, slug, name, created_at) VALUES (:i,:s,:s2, now())"),
              {"i": tid, "s": slug, "s2": slug})
    if with_watermark:
        s.execute(text("INSERT INTO ingestion_watermark (id, tenant_id, source, last_received_at,"
                       " events_ingested) VALUES (:i,:t,'zendesk', now(), 1)"),
                  {"i": uuid.uuid4(), "t": tid})
    return slug


def test_only_tenants_with_an_ingestion_watermark_are_trainable():
    with owner_session() as s:
        ingested, seeded = _tenant(s, True), _tenant(s, False)
    try:
        with elevated_session() as s:
            slugs = {slug for _, slug in trainable_tenants(s)}
        assert ingested in slugs
        assert seeded not in slugs
    finally:  # this fixture has a watermark, so leaving it would train the real model on it
        with owner_session() as s:
            s.execute(text("DELETE FROM tenant WHERE slug IN (:a, :b)"), {"a": ingested, "b": seeded})
