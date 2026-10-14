from __future__ import annotations

from pulse.ingest.adapters.base import Adapter


class SalesforceAdapter(Adapter):
    source = "salesforce"

    # Keys are lowercased before lookup, which is what absorbs the mid-2024
    # recasing of Account.updated -> Account.Updated. Matching on the exact
    # string would have silently dropped every record after the cutover.
    TYPE_MAP = {
        "account.updated": "crm.account_updated",
        "account.owner_changed": "crm.owner_changed",
        "opportunity.stage_changed": "crm.opportunity_stage_changed",
        "task.logged": "crm.meeting_logged",
        "opportunity.closed_lost": "crm.closed_lost",
    }

    # 'plan' was renamed 'plan_name' at the start of 2025. Both spellings exist
    # in the history; one internal name comes out.
    FIELD_ALIASES = {"plan_name": "plan"}
