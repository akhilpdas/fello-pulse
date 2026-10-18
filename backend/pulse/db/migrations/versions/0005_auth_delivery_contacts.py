"""Identity, delivery and contacts (specs/002-production-readiness/data-model.md).

Revision ID: 0005_auth_delivery
Revises: 0004_defaults

Adds credentials to ``app_user``, a customer contact to ``account``, outbound-email settings to
``tenant_config`` (off by default; demo mode on), delivery and draft-provenance columns to
``action``, and three tenant-scoped tables: ``app_session``, ``audit_event`` (append-only for the
application role) and ``contact_opt_out``. Every new table gets the same FORCEd row-level-security
policy as the rest -- a table without one is a cross-tenant leak that fails open.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0005_auth_delivery"
down_revision = "0004_defaults"
branch_labels = None
depends_on = None

NEW_TABLES = ["app_session", "audit_event", "contact_opt_out"]
CLAIM = "NULLIF(current_setting('pulse.tenant_id', true), '')::uuid"


def _tenant_fk() -> sa.Column:
    return sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)


def upgrade() -> None:
    # --- existing tables -------------------------------------------------- #
    op.add_column("app_user", sa.Column("password_hash", sa.Text(), nullable=True))
    op.add_column("app_user", sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("app_user", sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column("account", sa.Column("contact_name", sa.Text(), nullable=True))
    op.add_column("account", sa.Column("contact_email", sa.Text(), nullable=True))

    op.add_column("tenant_config", sa.Column("outbound_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("tenant_config", sa.Column("sender_address", sa.Text(), nullable=True))
    op.add_column("tenant_config", sa.Column("sender_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("tenant_config", sa.Column("demo_mode", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.add_column("tenant_config", sa.Column("test_inbox", sa.Text(), nullable=True))
    op.add_column("tenant_config", sa.Column("llm_calls_per_cycle", sa.Integer(), nullable=False, server_default=sa.text("50")))

    for col in ("redirected_to", "provider_message_id", "delivery_error", "original_subject",
                "original_body", "draft_model", "draft_fallback_reason"):
        op.add_column("action", sa.Column(col, sa.Text(), nullable=True))

    # --- new tables ------------------------------------------------------- #
    op.create_table(
        "app_session",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        _tenant_fk(),
        sa.Column("user_id", pg.UUID(as_uuid=True), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
    )
    op.create_index("ix_app_session_lookup", "app_session", ["tenant_id", "token_hash"])

    op.create_table(
        "audit_event",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        _tenant_fk(),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actor_user_id", pg.UUID(as_uuid=True), sa.ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("actor_kind", sa.String(16), nullable=False),
        sa.Column("event", sa.String(48), nullable=False),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("detail", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index("ix_audit_event_at", "audit_event", ["tenant_id", "at"])

    op.create_table(
        "contact_opt_out",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        _tenant_fk(),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", pg.UUID(as_uuid=True), sa.ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "email", name="uq_contact_opt_out_email"),
    )

    # --- privileges and row-level security -------------------------------- #
    trainer = op.get_bind().execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = 'pulse_trainer'")).scalar()   # absent on a managed database (0002)
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE app_session, contact_opt_out TO pulse_app" + (", pulse_trainer" if trainer else ""))
    # Append-only: the application can write and read the audit trail, never rewrite it.
    op.execute("GRANT SELECT, INSERT ON TABLE audit_event TO pulse_app")
    if trainer:
        op.execute("GRANT SELECT ON TABLE audit_event TO pulse_trainer")

    for table in NEW_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table}"
            f" USING (tenant_id = {CLAIM}) WITH CHECK (tenant_id = {CLAIM})"
        )


def downgrade() -> None:
    for table in reversed(NEW_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.drop_table(table)
    for col in ("redirected_to", "provider_message_id", "delivery_error", "original_subject",
                "original_body", "draft_model", "draft_fallback_reason"):
        op.drop_column("action", col)
    for col in ("outbound_enabled", "sender_address", "sender_verified", "demo_mode", "test_inbox", "llm_calls_per_cycle"):
        op.drop_column("tenant_config", col)
    op.drop_column("account", "contact_email")
    op.drop_column("account", "contact_name")
    for col in ("password_changed_at", "disabled_at", "password_hash"):
        op.drop_column("app_user", col)
