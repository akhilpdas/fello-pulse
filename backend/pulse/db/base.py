"""Declarative base and the tenant-scoping mixin.

``TenantScoped`` is more than a column. ``TENANT_SCOPED_TABLES``, collected here
as subclasses are defined, is what the row-level-security migration iterates
over and what the isolation test iterates over. A new tenant-scoped table
therefore gets its policy and its isolation proof automatically, and a table
that forgets the mixin shows up as a gap in both places rather than silently
shipping unprotected. Registration-by-construction rather than by a hand-kept
list is the point: the list cannot drift from the schema.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

TENANT_SCOPED_TABLES: list[str] = []


class Base(DeclarativeBase):
    pass


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def fk_uuid(target: str, nullable: bool = False, index: bool = False) -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), ForeignKey(target, ondelete="CASCADE"),
        nullable=nullable, index=index,
    )


def ts(nullable: bool = False, server_now: bool = False) -> Mapped[datetime]:
    kwargs: dict = {"nullable": nullable}
    if server_now:
        kwargs["server_default"] = text("now()")
    return mapped_column(DateTime(timezone=True), **kwargs)


class TenantScoped:
    """Mixin for every table holding customer data."""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        tablename = getattr(cls, "__tablename__", None)
        if isinstance(tablename, str) and tablename not in TENANT_SCOPED_TABLES:
            TENANT_SCOPED_TABLES.append(tablename)

    @declared_attr
    def tenant_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(
            UUID(as_uuid=True),
            ForeignKey("tenant.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
