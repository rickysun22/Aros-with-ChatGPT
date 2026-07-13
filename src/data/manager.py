"""DataManager - the single entry point for all market data.

This is the *only* module that is allowed to talk to a data provider (AKShare)
or to the database. Every other part of AROS must read/write market data
through a :class:`DataManager` instance, satisfying the project principle
*DataManager 为唯一数据入口*.

Design notes
------------
* A :class:`~core.config.AppConfig` and a :class:`DataProvider` are injected,
  which keeps the manager fully testable (tests pass a fake provider and a
  temporary database).
* ``get_daily`` / ``get_stock_list`` are pure reads of already-stored data.
  They never look ahead, so there is **no future-function leakage**.
* Writes go through a SQLite upsert keyed on ``(code, date)`` so re-syncing a
  stock is idempotent.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from core.config import AppConfig, get_config
from core.database import Base, get_engine, get_sessionmaker
from core.exceptions import ConfigError, DataError

from .models import DailyBar, Stock, SyncState
from .provider import AkShareProvider, DataProvider
from .providers.astockdata import AStockDataProvider


def _parse_date(value: str) -> date:
    """Parse an ISO ``YYYY-MM-DD`` string into a :class:`date`."""
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise DataError(f"Invalid date string {value!r}, expected YYYY-MM-DD") from exc


class DataManager:
    """Unified, configurable access to A-share market data."""

    def __init__(
        self,
        config: AppConfig | None = None,
        provider: DataProvider | None = None,
    ) -> None:
        self.config = config or get_config()
        self.provider = provider or self._build_provider()
        self._engine = get_engine(self.config.database.url)
        self._sessionmaker = get_sessionmaker(self._engine)
        self._ensure_schema()

    # ------------------------------------------------------------------ #
    # Provider selection (single source of truth)
    # ------------------------------------------------------------------ #
    def _build_provider(self) -> DataProvider:
        source = self.config.data.source
        if source == "astockdata":
            return AStockDataProvider()
        if source == "akshare":
            return AkShareProvider(adjust=self.config.data.adjust)
        raise ConfigError(
            f"Unsupported data.source: {source!r} (expected 'akshare' or 'astockdata')"
        )

    # ------------------------------------------------------------------ #
    # Schema
    # ------------------------------------------------------------------ #
    def _ensure_schema(self) -> None:
        from . import models  # noqa: F401  (register models on Base.metadata)

        Base.metadata.create_all(self._engine)

    # ------------------------------------------------------------------ #
    # Writes (from provider) -- used by sync pipelines
    # ------------------------------------------------------------------ #
    def sync_stock_list(self) -> int:
        """Fetch the full A-share list from the provider and upsert it."""
        df = self.provider.get_stock_list()
        with self._sessionmaker() as session:
            for row in df.itertuples(index=False):
                session.merge(Stock(code=str(row.code), name=str(row.name)))
            session.commit()
        return len(df)

    def sync_daily(
        self,
        code: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> int:
        """Fetch ``code``'s daily bars for the range and upsert them.

        Returns the number of bars stored.
        """
        start = start_date or _parse_date(self.config.data.start_date)
        end = end_date or _parse_date(self.config.data.end_date)
        df = self.provider.get_daily_bars(code, start, end)
        if df.empty:
            return 0

        with self._sessionmaker() as session:
            self._upsert_daily(session, df)
            session.merge(SyncState(code=code, last_date=df["date"].max()))
            session.commit()
        return len(df)

    @staticmethod
    def _upsert_daily(session: Session, df: pd.DataFrame) -> None:
        rows = [
            {
                "code": str(r.code),
                "date": r.date,
                "open": float(r.open),
                "high": float(r.high),
                "low": float(r.low),
                "close": float(r.close),
                "volume": float(r.volume),
                "amount": float(r.amount),
            }
            for r in df.itertuples(index=False)
        ]
        if not rows:
            return
        stmt = sqlite_insert(DailyBar).values(rows)
        # Reference the excluded row by attribute name so mypy stays happy.
        excluded = stmt.excluded
        stmt = stmt.on_conflict_do_update(
            index_elements=["code", "date"],
            set_={
                col: getattr(excluded, col)
                for col in ("open", "high", "low", "close", "volume", "amount")
            },
        )
        session.execute(stmt)

    # ------------------------------------------------------------------ #
    # Reads (the single source of truth)
    # ------------------------------------------------------------------ #
    def get_stock_list(self) -> pd.DataFrame:
        """Return all stored stocks as a DataFrame with ``code``/``name``."""
        with self._sessionmaker() as session:
            stocks = session.execute(select(Stock)).scalars().all()
            return pd.DataFrame([{"code": s.code, "name": s.name} for s in stocks])

    def get_daily(
        self,
        code: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pd.DataFrame:
        """Return stored daily bars for ``code`` in ``[start_date, end_date]``.

        The result is sorted ascending by date and contains no forward-looking
        columns. This is the canonical way to obtain price data downstream.
        """
        start = start_date or _parse_date(self.config.data.start_date)
        end = end_date or _parse_date(self.config.data.end_date)
        columns = ["date", "open", "high", "low", "close", "volume", "amount"]
        with self._sessionmaker() as session:
            stmt = (
                select(DailyBar)
                .where(
                    DailyBar.code == code,
                    DailyBar.date >= start,
                    DailyBar.date <= end,
                )
                .order_by(DailyBar.date)
            )
            bars = session.execute(stmt).scalars().all()
            return pd.DataFrame([{c: getattr(b, c) for c in columns} for b in bars])

    def last_sync_date(self, code: str) -> date | None:
        """Return the most recent bar date stored for ``code``, if any."""
        with self._sessionmaker() as session:
            state = session.get(SyncState, code)
            return state.last_date if state else None
