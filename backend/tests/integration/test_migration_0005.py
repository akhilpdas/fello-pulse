"""T212: migration 0005 adds exactly what specs/002-production-readiness/data-model.md says.

Names the production change that makes it fail: ``0005_auth_delivery_contacts`` and the matching
model changes. Also pins the safe defaults (outbound off, demo mode on) and that every new table is
tenant-scoped with FORCEd row-level security -- a new table without a policy is a cross-tenant leak.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from pulse.db.models import TENANT_SCOPED_TABLES
from pulse.db.session import owner_session

NEW_COLUMNS = {
    "app_user": {"password_hash": ("text", "YES"), "disabled_at": ("timestamp with time zone", "YES"),
                 "password_changed_at": ("timestamp with time zone", "YES")},
    "account": {"contact_name": ("text", "YES"), "contact_email": ("text", "YES")},
    "tenant_config": {"outbound_enabled": ("boolean", "NO"), "sender_address": ("text", "YES"),
                      "sender_verified": ("boolean", "NO"), "demo_mode": ("boolean", "NO"),
                      "test_inbox": ("text", "YES"), "llm_calls_per_cycle": ("integer", "NO")},
    "action": {"redirected_to": ("text", "YES"), "provider_message_id": ("text", "YES"),
               "delivery_error": ("text", "YES"), "original_subject": ("text", "YES"),
               "original_body": ("text", "YES"), "draft_model": ("text", "YES"),
               "draft_fallback_reason": ("text", "YES")},
}
NEW_TABLES = {
    "app_session": {"tenant_id", "user_id", "token_hash", "created_at", "expires_at", "revoked_at",
                    "last_seen_at", "user_agent"},
    "audit_event": {"tenant_id", "at", "actor_user_id", "actor_kind", "event", "subject", "detail"},
    "contact_opt_out": {"tenant_id", "email", "reason", "created_by_user_id", "created_at"},
}


def _columns(table: str) -> dict[str, tuple[str, str]]:
    with owner_session() as s:
        rows = s.execute(text(
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns"
            " WHERE table_schema = 'public' AND table_name = :t"), {"t": table}).all()
    return {r[0]: (r[1], r[2]) for r in rows}


@pytest.mark.parametrize("table", sorted(NEW_COLUMNS))
def test_existing_tables_gain_the_documented_columns(table):
    cols = _columns(table)
    for name, spec in NEW_COLUMNS[table].items():
        assert cols.get(name) == spec, f"{table}.{name}: expected {spec}, found {cols.get(name)}"


@pytest.mark.parametrize("table", sorted(NEW_TABLES))
def test_new_tables_exist_are_tenant_scoped_and_row_level_secured(table):
    cols = _columns(table)
    assert NEW_TABLES[table] <= set(cols), f"{table} missing {NEW_TABLES[table] - set(cols)}"
    assert table in TENANT_SCOPED_TABLES
    with owner_session() as s:
        forced = s.execute(text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :t"),
                           {"t": table}).one()
    assert tuple(forced) == (True, True)


def test_safe_defaults_outbound_off_demo_on():
    with owner_session() as s:
        defaults = dict(s.execute(text(
            "SELECT column_name, column_default FROM information_schema.columns"
            " WHERE table_name = 'tenant_config' AND column_name IN"
            " ('outbound_enabled','sender_verified','demo_mode','llm_calls_per_cycle')")).all())
    assert defaults["outbound_enabled"] == "false"
    assert defaults["sender_verified"] == "false"
    assert defaults["demo_mode"] == "true"
    assert defaults["llm_calls_per_cycle"] == "50"
