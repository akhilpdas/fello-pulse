"""T251 (FR-015, FR-023): the CRM's primary contact lands on the account, the *latest* CRM state wins
(a contact removed in the CRM is not kept alive as a stale address), and an account the CRM has no contact
for stays NULL -- no placeholder, no guess.

Names the production change that makes it fail: ``dimension.refresh_accounts`` folding
``primary_contact`` into ``account.contact_name`` / ``contact_email``.
"""

from __future__ import annotations

from pulse.db.session import tenant_session
from pulse.ingest.dimension import refresh_accounts
from tests.integration.conftest import record

CONTACT = {"name": "Sofia Reyes", "email": "sofia.reyes@acme.example.com"}


def _account_updated(sid, received, contact):
    return record(sid, "sf-1", "Account.updated", received, received,
                  {"name": "Acme", "segment": "mid", "acv_cents": 100000, "renewal_date": "2027-01-01",
                   "owner_ref": "x-csm-00", "primary_contact": contact})


def _contact_row(t):
    return t.scalar("SELECT contact_name || ' <' || contact_email || '>' FROM account WHERE id = :a", a=t.account_id)


def _refresh(t):
    with tenant_session(t.tenant_id) as s:
        refresh_accounts(s, t.tenant_id)


def test_the_primary_contact_is_stored_on_the_account(ingest_tenant):
    ingest_tenant.ingest("salesforce", ingest_tenant.feed("salesforce", [
        _account_updated("sf-a1", "2026-09-01T09:00:00Z", CONTACT)]))
    _refresh(ingest_tenant)
    assert _contact_row(ingest_tenant) == "Sofia Reyes <sofia.reyes@acme.example.com>"


def test_an_account_the_crm_has_no_contact_for_stays_null_not_a_placeholder(ingest_tenant):
    ingest_tenant.ingest("salesforce", ingest_tenant.feed("salesforce", [
        _account_updated("sf-a1", "2026-09-01T09:00:00Z", None)]))
    _refresh(ingest_tenant)
    assert ingest_tenant.scalar("SELECT contact_email FROM account WHERE id = :a", a=ingest_tenant.account_id) is None


def test_the_latest_crm_state_wins_including_a_contact_that_was_removed(ingest_tenant):
    ingest_tenant.ingest("salesforce", ingest_tenant.feed("salesforce", [
        _account_updated("sf-a1", "2026-08-01T09:00:00Z", CONTACT),
        _account_updated("sf-a2", "2026-09-01T09:00:00Z", None)]))
    _refresh(ingest_tenant)
    assert ingest_tenant.scalar("SELECT contact_email FROM account WHERE id = :a", a=ingest_tenant.account_id) is None
