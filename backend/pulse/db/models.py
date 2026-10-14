"""All persisted entities, per specs/001-renewal-risk-prioritisation/data-model.md.

Two conventions are load-bearing and worth stating here rather than leaving to
be inferred:

1. ``source_event`` carries ``occurred_at`` **and** ``received_at`` as separate
   non-null columns, and neither is derived from the other. Everything the
   system claims about point-in-time correctness rests on that pair. A record
   that arrived three days after it happened is the normal case.

2. ``score`` rows are immutable. They are never updated, only appended. The
   history *is* the audit trail, and the feature-level diff between two of them
   is what answers "why did this move" — the question the two lost renewals
   needed answered and nobody could.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from pulse.db.base import Base, TenantScoped, ts, uuid_pk

# --------------------------------------------------------------------------- #
# Tenancy and users
# --------------------------------------------------------------------------- #


class Tenant(Base):
    """The scoping root. Deliberately not tenant-scoped itself."""

    __tablename__ = "tenant"

    id: Mapped[uuid.UUID] = uuid_pk()
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = ts(server_now=True)


class TenantConfig(TenantScoped, Base):
    """Per-tenant policy.

    Every field here is an answer to one of the open business questions in
    spec.md. They are configuration rather than constants precisely because we
    had to guess at them, and a guess that is hard-coded is a guess nobody can
    correct without a deploy.
    """

    __tablename__ = "tenant_config"

    id: Mapped[uuid.UUID] = uuid_pk()

    # server_default as well as default: these are operator-facing settings and a
    # row inserted by any path -- a migration, a seed script, a console -- must
    # come out with sane policy rather than nulls.
    horizon_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=90, server_default=text("90")
    )
    contraction_threshold: Mapped[float] = mapped_column(
        Numeric(5, 4), nullable=False, default=0.25, server_default=text("0.25")
    )
    weekly_capacity: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10, server_default=text("10")
    )
    tier_red_at: Mapped[float] = mapped_column(
        Numeric(5, 4), nullable=False, default=0.35, server_default=text("0.35")
    )
    tier_amber_at: Mapped[float] = mapped_column(
        Numeric(5, 4), nullable=False, default=0.15, server_default=text("0.15")
    )
    min_days_history: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30, server_default=text("30")
    )
    min_sources_with_data: Mapped[int] = mapped_column(
        Integer, nullable=False, default=2, server_default=text("2")
    )
    suppression_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=14, server_default=text("14")
    )
    max_sends_per_cycle: Mapped[int] = mapped_column(
        Integer, nullable=False, default=25, server_default=text("25")
    )
    material_delta: Mapped[float] = mapped_column(
        Numeric(5, 4), nullable=False, default=0.08, server_default=text("0.08")
    )
    connected_sources: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False,
        server_default=text("ARRAY['salesforce','gmail','zendesk','product','stripe']::text[]"),
    )

    __table_args__ = (UniqueConstraint("tenant_id", name="uq_tenant_config_tenant"),)


class AppUser(TenantScoped, Base):
    __tablename__ = "app_user"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(
        String(16), nullable=False, default="csm", server_default=text("'csm'")
    )

    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_app_user_email"),)


# --------------------------------------------------------------------------- #
# Accounts and source identity
# --------------------------------------------------------------------------- #


class Account(TenantScoped, Base):
    """The unit that gets scored.

    Several columns are nullable on purpose rather than by omission: ``seats``,
    ``acv_cents``, ``industry`` and ``renewal_date`` are genuinely unknown for
    part of a real estate, and a feature that divides by a guessed seat count
    produces a number a CSM will quote to a customer. Absence propagates.
    """

    __tablename__ = "account"

    id: Mapped[uuid.UUID] = uuid_pk()
    external_ref: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    segment: Mapped[str | None] = mapped_column(String(16), nullable=True)
    industry: Mapped[str | None] = mapped_column(Text, nullable=True)
    region: Mapped[str | None] = mapped_column(String(32), nullable=True)
    seats: Mapped[int | None] = mapped_column(Integer, nullable=True)
    acv_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    mrr_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    renewal_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    signup_date: Mapped[date] = mapped_column(Date, nullable=False)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True
    )

    # --- outcome columns: denied to the feature layer (features/denylist.py) ---
    lifecycle_state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default=text("'active'")
    )
    churned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    churn_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)

    created_at: Mapped[datetime] = ts(server_now=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "external_ref", name="uq_account_external_ref"),
        Index("ix_account_owner", "tenant_id", "owner_user_id"),
    )


class IdentityLink(TenantScoped, Base):
    """Source-native identifier to internal account.

    Its own table, not columns on ``account``, because in a real estate the
    mapping is incomplete and an unresolved identifier needs somewhere to live
    and be seen. ``account_id`` nullable is the whole point: unresolved is a
    state we report, not an exception we swallow.
    """

    __tablename__ = "identity_link"

    id: Mapped[uuid.UUID] = uuid_pk()
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_account_ref: Mapped[str] = mapped_column(Text, nullable=False)
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account.id", ondelete="CASCADE"), nullable=True
    )
    method: Mapped[str] = mapped_column(String(24), nullable=False)
    confidence: Mapped[float] = mapped_column(
        Numeric(4, 3), nullable=False, default=1.0, server_default=text("1.0")
    )
    first_seen_at: Mapped[datetime] = ts(server_now=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "source", "source_account_ref", name="uq_identity_ref"),
    )


# --------------------------------------------------------------------------- #
# The event log
# --------------------------------------------------------------------------- #


class SourceEvent(TenantScoped, Base):
    """Append-only. The single most important table; everything is derived from it.

    The unique constraint on ``(tenant_id, source, source_event_id)`` *is* the
    idempotency requirement — enforced by the database rather than by a check in
    application code that a future refactor could drop.

    ``id`` is a bigserial rather than a UUID so that it provides a total order
    tiebreak when two events share an ``occurred_at`` to the millisecond.
    Deterministic feature computation needs a stable order, and a random UUID
    does not give one.
    """

    __tablename__ = "source_event"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_event_id: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account.id", ondelete="CASCADE"), nullable=True
    )
    source_account_ref: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = ts()
    received_at: Mapped[datetime] = ts()
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "source", "source_event_id", name="uq_source_event_natural"),
        # The as-of query path. Every feature read filters received_at <= as_of,
        # so this index carries the entire feature layer.
        Index("ix_event_asof", "tenant_id", "account_id", "received_at"),
        Index("ix_event_type_asof", "tenant_id", "account_id", "event_type", "received_at"),
        Index("ix_event_source_asof", "tenant_id", "source", "received_at"),
    )


class IngestionWatermark(TenantScoped, Base):
    __tablename__ = "ingestion_watermark"

    id: Mapped[uuid.UUID] = uuid_pk()
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    last_received_at: Mapped[datetime] = ts()
    last_cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    events_ingested: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )
    updated_at: Mapped[datetime] = ts(server_now=True)

    __table_args__ = (UniqueConstraint("tenant_id", "source", name="uq_watermark"),)


# --------------------------------------------------------------------------- #
# Features, models, scores
# --------------------------------------------------------------------------- #


class FeatureSnapshot(TenantScoped, Base):
    """The feature vector for one account at one decision time.

    Persisted rather than recomputed on read, for two reasons. Drift becomes
    detectable from history without re-deriving it, and an explanation can never
    silently disagree with the score it explains because both point at the same
    immutable row.

    ``values`` distinguishes JSON ``null`` from ``0.0`` and that distinction
    survives into the model. An account with no Gmail connection has null email
    features; an account whose customer has gone quiet has zero. Those are
    opposite situations.
    """

    __tablename__ = "feature_snapshot"

    id: Mapped[uuid.UUID] = uuid_pk()
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account.id", ondelete="CASCADE"), nullable=False
    )
    as_of: Mapped[datetime] = ts()
    values: Mapped[dict] = mapped_column(JSONB, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False)
    coverage: Mapped[dict] = mapped_column(JSONB, nullable=False)
    days_of_history: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    feature_set_version: Mapped[str] = mapped_column(String(32), nullable=False)
    computed_at: Mapped[datetime] = ts(server_now=True)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "account_id", "as_of", "feature_set_version", name="uq_snapshot"
        ),
        Index("ix_snapshot_account", "tenant_id", "account_id", "as_of"),
    )


class ModelVersion(Base):
    """A fitted artefact and its model card.

    Not tenant-scoped: one shared model serves every tenant (clarifications
    B-7), written only by the explicitly elevated cross-tenant training path.
    """

    __tablename__ = "model_version"

    id: Mapped[uuid.UUID] = uuid_pk()
    version: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    algorithm: Mapped[str] = mapped_column(Text, nullable=False)
    feature_set_version: Mapped[str] = mapped_column(String(32), nullable=False)
    feature_names: Mapped[list] = mapped_column(JSONB, nullable=False)
    trained_at: Mapped[datetime] = ts(server_now=True)
    train_window_start: Mapped[datetime] = ts()
    train_window_end: Mapped[datetime] = ts()
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    data_version: Mapped[str] = mapped_column(Text, nullable=False)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False)
    artifact_path: Mapped[str] = mapped_column(Text, nullable=False)
    promoted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    promotion_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class Score(TenantScoped, Base):
    """Immutable. Appended, never updated."""

    __tablename__ = "score"

    id: Mapped[uuid.UUID] = uuid_pk()
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account.id", ondelete="CASCADE"), nullable=False
    )
    as_of: Mapped[datetime] = ts()
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("feature_snapshot.id", ondelete="CASCADE"), nullable=False
    )

    probability: Mapped[float] = mapped_column(Numeric(6, 5), nullable=False)
    probability_raw: Mapped[float] = mapped_column(Numeric(6, 5), nullable=False)
    tier: Mapped[str] = mapped_column(String(8), nullable=False)
    health_score: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[str] = mapped_column(String(8), nullable=False)
    abstain_reason: Mapped[str | None] = mapped_column(String(48), nullable=True)

    contributions: Mapped[dict] = mapped_column(JSONB, nullable=False)
    dominant_driver: Mapped[str | None] = mapped_column(String(32), nullable=True)

    value_at_risk_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    urgency_multiplier: Mapped[float] = mapped_column(
        Numeric(6, 3), nullable=False, default=1.0, server_default=text("1.0")
    )
    priority: Mapped[float] = mapped_column(
        Numeric(18, 4), nullable=False, default=0, server_default=text("0")
    )
    ranking_math: Mapped[dict] = mapped_column(JSONB, nullable=False)

    created_at: Mapped[datetime] = ts(server_now=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "account_id", "as_of", name="uq_score"),
        Index("ix_score_queue", "tenant_id", "as_of", "priority"),
        Index("ix_score_account", "tenant_id", "account_id", "as_of"),
    )


# --------------------------------------------------------------------------- #
# The agent
# --------------------------------------------------------------------------- #


class PlayAllowlist(TenantScoped, Base):
    """Autonomous dispatch is opt-in, per tenant, per play.

    Absence of a row is the default and means "draft for a human". The
    ``enabled_by_user_id`` column exists so that switching autonomous sending on
    leaves an accountability record naming a person.
    """

    __tablename__ = "play_allowlist"

    id: Mapped[uuid.UUID] = uuid_pk()
    play_key: Mapped[str] = mapped_column(String(48), nullable=False)
    # Defaults to false in the schema as well as the model: autonomous sending
    # must be impossible to switch on by accident, including by an INSERT that
    # simply omits the column.
    auto_send: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    enabled_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True
    )
    enabled_at: Mapped[datetime] = ts(server_now=True)

    __table_args__ = (UniqueConstraint("tenant_id", "play_key", name="uq_allowlist"),)


class AgentRun(TenantScoped, Base):
    """One autonomous cycle.

    ``decisions_declined`` is the interesting half of this record. A system that
    logs only what it did, and not what it chose not to do and why, cannot be
    audited — and an autonomous system nobody can audit is one nobody will
    leave switched on.
    """

    __tablename__ = "agent_run"

    id: Mapped[uuid.UUID] = uuid_pk()
    trigger: Mapped[str] = mapped_column(
        String(24), nullable=False, default="schedule", server_default=text("'schedule'")
    )
    started_at: Mapped[datetime] = ts(server_now=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="running", server_default=text("'running'")
    )
    as_of: Mapped[datetime] = ts()
    stage_counts: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    decisions_declined: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    errors: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (Index("ix_run_recent", "tenant_id", "started_at"),)


class Action(TenantScoped, Base):
    __tablename__ = "action"

    id: Mapped[uuid.UUID] = uuid_pk()
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account.id", ondelete="CASCADE"), nullable=False
    )
    score_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("score.id", ondelete="SET NULL"), nullable=True
    )
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_run.id", ondelete="SET NULL"), nullable=True
    )
    play_key: Mapped[str] = mapped_column(String(48), nullable=False)
    # Drafted, not sent. The default state of any outbound action is one that
    # needs a human; see FR-034.
    state: Mapped[str] = mapped_column(
        String(24), nullable=False, default="drafted", server_default=text("'drafted'")
    )
    state_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    channel: Mapped[str] = mapped_column(
        String(16), nullable=False, default="email", server_default=text("'email'")
    )
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Which writer produced the draft, so a reviewer knows whether a human is
    # editing a template or a language model's prose.
    draft_source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="template", server_default=text("'template'")
    )
    grounding: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    created_at: Mapped[datetime] = ts(server_now=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    __table_args__ = (
        Index("ix_action_account", "tenant_id", "account_id", "created_at"),
        Index("ix_action_state", "tenant_id", "state"),
    )


class WorkLease(Base):
    """Crash-safe claiming for the worker.

    A lease with an expiry rather than a bare ``in_progress`` status, because the
    failure that matters is a worker dying mid-unit. A status column with no
    expiry leaves that unit never retried and never reported — precisely the
    silent gap that produced the original complaint.

    Not tenant-scoped: this is worker infrastructure and is never served to a
    request.
    """

    __tablename__ = "work_lease"

    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    key: Mapped[str] = mapped_column(Text, nullable=False)
    owner: Mapped[str | None] = mapped_column(Text, nullable=True)
    leased_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default=text("'pending'")
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = ts(server_now=True)

    __table_args__ = (
        UniqueConstraint("kind", "key", name="uq_lease"),
        Index("ix_lease_claim", "kind", "state", "leased_until"),
    )


class Suppression(TenantScoped, Base):
    """A human deciding an account should not be surfaced.

    Exclusion from the *queue*, never from scoring. An account deliberately
    being allowed to churn is a legitimate business state, and deleting its data
    to express that would destroy the record.
    """

    __tablename__ = "suppression"

    id: Mapped[uuid.UUID] = uuid_pk()
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account.id", ondelete="CASCADE"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = ts(server_now=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_suppression_account", "tenant_id", "account_id", "expires_at"),)


class Feedback(TenantScoped, Base):
    """A human judgement, retained as a label.

    A dismissal that only removes a row from a list throws away the most
    valuable label the system will ever be handed: a domain expert saying "this
    one is wrong". Stored as training data, not as UI state.
    """

    __tablename__ = "feedback"

    id: Mapped[uuid.UUID] = uuid_pk()
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account.id", ondelete="CASCADE"), nullable=False
    )
    score_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("score.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = ts(server_now=True)

    __table_args__ = (Index("ix_feedback_account", "tenant_id", "account_id"),)


# Tables that hold customer data and therefore carry a tenant policy. Built by
# TenantScoped.__init_subclass__ as the classes above are defined, so it cannot
# drift from the schema.
from pulse.db.base import TENANT_SCOPED_TABLES  # noqa: E402

GLOBAL_TABLES = ["tenant", "model_version", "work_lease"]

__all__ = [
    "Account", "Action", "AgentRun", "AppUser", "Base", "Feedback", "FeatureSnapshot",
    "GLOBAL_TABLES", "IdentityLink", "IngestionWatermark", "ModelVersion", "PlayAllowlist",
    "Score", "SourceEvent", "Suppression", "TENANT_SCOPED_TABLES", "Tenant", "TenantConfig",
    "WorkLease",
]
