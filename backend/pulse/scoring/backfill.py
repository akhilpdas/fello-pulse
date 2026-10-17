"""Backfill weekly score snapshots before an anchor date, so a queue has history to browse and compare.

Scores only: nothing here drafts, sends or records an agent run for a past date -- those are the agent's decisions and
belong to the moment they were made. Idempotent (``score_and_persist`` upserts on ``(tenant, account, as_of)``).

Honest limitation: the model was trained on these same weeks, so a backfilled score is in-sample and looks better than
the model would have looked at the time. It is for browsing and comparing, not for evaluating the model.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from pulse.ml.train import TrainedModel
from pulse.scoring.service import score_and_persist

_WEEK = timedelta(days=7)


def backfill_snapshots(
    session: Session, *, tenant_id: uuid.UUID, model: TrainedModel, model_version: str,
    tenant_config: dict, anchor: datetime, weeks: int,
) -> dict[datetime, int]:
    """Score the accounts that existed at each of the ``weeks`` weekly points before ``anchor``.
    Returns ``{as_of: accounts scored}``."""
    scored: dict[datetime, int] = {}
    for k in range(1, weeks + 1):
        as_of = anchor - k * _WEEK
        account_ids = [r[0] for r in session.execute(
            text("SELECT id FROM account WHERE tenant_id = :t AND signup_date <= :d"
                 " AND (churned_at IS NULL OR churned_at > :as_of) ORDER BY id"),
            {"t": tenant_id, "d": as_of.date(), "as_of": as_of},
        ).all()]
        for account_id in account_ids:
            score_and_persist(session, tenant_id=tenant_id, account_id=account_id, model=model,
                              model_version=model_version, tenant_config=tenant_config, as_of=as_of)
        scored[as_of] = len(account_ids)
    return scored
