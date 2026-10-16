"""T246 (FR-007, FR-009): demo users get a password at provisioning, so a freshly built database can be
signed in to. The password is supplied by the caller (never a constant in the code), is stored only as a
hash, never overwrites a password someone already set, and users provisioned without one cannot sign in.

Names the production change that makes it fail: ``provision_tenant_data(..., demo_password=...)``.
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy import text

from pulse.auth.passwords import hash_password, verify_password
from pulse.db.session import owner_session, tenant_session
from pulse.ingest.service import bootstrap_tenant, provision_tenant_data

DEMO = "demo passphrase for the walkthrough"


def _feed(tmp_path):
    slug = f"demo-{uuid.uuid4().hex[:8]}"
    (tmp_path / "tenant.json").write_text(json.dumps({
        "slug": slug, "name": "Demo Co", "connected_sources": ["zendesk"], "config": {},
        "users": [
            {"ref": f"{slug}-csm-00", "email": f"csm00@{slug}.example.com", "name": "Op", "role": "operator"},
            {"ref": f"{slug}-csm-01", "email": f"csm01@{slug}.example.com", "name": "Cs", "role": "csm"},
        ]}))
    (tmp_path / "identity_map.jsonl").write_text(json.dumps(
        {"source": "zendesk", "source_account_ref": "z1", "account_external_ref": f"{slug}-00000",
         "method": "mapping_table", "confidence": 1.0}) + "\n")
    return slug


def _hashes(tenant_id):
    with owner_session() as s:
        return dict(s.execute(text("SELECT email, password_hash FROM app_user WHERE tenant_id = :t"),
                              {"t": tenant_id}).all())


def _provision(tmp_path, **kw):
    with owner_session() as s:
        res = bootstrap_tenant(s, tmp_path)
    with tenant_session(res.tenant_id) as s:
        provision_tenant_data(s, res.tenant_id, tmp_path, **kw)
    return res.tenant_id


def _cleanup(tenant_id):
    with owner_session() as s:
        s.execute(text("DELETE FROM tenant WHERE id = :i"), {"i": tenant_id})


def test_provisioned_users_can_sign_in_with_the_demo_password_and_it_is_only_stored_hashed(tmp_path):
    _feed(tmp_path)
    tenant_id = _provision(tmp_path, demo_password=DEMO)
    try:
        hashes = _hashes(tenant_id)
        assert len(hashes) == 2
        assert all(h and DEMO not in h and verify_password(DEMO, h) for h in hashes.values())
    finally:
        _cleanup(tenant_id)


def test_without_a_demo_password_users_cannot_sign_in(tmp_path):
    _feed(tmp_path)
    tenant_id = _provision(tmp_path)
    try:
        assert set(_hashes(tenant_id).values()) == {None}
    finally:
        _cleanup(tenant_id)


def test_reprovisioning_fills_missing_passwords_but_never_overwrites_one_someone_set(tmp_path):
    slug = _feed(tmp_path)
    tenant_id = _provision(tmp_path)  # users exist, no passwords
    mine = hash_password("my own chosen passphrase")
    with owner_session() as s:
        s.execute(text("UPDATE app_user SET password_hash = :h WHERE email = :e"),
                  {"h": mine, "e": f"csm01@{slug}.example.com"})
    try:
        with tenant_session(tenant_id) as s:
            provision_tenant_data(s, tenant_id, tmp_path, demo_password=DEMO)
        hashes = _hashes(tenant_id)
        assert hashes[f"csm01@{slug}.example.com"] == mine  # untouched
        assert verify_password(DEMO, hashes[f"csm00@{slug}.example.com"])  # the missing one was filled
    finally:
        _cleanup(tenant_id)
