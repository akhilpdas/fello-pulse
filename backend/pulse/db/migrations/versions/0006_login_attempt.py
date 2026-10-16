"""Shared state for the login limiter (a declared *global* table).

Revision ID: 0006_login_attempt
Revises: 0005_auth_delivery

Holds a hash of (address, workspace, email) and a time -- no tenant data, no email address. Not tenant-scoped because
a sign-in has no tenant until it succeeds. The application role may insert, read and delete; nothing else.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_login_attempt"
down_revision = "0005_auth_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "login_attempt",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_login_attempt_key", "login_attempt", ["key_hash", "at"])
    op.execute("GRANT SELECT, INSERT, DELETE ON TABLE login_attempt TO pulse_app")
    op.execute("GRANT USAGE, SELECT ON SEQUENCE login_attempt_id_seq TO pulse_app")


def downgrade() -> None:
    op.drop_table("login_attempt")
