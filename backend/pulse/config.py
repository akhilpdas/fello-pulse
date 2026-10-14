"""Settings and the injectable clock.

Nothing in Pulse calls ``datetime.now()`` directly. A system whose correctness
depends on the wall clock cannot be tested for point-in-time behaviour, and
point-in-time behaviour is the first principle in the constitution. Every
component takes a ``Clock``; production passes ``SystemClock``, tests pass
``FrozenClock``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

from pydantic_settings import BaseSettings, SettingsConfigDict


class Clock(Protocol):
    """The only sanctioned source of 'now'."""

    def now(self) -> datetime: ...


@dataclass(frozen=True)
class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass
class FrozenClock:
    """A clock that only moves when a test moves it."""

    _now: datetime

    def now(self) -> datetime:
        return self._now

    def advance(self, **kwargs: float) -> datetime:
        self._now = self._now + timedelta(**kwargs)
        return self._now

    def set(self, when: datetime) -> datetime:
        self._now = when
        return self._now


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PULSE_", extra="ignore")

    # Two URLs, deliberately. Migrations run as the owner; the application runs
    # as a role that cannot bypass row-level security. Collapsing these into one
    # connection string is how RLS gets silently disabled in production.
    database_url_owner: str = "postgresql+psycopg://pulse@/pulse?host=/tmp&port=5432"
    database_url_app: str = (
        "postgresql+psycopg://pulse_app:pulse_app@/pulse?host=/tmp&port=5432"
    )

    echo_sql: bool = False
    pool_size: int = 10

    # Reproducibility. Recorded into every artefact these seeds produced.
    data_seed: int = 20261015
    model_seed: int = 7

    # Modelling defaults. Per-tenant values in tenant_config override these;
    # these exist so a fresh tenant has sane behaviour on day one.
    horizon_days: int = 90
    feature_set_version: str = "fs-1"

    # The agent
    worker_tick_seconds: int = 30
    cycle_interval_minutes: int = 15
    lease_seconds: int = 300
    worker_id: str = field(default_factory=lambda: os.environ.get("HOSTNAME", "worker-1"))

    # Language model support is optional by construction. With no key configured
    # the drafter falls back to deterministic templates and the system is fully
    # functional: degraded prose, identical ranking.
    llm_enabled: bool = False
    llm_model: str = "claude-sonnet-4-5"
    llm_api_key: str | None = None

    # Model promotion gate: a candidate must beat the heuristic baseline at the
    # operating point by at least this margin in precision to be promoted.
    promotion_min_lift: float = 0.02
    # A test-block AUC above this is treated as evidence of a broken harness
    # rather than a good model, and fails the build.
    auc_plausibility_ceiling: float = 0.95

    auth_secret: str = "dev-only-not-a-real-secret"

    paths_feeds: str = "data/feeds"
    paths_artifacts: str = "artifacts"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Test hook."""
    global _settings
    _settings = None
