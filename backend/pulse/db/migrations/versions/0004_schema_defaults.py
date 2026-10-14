"""Server-side defaults for every NOT NULL column that has a model default.

Revision ID: 0004_defaults
Revises: 0003_cfg_defaults

A default expressed only in the Python model applies only to inserts that go
through the ORM. That guarantee stops holding the first time anyone writes SQL —
a backfill, a seed script, a console during an incident — and the failure is a
NOT NULL violation at the worst moment, or worse, a column that silently had to
be made nullable to get the insert through.

Two of these defaults are not merely tidiness:

``play_allowlist.auto_send`` defaults to false, so autonomous sending cannot be
switched on by an INSERT that simply omits the column.

``action.state`` defaults to 'drafted', so an outbound action created by any
path starts in a state that requires a human (FR-034). The safe value is the one
you get when you forget to say anything.
"""

from __future__ import annotations

from alembic import op

revision = "0004_defaults"
down_revision = "0003_cfg_defaults"
branch_labels = None
depends_on = None

DEFAULTS: list[tuple[str, str, str]] = [
    ("app_user", "role", "'csm'"),
    ("account", "lifecycle_state", "'active'"),
    ("identity_link", "confidence", "1.0"),
    ("ingestion_watermark", "events_ingested", "0"),
    ("feature_snapshot", "days_of_history", "0"),
    ("model_version", "promoted", "false"),
    ("score", "urgency_multiplier", "1.0"),
    ("score", "priority", "0"),
    ("play_allowlist", "auto_send", "false"),
    ("agent_run", "trigger", "'schedule'"),
    ("agent_run", "status", "'running'"),
    ("agent_run", "stage_counts", "'{}'::jsonb"),
    ("agent_run", "decisions_declined", "'[]'::jsonb"),
    ("agent_run", "errors", "'[]'::jsonb"),
    ("action", "state", "'drafted'"),
    ("action", "channel", "'email'"),
    ("action", "draft_source", "'template'"),
    ("action", "grounding", "'{}'::jsonb"),
    ("action", "attempts", "0"),
    ("work_lease", "state", "'pending'"),
    ("work_lease", "attempts", "0"),
]


def upgrade() -> None:
    for table, column, value in DEFAULTS:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT {value}")


def downgrade() -> None:
    for table, column, _ in DEFAULTS:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT")
