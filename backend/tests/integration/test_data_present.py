"""B-30: "now" for a simulated-present run is the newest moment *every* source has reported -- not the newest event of
any source. In the demo data a handful of CRM owner-change events run three weeks past the end of everything else, and
``max(received_at)`` took them as "now", so every account looked silent and the newest snapshot flagged 144 red accounts
against 15 the week before.

Names the production change that makes these fail: ``pulse.ingest.present.data_present`` and ``cli`` using it.
"""

from __future__ import annotations

import argparse
import uuid
from datetime import UTC, datetime

from sqlalchemy import text

import pulse.cli as cli
import pulse.ml.pipeline as pipeline
from pulse.agent import worker
from pulse.db.session import owner_session
from pulse.ingest.present import data_present
from tests.integration._agent_fixtures import seed_tenant

NOW = datetime(2026, 10, 1, tzinfo=UTC)


def _events(tenant_id, source, *received):
    with owner_session() as s:
        for i, when in enumerate(received):
            s.execute(
                text("INSERT INTO source_event (tenant_id, source, source_event_id, event_type, source_account_ref,"
                     " occurred_at, received_at, payload) VALUES (:t,:s,:id,'x.y',:r,:o,:o, CAST('{}' AS jsonb))"),
                {"t": tenant_id, "s": source, "id": f"{source}-{uuid.uuid4().hex[:8]}-{i}", "r": f"ref-{i}", "o": when})


def _d(day, month=10):
    return datetime(2026, month, day, 12, 0, tzinfo=UTC)


def test_present_is_the_earliest_of_each_sources_newest_event():
    tenant_id, _ = seed_tenant(NOW)
    _events(tenant_id, "stripe", _d(5), _d(12))
    _events(tenant_id, "product", _d(10), _d(19))          # lags behind the dataset end: legitimate
    _events(tenant_id, "salesforce", _d(12), _d(20, 11))   # a noisy source that runs far ahead
    with owner_session() as s:
        assert data_present(s, [tenant_id]) == _d(12)


def test_a_source_that_runs_ahead_cannot_pull_present_forward():
    tenant_id, _ = seed_tenant(NOW)
    _events(tenant_id, "stripe", _d(12))
    _events(tenant_id, "salesforce", _d(12), _d(30, 11))
    with owner_session() as s:
        assert data_present(s, [tenant_id]) == _d(12)


def test_a_source_with_no_events_is_not_counted():
    tenant_id, _ = seed_tenant(NOW)
    _events(tenant_id, "stripe", _d(12))
    with owner_session() as s:
        assert data_present(s, [tenant_id]) == _d(12)


def test_present_uses_the_newest_across_the_given_tenants_per_source():
    a, _ = seed_tenant(NOW)
    b, _ = seed_tenant(NOW)
    _events(a, "stripe", _d(10))
    _events(b, "stripe", _d(12))
    _events(a, "zendesk", _d(11))
    with owner_session() as s:
        assert data_present(s, [a, b]) == _d(11)   # stripe 12 (best of a,b), zendesk 11 -> earliest is 11


def test_other_tenants_data_is_ignored():
    mine, _ = seed_tenant(NOW)
    other, _ = seed_tenant(NOW)
    _events(mine, "stripe", _d(12))
    _events(other, "stripe", _d(30, 11))
    with owner_session() as s:
        assert data_present(s, [mine]) == _d(12)


def test_no_events_means_no_present():
    tenant_id, _ = seed_tenant(NOW)
    with owner_session() as s:
        assert data_present(s, [tenant_id]) is None


def test_the_cycle_command_runs_as_of_that_present_by_default(monkeypatch):
    tenant_id, _ = seed_tenant(NOW)
    _events(tenant_id, "stripe", _d(12))
    _events(tenant_id, "salesforce", _d(12), _d(9, 11))
    seen = {}
    monkeypatch.setattr(pipeline, "trainable_tenants", lambda s: [(tenant_id, "x")])
    monkeypatch.setattr("pulse.ml.registry.load_promoted_model", lambda p: (object(), "m"))
    monkeypatch.setattr(worker, "build_runtime", lambda tid, **kw: object())
    monkeypatch.setattr(worker, "tick", lambda rts, clock, **kw: seen.update(now=clock.now()) or [])

    assert cli.cmd_cycle(argparse.Namespace(as_of=None, artifacts="x")) == 0
    assert seen["now"] == _d(12)


def test_an_explicit_as_of_still_wins(monkeypatch):
    tenant_id, _ = seed_tenant(NOW)
    _events(tenant_id, "stripe", _d(12))
    seen = {}
    monkeypatch.setattr(pipeline, "trainable_tenants", lambda s: [(tenant_id, "x")])
    monkeypatch.setattr("pulse.ml.registry.load_promoted_model", lambda p: (object(), "m"))
    monkeypatch.setattr(worker, "build_runtime", lambda tid, **kw: object())
    monkeypatch.setattr(worker, "tick", lambda rts, clock, **kw: seen.update(now=clock.now()) or [])
    cli.cmd_cycle(argparse.Namespace(as_of="2026-09-01T00:00:00+00:00", artifacts="x"))
    assert seen["now"] == datetime(2026, 9, 1, tzinfo=UTC)


def test_simulate_present_uses_the_same_definition(monkeypatch):
    tenant_id, _ = seed_tenant(NOW)
    _events(tenant_id, "stripe", _d(12))
    _events(tenant_id, "salesforce", _d(12), _d(9, 11))
    monkeypatch.setattr(pipeline, "trainable_tenants", lambda s: [(tenant_id, "x")])
    assert cli._data_present() == _d(12)

