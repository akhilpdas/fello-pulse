"""T249 (FR-023): the simulated CRM carries a primary customer contact per account -- and, as in a real
CRM, some accounts have none. Reads the feed files (the data contract the application consumes).

Names the production change that makes it fail: ``generator`` emitting ``primary_contact`` on
``Account.updated`` for ~90% of accounts, deterministically per account.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

FEEDS = Path(os.environ.get("PULSE_FEEDS", "../data/feeds")).resolve()
pytestmark = pytest.mark.skipif(not (FEEDS / "manifest.json").exists(), reason="feeds not generated")


def _contacts(tenant: str) -> dict[str, set]:
    """sf_ref -> every distinct primary_contact (as JSON) seen across that account's refreshes."""
    out: dict[str, set] = {}
    with (FEEDS / tenant / "salesforce.jsonl").open() as fh:
        for line in fh:
            r = json.loads(line)
            if r["event_type"].lower().replace("_", ".") not in ("account.updated",):
                continue
            out.setdefault(r["source_account_ref"], set()).add(json.dumps(r["payload"].get("primary_contact"), sort_keys=True))
    return out


@pytest.mark.parametrize("tenant", ["northwind", "globex", "initech"])
def test_most_accounts_have_a_contact_and_some_realistically_do_not(tenant):
    per_account = _contacts(tenant)
    assert per_account, "no Account.updated records found"
    has = [a for a, seen in per_account.items() if seen != {"null"}]
    share = len(has) / len(per_account)
    assert 0.8 <= share <= 0.97, f"{tenant}: {share:.0%} of accounts have a contact"
    assert len(has) < len(per_account), "every account has a contact: the 'no contact' case is never exercised"


def test_an_accounts_contact_is_stable_across_refreshes_and_well_formed():
    for tenant in ("northwind", "globex", "initech"):
        for ref, seen in _contacts(tenant).items():
            assert len(seen) == 1, f"{ref}: contact changes between refreshes: {seen}"
            (only,) = seen
            if only != "null":
                c = json.loads(only)
                assert c["name"].strip() and "@" in c["email"] and c["email"].endswith(".example.com")
