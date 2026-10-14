from __future__ import annotations

from pulse.ingest.adapters.base import Adapter


class GmailAdapter(Adapter):
    source = "gmail"

    TYPE_MAP = {
        "message.sent": "email.outbound",
        "message.received": "email.inbound",
    }
