"""T264 (FR-014, FR-004, FR-012): an operator controls whether and how their tenant sends email -- and cannot
switch it on without a verified sender. Changing the sender address revokes verification (and so switches
sending off) because a new address has not been proven to be ours to send from.

Names the production change that makes it fail: ``GET/PATCH /admin/outbound``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import text

from pulse.api.main import app
from pulse.db.session import owner_session
from tests.auth_helpers import auth_headers
from tests.integration._agent_fixtures import seed_tenant

AS_OF = datetime(2026, 10, 1, tzinfo=UTC)


def _tenant():
    tenant_id, _ = seed_tenant(AS_OF)
    return tenant_id, auth_headers(tenant_id), TestClient(app)


def _audit(tenant_id):
    with owner_session() as s:
        return [r[0] for r in s.execute(text("SELECT event FROM audit_event WHERE tenant_id = :t ORDER BY at, id"),
                                        {"t": tenant_id}).all()]


def test_defaults_are_safe_off_unverified_and_demo():
    _, h, c = _tenant()
    body = c.get("/admin/outbound", headers=h).json()
    assert (body["outbound_enabled"], body["sender_verified"], body["demo_mode"]) == (False, False, True)
    assert body["sender_address"] is None and "smtp_configured" in body


def test_a_csm_is_refused():
    tenant_id, _, c = _tenant()
    csm = auth_headers(tenant_id, role="csm")
    assert c.get("/admin/outbound", headers=csm).status_code == 403
    assert c.patch("/admin/outbound", json={"outbound_enabled": True}, headers=csm).status_code == 403


def test_outbound_cannot_be_enabled_without_a_verified_sender():
    tenant_id, h, c = _tenant()
    assert c.patch("/admin/outbound", json={"outbound_enabled": True}, headers=h).status_code == 409
    assert c.patch("/admin/outbound", json={"sender_address": "csm@northwind.example.com",
                                            "outbound_enabled": True}, headers=h).status_code == 409  # not verified
    assert c.patch("/admin/outbound", json={"sender_verified": True}, headers=h).status_code == 409  # no address yet
    ok = c.patch("/admin/outbound", json={"sender_address": "csm@northwind.example.com", "sender_verified": True,
                                          "outbound_enabled": True}, headers=h)
    assert ok.status_code == 200 and ok.json()["outbound_enabled"] is True


def test_changing_the_sender_revokes_verification_and_switches_sending_off():
    tenant_id, h, c = _tenant()
    c.patch("/admin/outbound", json={"sender_address": "a@northwind.example.com", "sender_verified": True,
                                     "outbound_enabled": True}, headers=h)
    after = c.patch("/admin/outbound", json={"sender_address": "b@northwind.example.com"}, headers=h).json()
    assert after["sender_address"] == "b@northwind.example.com"
    assert (after["sender_verified"], after["outbound_enabled"]) == (False, False)


def test_addresses_are_validated_and_unknown_fields_rejected():
    _, h, c = _tenant()
    assert c.patch("/admin/outbound", json={"sender_address": "not-an-email"}, headers=h).status_code == 422
    assert c.patch("/admin/outbound", json={"test_inbox": "also not"}, headers=h).status_code == 422
    assert c.patch("/admin/outbound", json={"tenant_id": "x"}, headers=h).status_code == 422


def test_changes_are_audited_and_one_tenants_change_does_not_touch_another():
    a, ha, c = _tenant()
    b, hb, _ = _tenant()
    c.patch("/admin/outbound", json={"test_inbox": "inbox@pulse.example.com", "demo_mode": False}, headers=ha)
    assert "outbound_changed" in _audit(a) and "outbound_changed" not in _audit(b)
    other = c.get("/admin/outbound", headers=hb).json()
    assert other["test_inbox"] is None and other["demo_mode"] is True
