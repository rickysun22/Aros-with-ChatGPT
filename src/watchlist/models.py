"""SQLAlchemy ORM models for the Watchlist Tracker (Sprint 1.9).

These models reuse the shared :class:`~core.database.Base` so the database
engine in ``core.database`` manages their schema alongside the existing
``Stock`` / ``DailyBar`` / ``SyncState`` tables.

* ``WatchlistItem`` - membership of the tracked universe (soft-delete via
  ``removed_at`` so history is preserved).
* ``RankingPoint`` - one daily ranking snapshot per watched code, capturing the
  full cross-sectional rank (so a code that drops out of the Top-N is still
  tracked) plus its composite score and per-dimension scores.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class WatchlistItem(Base):
    """A watched instrument. Active when ``removed_at`` is NULL."""

    __tablename__ = "watchlist_items"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    removed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    @property
    def is_active(self) -> bool:
        return self.removed_at is None


class RankingPoint(Base):
    """One daily ranking snapshot for a single watched code."""

    __tablename__ = "ranking_points"
    __table_args__ = (UniqueConstraint("as_of", "code", name="uq_point_asof_code"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    as_of: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    code: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    # Full cross-sectional rank within the watchlist; None when no data at as_of.
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Composite score at the cross-section; None when no data at as_of.
    composite_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Per-dimension scores, e.g. {"a": 0.6, "b": 0.4}; None when no data.
    scores_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
