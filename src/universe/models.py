"""ORM models for the Universe (stock-pool) Tracker (Sprint 1.13).

A *universe* is a named, reusable pool of stock codes. It is the single
candidate source that downstream commands (``report``) can resolve via
``--universe NAME`` instead of passing codes by hand every run.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class UniversePool(Base):
    """One named pool of stock codes (membership stored as a JSON list)."""

    __tablename__ = "universe_pool"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    codes_json: Mapped[Any] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
