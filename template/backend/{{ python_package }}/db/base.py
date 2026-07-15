"""SQLAlchemy declarative base and shared column mixins.

Types are kept portable (``Uuid``, ``JSON``, non-native enums) so the same models run
on Postgres (production) and SQLite (tests). Timestamps use Python-side defaults.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all models."""


def _utcnow() -> datetime:
    return datetime.now(UTC)


class UUIDMixin:
    """UUID primary key."""

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    """Created/updated timestamps (UTC)."""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
