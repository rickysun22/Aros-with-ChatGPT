"""Backtest result cache (Sprint 1.12).

Persist a single-code backtest result (metrics + equity curve) keyed by
``(code, params_hash)`` so repeated runs over the same window/parameters skip
the expensive simulation. The cache is *best-effort*: any database failure is
swallowed and the backtest falls back to a live computation, so enabling the
cache can never break a backtest.

The cache key folds in everything that changes the simulation outcome: the
resolved signal column, the cost model, the cash/position limits, the benchmark
flag, and the start/end window. A different window (e.g. a new ``as_of``) is a
natural cache miss.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date
from typing import Any

from sqlalchemy import JSON, Column, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Session

from core.config import BacktestConfig
from core.database import Base

logger = logging.getLogger(__name__)


class BacktestCache(Base):
    """One cached single-code backtest result."""

    __tablename__ = "backtest_cache"

    id = Column(Integer, primary_key=True)
    code = Column(String(16), nullable=False, index=True)
    params_hash = Column(String(32), nullable=False)
    start = Column(String(10))
    end = Column(String(10))
    signal_col = Column(String(64))
    metrics_json = Column(JSON, nullable=False)
    equity_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (UniqueConstraint("code", "params_hash", name="uq_backtest_cache"),)


def compute_params_hash(
    config: BacktestConfig,
    signal_key: str,
    start: date | None,
    end: date | None,
) -> str:
    """A stable hash over every input that affects the simulation output."""
    parts = {
        "signal": signal_key,
        "cost": config.cost.model_dump(),
        "initial_cash": config.initial_cash,
        "max_position": config.max_position,
        "benchmark": config.benchmark,
        "start": str(start) if start else None,
        "end": str(end) if end else None,
    }
    blob = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def get_cached(
    code: str, params_hash: str, session: Session | None = None
) -> tuple[dict[str, float], list[float]] | None:
    """Return ``(metrics, equity)`` from cache, or ``None`` on miss/error."""
    if session is None:
        from core.database import get_engine, get_sessionmaker

        engine = get_engine()
        Base.metadata.create_all(engine)
        session = get_sessionmaker(engine)()
    try:
        row = session.query(BacktestCache).filter_by(code=code, params_hash=params_hash).first()
        if row is None:
            return None
        metrics = dict(row.metrics_json)
        equity = list(row.equity_json)
        return metrics, equity
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("backtest cache read failed: %s", exc)
        return None
    finally:
        if session is not None:
            session.close()


def store(
    code: str,
    params_hash: str,
    start: date | None,
    end: date | None,
    signal_col: str | None,
    metrics: dict[str, float],
    equity: list[float],
    session: Session | None = None,
) -> None:
    """Persist a result; silently ignore DB failures."""
    if session is None:
        from core.database import get_engine, get_sessionmaker

        engine = get_engine()
        Base.metadata.create_all(engine)
        session = get_sessionmaker(engine)()
    try:
        session.merge(
            BacktestCache(
                code=code,
                params_hash=params_hash,
                start=str(start) if start else None,
                end=str(end) if end else None,
                signal_col=signal_col,
                metrics_json=dict(metrics),
                equity_json=list(equity),
            )
        )
        session.commit()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("backtest cache write failed: %s", exc)
        try:
            session.rollback()
        except Exception:  # pragma: no cover - defensive
            pass
    finally:
        if session is not None:
            session.close()


def run_code_cached(
    engine: Any,
    code: str,
    data_manager: Any,
    start_date: date | None = None,
    end_date: date | None = None,
    signal_col: str | None = None,
    session: Session | None = None,
) -> tuple[Any, dict[str, float]]:
    """Like ``engine.run_code`` but consult the cache first.

    On a hit the cached metrics + equity are returned (the equity is re-attached
    to a freshly loaded price frame so callers that read ``df['equity']`` keep
    working). On a miss the engine computes, the result is stored, and it is
    returned. The *engine* must expose ``run_code(..., use_cache=False)``.
    """
    signal_key = signal_col or engine.config.strategy or (engine.names[0] if engine.names else "")
    params_hash = compute_params_hash(engine.config, signal_key, start_date, end_date)

    cached = get_cached(code, params_hash, session)
    if cached is not None:
        metrics, equity = cached
        df = data_manager.get_daily(code, start_date, end_date)
        if df is not None and not df.empty and equity:
            df = df.copy()
            df["equity"] = equity
            return df, metrics

    df, metrics = engine.run_code(
        code, data_manager, start_date, end_date, signal_col, use_cache=False
    )
    if df is not None and not df.empty and isinstance(metrics, dict):
        equity = list(df["equity"].astype(float)) if "equity" in df.columns else []
        store(
            code,
            params_hash,
            start_date,
            end_date,
            signal_col,
            metrics,
            equity,
            session,
        )
    return df, metrics
