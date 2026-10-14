"""Server-side defaults for tenant_config.

Revision ID: 0003_cfg_defaults
Revises: 0002_rls

These are operator-facing policy settings, every one of them an answer to an
open business question in the spec. A tenant_config row created by any path — a
seed script, an onboarding migration, a psql console during an incident — must
come out carrying sane policy rather than nulls. Defaults expressed only in the
Python model apply only to inserts that go through the ORM, which is a guarantee
that quietly stops holding the first time someone writes SQL.
"""

from __future__ import annotations

from alembic import op

revision = "0003_cfg_defaults"
down_revision = "0002_rls"
branch_labels = None
depends_on = None

DEFAULTS = {
    "horizon_days": "90",
    "contraction_threshold": "0.25",
    "weekly_capacity": "10",
    "tier_red_at": "0.35",
    "tier_amber_at": "0.15",
    "min_days_history": "30",
    "min_sources_with_data": "2",
    "suppression_days": "14",
    "max_sends_per_cycle": "25",
    "material_delta": "0.08",
}


def upgrade() -> None:
    for column, value in DEFAULTS.items():
        op.execute(f"ALTER TABLE tenant_config ALTER COLUMN {column} SET DEFAULT {value}")


def downgrade() -> None:
    for column in DEFAULTS:
        op.execute(f"ALTER TABLE tenant_config ALTER COLUMN {column} DROP DEFAULT")
