"""SQLAlchemy ORM models for AROS market data.

These models are bound to the shared :class:`~core.database.Base` so the
database engine in ``core.database`` manages their schema.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class Stock(Base):
    """A tradable A-share instrument."""

    __tablename__ = "stocks"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    exchange: Mapped[str | None] = mapped_column(String(8), nullable=True)
    list_date: Mapped[date | None] = mapped_column(Date, nullable=True)


class DailyBar(Base):
    """A single day of OHLCV data for one stock (adjusted per config)."""

    __tablename__ = "daily_bars"
    __table_args__ = (
        UniqueConstraint("code", "date", name="uq_bar_code_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, default=0.0)
    amount: Mapped[float] = mapped_column(Float, default=0.0)


class SyncState(Base):
    """Tracks how far each stock's daily bars have been synchronized."""

    __tablename__ = "sync_state"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    last_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )
