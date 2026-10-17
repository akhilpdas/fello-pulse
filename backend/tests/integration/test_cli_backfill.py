"""``pulse backfill --weeks N``: score weekly history before each tenant's newest snapshot.

Names the production change that makes it fail: ``cli.cmd_backfill`` and the ``backfill`` subcommand.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

import pulse.cli as cli
import pulse.ml.pipeline as pipeline
from pulse.db.session import owner_session, tenant_session
from pulse.scoring.service import score_and_persist
from tests.integration._agent_fixtures import seed_account, seed_tenant, toy_support_model

ANCHOR = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def _as_ofs(tenant_id):
    with owner_session() as s:
        return [r[0] for r in s.execute(text("SELECT DISTINCT as_of FROM score WHERE tenant_id = :t ORDER BY 1"),
                                        {"t": tenant_id}).all()]


def test_backfills_each_tenant_from_its_own_newest_snapshot_and_skips_a_tenant_never_scored(monkeypatch, capsys):
    model = toy_support_model(3)
    scored, cfg = seed_tenant(ANCHOR)
    unscored, _ = seed_tenant(ANCHOR)
    with owner_session() as s:
        a = seed_account(s, scored, ANCHOR, "cli-bf", n_tickets=8)
        seed_account(s, unscored, ANCHOR, "cli-none", n_tickets=8)
    with tenant_session(scored) as s:
        score_and_persist(s, tenant_id=scored, account_id=a, model=model, model_version="t",
                          tenant_config=cfg, as_of=ANCHOR)
    monkeypatch.setattr(cli, "_load_promoted", lambda artifacts: (model, "t"))
    monkeypatch.setattr(pipeline, "trainable_tenants", lambda s: [(scored, "scored"), (unscored, "unscored")])

    assert cli.cmd_backfill(argparse.Namespace(weeks=2, artifacts="x")) == 0

    assert _as_ofs(scored) == [ANCHOR - timedelta(days=14), ANCHOR - timedelta(days=7), ANCHOR]
    assert _as_ofs(unscored) == []  # nothing to anchor on: not guessed, not invented
    out = capsys.readouterr().out
    assert "scored" in out and "unscored" in out and "no snapshot" in out
