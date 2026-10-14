"""Per-source adapters.

An adapter's whole job is to absorb a source's spelling so the feature layer
never sees it. Two concrete cases in this dataset:

* Salesforce recased ``Account.updated`` to ``Account.Updated`` in mid-2024.
* ``payload.plan`` became ``payload.plan_name`` at the start of 2025.

Both are invisible failures if unhandled — no error is raised, a feature just
silently loses part of the history. Each adapter declares its mapping as data
and the mapping is covered by a test.
"""

from __future__ import annotations

from pulse.ingest.adapters.base import Adapter, UnknownEventType
from pulse.ingest.adapters.gmail import GmailAdapter
from pulse.ingest.adapters.product import ProductAdapter
from pulse.ingest.adapters.salesforce import SalesforceAdapter
from pulse.ingest.adapters.stripe import StripeAdapter
from pulse.ingest.adapters.zendesk import ZendeskAdapter

ADAPTERS: dict[str, Adapter] = {
    "salesforce": SalesforceAdapter(),
    "gmail": GmailAdapter(),
    "zendesk": ZendeskAdapter(),
    "product": ProductAdapter(),
    "stripe": StripeAdapter(),
}

__all__ = ["ADAPTERS", "Adapter", "UnknownEventType"]
