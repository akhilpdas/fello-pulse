"""T286 (FR-029): when a human edits a draft, what the system (or the model) originally wrote is kept alongside
the edit -- once, from the first edit -- so "what did the model write and what did the CSM change?" is answerable.

Names the production change that makes it fail: ``edit_action`` recording ``original_subject`` / ``original_body``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import text

from pulse.api.main import app
from pulse.db.session import owner_session
from tests.auth_helpers import auth_headers
from tests.integration._agent_fixtures import seed_account, seed_tenant

AS_OF = datetime(2026, 10, 1, tzinfo=UTC)


def _draft():
    tenant_id, _ = seed_tenant(AS_OF)
    action_id = uuid.uuid4()
    with owner_session() as s:
        acct = seed_account(s, tenant_id, AS_OF, "edit-a", n_tickets=1)
        s.execute(text("INSERT INTO action (id, tenant_id, account_id, play_key, subject, body, draft_source, draft_model)"
                       " VALUES (:i,:t,:a,'support_recovery','Model subject','Model body','llm','claude-sonnet-5-5')"),
                  {"i": action_id, "t": tenant_id, "a": acct})
    return tenant_id, action_id


def test_the_first_edit_preserves_the_original_and_later_edits_do_not_overwrite_it():
    tenant_id, action_id = _draft()
    c, h = TestClient(app), auth_headers(tenant_id)
    first = c.patch(f"/actions/{action_id}", json={"subject": "Human subject", "body": "Human body"}, headers=h).json()
    assert (first["subject"], first["body"]) == ("Human subject", "Human body")
    assert (first["original_subject"], first["original_body"]) == ("Model subject", "Model body")
    second = c.patch(f"/actions/{action_id}", json={"body": "Human body, second pass"}, headers=h).json()
    assert second["body"] == "Human body, second pass"
    assert (second["original_subject"], second["original_body"]) == ("Model subject", "Model body")  # still the first original
    assert second["draft_source"] == "llm" and second["draft_model"] == "claude-sonnet-5-5"


def test_an_unedited_draft_has_no_original_recorded():
    tenant_id, action_id = _draft()
    rows = TestClient(app).get("/actions", headers=auth_headers(tenant_id)).json()["rows"]
    assert rows[0]["original_subject"] is None and rows[0]["original_body"] is None
