"""Backfilling weekly score snapshots so the queue has history (gap found 2026-10-17: a fresh demo has one snapshot,
so "change since last cycle", "what moved" and any week picker have nothing to show).

Names the production change that makes these fail: ``pulse.scoring.backfill.backfill_snapshots``.

Backfill writes *scores only*. It must never draft, send, or record a run for a past date -- those are the agent's
decisions and they belong to the moment they were made.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from pulse.db.session import owner_session, tenant_session
from pulse.scoring.backfill import backfill_snapshots
from pulse.scoring.service import score_and_persist
from tests.integration._agent_fixtures import seed_account, seed_tenant, toy_support_model

ANCHOR = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
WEEK = timedelta(days=7)


@pytest.fixture
def world():
    tenant_id, cfg = seed_tenant(ANCHOR)
    with owner_session() as s:
        accounts = [seed_account(s, tenant_id, ANCHOR, f"bf{i}", n_tickets=8) for i in range(3)]
    model = toy_support_model(3)
    with tenant_session(tenant_id) as s:  # the "current" snapshot a cycle already wrote
        for a in accounts:
            score_and_persist(s, tenant_id=tenant_id, account_id=a, model=model, model_version="t",
                              tenant_config=cfg, as_of=ANCHOR)
    return {"tenant": tenant_id, "cfg": cfg, "accounts": accounts, "model": model}


def _run(w, weeks=3):
    with tenant_session(w["tenant"]) as s:
        return backfill_snapshots(s, tenant_id=w["tenant"], model=w["model"], model_version="t",
                                  tenant_config=w["cfg"], anchor=ANCHOR, weeks=weeks)


def _as_ofs(tenant_id):
    with owner_session() as s:
        return [r[0] for r in s.execute(text("SELECT DISTINCT as_of FROM score WHERE tenant_id = :t ORDER BY 1"),
                                        {"t": tenant_id}).all()]


def test_writes_one_snapshot_per_week_before_the_anchor(world):
    _run(world, weeks=3)
    assert _as_ofs(world["tenant"]) == [ANCHOR - 3 * WEEK, ANCHOR - 2 * WEEK, ANCHOR - WEEK, ANCHOR]


def test_returns_how_many_accounts_were_scored_per_snapshot(world):
    assert _run(world, weeks=2) == {ANCHOR - WEEK: 3, ANCHOR - 2 * WEEK: 3}


def test_is_idempotent(world):
    _run(world, weeks=3)
    with owner_session() as s:
        before = s.execute(text("SELECT count(*) FROM score WHERE tenant_id = :t"), {"t": world["tenant"]}).scalar()
    _run(world, weeks=3)
    with owner_session() as s:
        after = s.execute(text("SELECT count(*) FROM score WHERE tenant_id = :t"), {"t": world["tenant"]}).scalar()
    assert before == after == 3 * 4


def test_leaves_the_current_snapshot_untouched(world):
    with owner_session() as s:
        before = s.execute(text("SELECT id, probability FROM score WHERE tenant_id = :t AND as_of = :a ORDER BY id"),
                           {"t": world["tenant"], "a": ANCHOR}).all()
    _run(world)
    with owner_session() as s:
        after = s.execute(text("SELECT id, probability FROM score WHERE tenant_id = :t AND as_of = :a ORDER BY id"),
                          {"t": world["tenant"], "a": ANCHOR}).all()
    assert before == after


def test_never_drafts_sends_or_records_a_run(world):
    _run(world)
    with owner_session() as s:
        for table in ("action", "agent_run"):
            n = s.execute(text(f"SELECT count(*) FROM {table} WHERE tenant_id = :t"), {"t": world["tenant"]}).scalar()
            assert n == 0, table


def test_an_account_is_not_scored_before_it_signed_up(world):
    late = world["accounts"][0]
    with owner_session() as s:
        s.execute(text("UPDATE account SET signup_date = :d WHERE id = :a"),
                  {"d": (ANCHOR - 10 * timedelta(days=1)).date(), "a": late})
    counts = _run(world, weeks=2)
    assert counts == {ANCHOR - WEEK: 3, ANCHOR - 2 * WEEK: 2}  # signed up 10 days ago: present 1 week back, not 2


def test_an_account_that_churned_later_is_still_in_the_earlier_snapshots(world):
    churned = world["accounts"][1]
    with owner_session() as s:
        s.execute(text("UPDATE account SET lifecycle_state = 'churned', churned_at = :c WHERE id = :a"),
                  {"c": ANCHOR - 10 * timedelta(days=1), "a": churned})
    counts = _run(world, weeks=2)
    assert counts == {ANCHOR - WEEK: 2, ANCHOR - 2 * WEEK: 3}  # gone 10 days ago: absent 1 week back, present 2


def test_zero_weeks_does_nothing(world):
    assert _run(world, weeks=0) == {}
