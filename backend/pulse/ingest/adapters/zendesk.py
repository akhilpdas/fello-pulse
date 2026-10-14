from __future__ import annotations

from pulse.ingest.adapters.base import Adapter


class ZendeskAdapter(Adapter):
    source = "zendesk"

    TYPE_MAP = {
        "ticket.created": "support.ticket_created",
        "ticket.first_reply": "support.first_reply",
        "ticket.solved": "support.ticket_solved",
        "ticket.reopened": "support.ticket_reopened",
        "satisfaction.rated": "support.satisfaction_rated",
    }
