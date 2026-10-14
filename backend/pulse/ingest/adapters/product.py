from __future__ import annotations

from typing import Any

from pulse.ingest.adapters.base import Adapter


class ProductAdapter(Adapter):
    source = "product"

    TYPE_MAP = {
        "usage.weekly_rollup": "product.usage_rollup",
        "usage.daily_rollup": "product.usage_rollup",
        "feature.first_used": "product.feature_first_used",
    }

    def normalize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Guarantee ``period_days`` is present.

        Daily and weekly deliveries normalise to the same internal event, so the
        feature layer never branches on delivery cadence — it divides by
        ``period_days``. A tenant that switches from weekly to daily rollups
        costs nothing, and no feature silently changes meaning when they do.
        """
        out = dict(payload)
        if "period_days" not in out:
            out["period_days"] = 7 if "daily" in out else 1
        return out
