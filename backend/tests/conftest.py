"""Shared fixtures.

The isolation tests need two tenants that each have at least one row in *every*
tenant-scoped table, otherwise "no rows of the other tenant were returned" is
satisfied trivially by a table that was empty anyway. ``two_tenants`` therefore
seeds a complete, cross-referenced set for both.
"""

from __future__ import annotations

import os
import subprocess
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from pulse.config import FrozenClock
from pulse.db.models import TENANT_SCOPED_TABLES
from pulse.db.session import dispose_engines, owner_session

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    """Bring the schema to head once per test session."""
    subprocess.run(
        ["python3", "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=BACKEND, check=True, capture_output=True,
        env={**os.environ, "PYTHONPATH": BACKEND},
    )
    yield
    dispose_engines()


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(NOW)


def _seed_tenant(s, slug: str) -> dict:
    """One tenant with one row in every tenant-scoped table."""
    tid = uuid.uuid4()
    s.execute(
        text("INSERT INTO tenant (id, slug, name, created_at) VALUES (:i,:s,:n, now())"),
        {"i": tid, "s": slug, "n": slug.title()},
    )
    s.execute(
        text("INSERT INTO tenant_config (id, tenant_id) VALUES (:i,:t)"),
        {"i": uuid.uuid4(), "t": tid},
    )
    uid = uuid.uuid4()
    s.execute(
        text(
            "INSERT INTO app_user (id, tenant_id, email, name, role)"
            " VALUES (:i,:t,:e,:n,'csm')"
        ),
        {"i": uid, "t": tid, "e": f"csm@{slug}.test", "n": f"CSM {slug}"},
    )
    aid = uuid.uuid4()
    s.execute(
        text(
            "INSERT INTO account (id, tenant_id, external_ref, name, segment, signup_date,"
            " owner_user_id, lifecycle_state, acv_cents, renewal_date, seats, created_at)"
            " VALUES (:i,:t,:r,:n,'mid',:sd,:u,'active',4200000,:rd,42, now())"
        ),
        {"i": aid, "t": tid, "r": f"{slug}-acct-1", "n": f"{slug.title()} Account One",
         "sd": (NOW - timedelta(days=700)).date(), "u": uid,
         "rd": (NOW + timedelta(days=40)).date()},
    )
    s.execute(
        text(
            "INSERT INTO identity_link (id, tenant_id, source, source_account_ref,"
            " account_id, method, confidence, first_seen_at)"
            " VALUES (:i,:t,'stripe',:r,:a,'direct',1.0, now())"
        ),
        {"i": uuid.uuid4(), "t": tid, "r": f"cus_{slug}_1", "a": aid},
    )
    s.execute(
        text(
            "INSERT INTO source_event (tenant_id, source, source_event_id, event_type,"
            " account_id, source_account_ref, occurred_at, received_at, payload)"
            " VALUES (:t,'zendesk',:se,'support.ticket_created',:a,:r,:o,:rc,"
            " CAST(:p AS jsonb))"
        ),
        {"t": tid, "se": f"{slug}-evt-1", "a": aid, "r": f"zd_{slug}_1",
         "o": NOW - timedelta(days=3), "rc": NOW - timedelta(days=2),
         "p": '{"priority": "high"}'},
    )
    s.execute(
        text(
            "INSERT INTO ingestion_watermark (id, tenant_id, source, last_received_at,"
            " events_ingested, updated_at) VALUES (:i,:t,'zendesk',:w, 1, now())"
        ),
        {"i": uuid.uuid4(), "t": tid, "w": NOW - timedelta(days=2)},
    )
    fsid = uuid.uuid4()
    s.execute(
        text(
            "INSERT INTO feature_snapshot (id, tenant_id, account_id, as_of, values,"
            " evidence, coverage, days_of_history, feature_set_version, computed_at)"
            " VALUES (:i,:t,:a,:ao, CAST(:v AS jsonb), CAST(:e AS jsonb),"
            " CAST(:c AS jsonb), 700, 'fs-1', now())"
        ),
        {"i": fsid, "t": tid, "a": aid, "ao": NOW,
         "v": '{"support_tickets_28d": 4}', "e": '{"support_experience": [1]}',
         "c": '{"zendesk": {"has_data": true}}'},
    )
    mv = f"m-test-{slug}"
    s.execute(
        text(
            "INSERT INTO model_version (id, version, algorithm, feature_set_version,"
            " feature_names, trained_at, train_window_start, train_window_end,"
            " horizon_days, seed, data_version, metrics, artifact_path, promoted)"
            " VALUES (:i,:v,'hgb','fs-1', CAST(:fn AS jsonb), now(), :s, :e, 90, 7,"
            " 'dv-test', CAST(:m AS jsonb), '/tmp/x.pkl', true)"
            " ON CONFLICT (version) DO NOTHING"
        ),
        {"i": uuid.uuid4(), "v": mv, "fn": '["support_tickets_28d"]',
         "s": NOW - timedelta(days=400), "e": NOW - timedelta(days=100), "m": "{}"},
    )
    sid = uuid.uuid4()
    s.execute(
        text(
            "INSERT INTO score (id, tenant_id, account_id, as_of, model_version,"
            " feature_snapshot_id, probability, probability_raw, tier, health_score,"
            " confidence, contributions, urgency_multiplier, priority, ranking_math,"
            " created_at) VALUES (:i,:t,:a,:ao,:mv,:fs, 0.42, 0.40, 'red', 38, 'high',"
            " CAST(:co AS jsonb), 1.5, 26460.0, CAST(:rm AS jsonb), now())"
        ),
        {"i": sid, "t": tid, "a": aid, "ao": NOW, "mv": mv, "fs": fsid,
         "co": '{"support_tickets_28d": 0.12}', "rm": '{"p": 0.42}'},
    )
    runid = uuid.uuid4()
    s.execute(
        text(
            "INSERT INTO agent_run (id, tenant_id, trigger, started_at, status, as_of,"
            " stage_counts, decisions_declined, errors)"
            " VALUES (:i,:t,'schedule', now(), 'succeeded', :ao, CAST(:sc AS jsonb),"
            " CAST('[]' AS jsonb), CAST('[]' AS jsonb))"
        ),
        {"i": runid, "t": tid, "ao": NOW, "sc": '{"scored": 1}'},
    )
    s.execute(
        text(
            "INSERT INTO action (id, tenant_id, account_id, score_id, agent_run_id,"
            " play_key, state, channel, subject, body, draft_source, grounding, created_at)"
            " VALUES (:i,:t,:a,:s,:r,'support_recovery','pending_approval','email',"
            " :sub,:b,'template', CAST(:g AS jsonb), now())"
        ),
        {"i": uuid.uuid4(), "t": tid, "a": aid, "s": sid, "r": runid,
         "sub": f"Checking in — {slug}", "b": "body", "g": '{"events": [1]}'},
    )
    s.execute(
        text(
            "INSERT INTO play_allowlist (id, tenant_id, play_key, auto_send,"
            " enabled_by_user_id, enabled_at) VALUES (:i,:t,'adoption_nudge', false,"
            " :u, now())"
        ),
        {"i": uuid.uuid4(), "t": tid, "u": uid},
    )
    s.execute(
        text(
            "INSERT INTO suppression (id, tenant_id, account_id, reason,"
            " created_by_user_id, created_at, expires_at)"
            " VALUES (:i,:t,:a,'deliberate churn',:u, now(), :x)"
        ),
        {"i": uuid.uuid4(), "t": tid, "a": aid, "u": uid, "x": NOW + timedelta(days=30)},
    )
    s.execute(
        text(
            "INSERT INTO feedback (id, tenant_id, account_id, score_id, kind, note,"
            " created_by_user_id, created_at)"
            " VALUES (:i,:t,:a,:s,'false_positive','seasonal dip',:u, now())"
        ),
        {"i": uuid.uuid4(), "t": tid, "a": aid, "s": sid, "u": uid},
    )
    return {"tenant_id": tid, "slug": slug, "account_id": aid, "user_id": uid,
            "score_id": sid, "snapshot_id": fsid, "run_id": runid}


@pytest.fixture
def two_tenants():
    """Two fully-populated tenants, torn down afterwards."""
    a_slug = f"iso-a-{uuid.uuid4().hex[:8]}"
    b_slug = f"iso-b-{uuid.uuid4().hex[:8]}"
    with owner_session() as s:
        a = _seed_tenant(s, a_slug)
        b = _seed_tenant(s, b_slug)
    yield a, b
    with owner_session() as s:
        for t in (a, b):
            s.execute(text("DELETE FROM tenant WHERE id = :i"), {"i": t["tenant_id"]})
            s.execute(
                text("DELETE FROM model_version WHERE version = :v"),
                {"v": f"m-test-{t['slug']}"},
            )


@pytest.fixture
def scoped_tables() -> list[str]:
    return sorted(TENANT_SCOPED_TABLES)
