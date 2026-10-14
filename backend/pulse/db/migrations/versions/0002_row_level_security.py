"""Row-level security: the tenant isolation control.

Revision ID: 0002_rls
Revises: dcc8c19e6412

Why this is a migration and not application code
------------------------------------------------
Isolation enforced by a `WHERE tenant_id = :t` in every query fails *open*: one
forgotten clause, one raw SQL report, one JOIN that loses the scope, and rows
cross a tenant boundary with no error raised. RLS fails *closed* — the forgotten
clause returns zero rows. For a property whose single failure is a
customer-facing breach, the control belongs in the layer that cannot be bypassed
by forgetting.

Three details here are load-bearing:

1. **FORCE ROW LEVEL SECURITY**, not just ENABLE. Without FORCE, the table owner
   silently bypasses its own policies, so a test run as the owner would pass for
   the wrong reason and prove nothing.

2. **NULLIF(..., '')** before the cast. `current_setting(k, true)` returns NULL
   when unset but an empty string if something set it to ''. Casting '' to uuid
   raises, turning a missing claim into a 500 instead of an empty result. With
   NULLIF, an unset or blank claim yields NULL, `tenant_id = NULL` is NULL, and
   the row is filtered out. Unset therefore means "see nothing", which is the
   correct default.

3. **WITH CHECK as well as USING.** USING governs what you can read; WITH CHECK
   governs what you can write. Without it, a tenant could insert or update a row
   carrying another tenant's id — invisible to them afterwards, but corrupting
   the other tenant's data.

Three roles, deliberately distinct:
  pulse          owner, runs migrations (superuser)
  pulse_app      serves requests, NOBYPASSRLS — the claim is the only way in
  pulse_trainer  BYPASSRLS, used *only* by cross-tenant model training
A separate role for the elevated path means "this code reads across tenants" is
visible in the connection string rather than hidden in a flag, and it is
greppable at review time.
"""

from __future__ import annotations

from alembic import op

revision = "0002_rls"
down_revision = "dcc8c19e6412"
branch_labels = None
depends_on = None

TENANT_SCOPED_TABLES = [
    "tenant_config", "app_user", "account", "identity_link", "source_event",
    "ingestion_watermark", "feature_snapshot", "score", "play_allowlist",
    "agent_run", "action", "suppression", "feedback",
]

GLOBAL_TABLES = ["tenant", "model_version", "work_lease"]

CLAIM = "NULLIF(current_setting('pulse.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pulse_app') THEN
            CREATE ROLE pulse_app LOGIN PASSWORD 'pulse_app'
              NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
          END IF;
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pulse_trainer') THEN
            CREATE ROLE pulse_trainer LOGIN PASSWORD 'pulse_trainer'
              NOSUPERUSER NOCREATEDB NOCREATEROLE BYPASSRLS;
          END IF;
        END
        $$;
        """
    )
    op.execute("GRANT USAGE ON SCHEMA public TO pulse_app, pulse_trainer")

    for table in TENANT_SCOPED_TABLES + GLOBAL_TABLES:
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO pulse_app, pulse_trainer"
        )

    op.execute(
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO pulse_app, pulse_trainer"
    )

    for table in TENANT_SCOPED_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        # FORCE: without it the owner bypasses its own policy and the isolation
        # tests would pass without proving anything.
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
              USING (tenant_id = {CLAIM})
              WITH CHECK (tenant_id = {CLAIM})
            """
        )

    # agent_run carries a nullable tenant_id for the cross-tenant orchestration
    # record. Without this, that row would be invisible to every tenant session
    # including the one that wrote it. Readable by all, writable by none through
    # a tenant claim: the orchestration record is written by the elevated path.
    op.execute(
        """
        CREATE POLICY orchestration_run_visible ON agent_run
          FOR SELECT USING (tenant_id IS NULL)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS orchestration_run_visible ON agent_run")
    for table in TENANT_SCOPED_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
