"""T218 (FR-003, FR-008): sessions are opaque, revocable and expiring; only a hash of the secret is
stored; and the tenant prefix in the token is *untrusted* -- it is used to open the claim under which
the lookup runs, and a forged prefix finds nothing because row-level security hides the real row.

Names the production change that makes it fail: ``pulse.auth.sessions`` and ``pulse.auth.principal``.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from pulse.auth.principal import Principal
from pulse.auth.sessions import create_session, resolve_session, revoke_session
from pulse.db.session import owner_session

NOW = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
TTL = timedelta(hours=12)


def _tenant_with_user(role="csm"):
    tenant_id, user_id = uuid.uuid4(), uuid.uuid4()
    with owner_session() as s:
        s.execute(text("INSERT INTO tenant (id, slug, name, created_at) VALUES (:i,:s,'t', now())"),
                  {"i": tenant_id, "s": f"sess-{uuid.uuid4().hex[:8]}"})
        s.execute(text("INSERT INTO app_user (id, tenant_id, email, name, role)"
                       " VALUES (:i,:t,'u@example.test','U',:r)"), {"i": user_id, "t": tenant_id, "r": role})
    return tenant_id, user_id


def test_token_carries_the_tenant_and_only_a_hash_of_the_secret_is_stored():
    tenant_id, user_id = _tenant_with_user()
    token = create_session(tenant_id, user_id, now=NOW, ttl=TTL)
    prefix, secret = token.split(".", 1)
    assert prefix == str(tenant_id)
    with owner_session() as s:
        rows = s.execute(text("SELECT token_hash, expires_at FROM app_session WHERE user_id = :u"),
                         {"u": user_id}).all()
    assert [r[0] for r in rows] == [hashlib.sha256(secret.encode()).hexdigest()]
    assert rows[0][1] == NOW + TTL
    assert secret not in rows[0][0]


def test_a_valid_token_resolves_to_the_principal_with_the_users_current_role():
    tenant_id, user_id = _tenant_with_user(role="operator")
    token = create_session(tenant_id, user_id, now=NOW, ttl=TTL)
    assert resolve_session(token, now=NOW + timedelta(hours=1)) == Principal(tenant_id, user_id, "operator")


def test_expired_and_revoked_sessions_do_not_resolve():
    tenant_id, user_id = _tenant_with_user()
    token = create_session(tenant_id, user_id, now=NOW, ttl=TTL)
    assert resolve_session(token, now=NOW + TTL + timedelta(seconds=1)) is None
    token2 = create_session(tenant_id, user_id, now=NOW, ttl=TTL)
    assert resolve_session(token2, now=NOW) is not None
    revoke_session(token2)
    assert resolve_session(token2, now=NOW) is None


def test_a_forged_tenant_prefix_with_a_real_secret_finds_nothing():
    a, user_a = _tenant_with_user()
    b, _ = _tenant_with_user()
    real = create_session(a, user_a, now=NOW, ttl=TTL)
    _, secret = real.split(".", 1)
    assert resolve_session(f"{b}.{secret}", now=NOW) is None  # right secret, wrong tenant claim
    assert resolve_session(real, now=NOW) is not None  # control: the genuine token still works


def test_garbage_tokens_resolve_to_none_without_raising():
    for bad in ["", "nodot", "not-a-uuid.secret", f"{uuid.uuid4()}.", f"{uuid.uuid4()}.unknownsecret", "a.b.c"]:
        assert resolve_session(bad, now=NOW) is None
