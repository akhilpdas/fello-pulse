from __future__ import annotations

from pulse.ingest.adapters.base import Adapter


class StripeAdapter(Adapter):
    source = "stripe"

    TYPE_MAP = {
        "invoice.paid": "billing.invoice_paid",
        "invoice.payment_failed": "billing.payment_failed",
        "subscription.updated": "billing.subscription_updated",
        "subscription.deleted": "billing.subscription_deleted",
    }

    FIELD_ALIASES = {"plan_name": "plan"}
