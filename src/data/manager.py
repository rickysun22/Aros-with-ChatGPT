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

from .models import DailyBar, IndexBar, Stock, SyncState
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
    # Index / benchmark writes (Sprint 2.0) -- still the single data entry
    # ------------------------------------------------------------------ #
    def sync_index(
        self,
        code: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> int:
        """Fetch benchmark index ``code``'s daily bars for the range and upsert.

        Returns the number of bars stored. Empty provider results store nothing
        and return 0 (mirrors :meth:`sync_daily`); a *missing* read is surfaced
        by :meth:`get_index_daily`, not here.
        """
        start = start_date or _parse_date(self.config.data.start_date)
        end = end_date or _parse_date(self.config.data.end_date)
        df = self.provider.get_index_daily(code, start, end)
        if df.empty:
            return 0

        with self._sessionmaker() as session:
            self._upsert_index(session, df)
            session.commit()
        return len(df)

    @staticmethod
    def _upsert_index(session: Session, df: pd.DataFrame) -> None:
        def _num(value: object) -> float | None:
            return None if pd.isna(value) else float(value)  # type: ignore[arg-type]

        rows = [
            {
                "code": str(r.code),
                "date": r.date,
                "open": float(r.open),
                "high": float(r.high),
                "low": float(r.low),
                "close": float(r.close),
                "volume": _num(r.volume),
                "amount": _num(r.amount),
            }
            for r in df.itertuples(index=False)
        ]
        if not rows:
            return
        stmt = sqlite_insert(IndexBar).values(rows)
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

    def get_index_daily(
        self,
        code: str,
        start_date: date | None = None,
        end_date: date | None = None,
        as_of: date | None = None,
    ) -> pd.DataFrame:
        """Return stored daily bars for benchmark index ``code`` (Sprint 2.0).

        Mirrors :meth:`get_daily` but reads the ``index_bars`` table. ``as_of``
        is the no-look-ahead ceiling: only rows with ``date <= as_of`` are
        returned (in addition to the ``[start_date, end_date]`` window). Unlike
        :meth:`get_daily`, a benchmark with no matching data is treated as an
        error and raises :class:`DataError` rather than returning an empty frame,
        so a missing benchmark can never be silently ignored downstream.
        """
        start = start_date or _parse_date(self.config.data.start_date)
        end = end_date or _parse_date(self.config.data.end_date)
        columns = ["date", "open", "high", "low", "close", "volume", "amount"]
        with self._sessionmaker() as session:
            conditions = [
                IndexBar.code == code,
                IndexBar.date >= start,
                IndexBar.date <= end,
            ]
            if as_of is not None:
                conditions.append(IndexBar.date <= as_of)
            stmt = select(IndexBar).where(*conditions).order_by(IndexBar.date)
            bars = session.execute(stmt).scalars().all()
        if not bars:
            raise DataError(
                f"No index data for benchmark {code!r} in range "
                f"[{start}, {as_of or end}]; sync it first via sync_index({code!r})"
            )
        return pd.DataFrame([{c: getattr(b, c) for c in columns} for b in bars])

    def last_sync_date(self, code: str) -> date | None:
        """Return the most recent bar date stored for ``code``, if any."""
        with self._sessionmaker() as session:
            state = session.get(SyncState, code)
            return state.last_date if state else None
