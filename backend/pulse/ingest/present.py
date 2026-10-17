"""What "now" means for a run on simulated data (clarifications B-30).

A simulated-present run (``pulse cycle`` without ``--as-of``, ``pulse serve --simulate-present``) needs a moment to score
as of. The newest event of *any* source is the wrong choice: one noisy or lagging source runs ahead of the rest, every
other source then looks silent, and every account looks disengaged. "Now" is instead the newest moment **every** source
has reported -- the earliest of each source's newest event -- so a source that runs ahead cannot pull it forward.
Production runs use the wall clock; this is only for data whose present is not the wall clock's.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session


def data_present(session: Session, tenant_ids: Sequence[uuid.UUID]) -> datetime | None:
    """Earliest, across sources, of each source's newest ``received_at`` over the given tenants; ``None`` if no events."""
    if not tenant_ids:
        return None
    return session.execute(
        text("SELECT min(newest) FROM (SELECT max(received_at) AS newest FROM source_event"
             " WHERE tenant_id = ANY(:t) GROUP BY source) per_source"),
        {"t": list(tenant_ids)},
    ).scalar()
