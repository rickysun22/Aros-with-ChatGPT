"""Database engine and session management (SQLAlchemy 2.x).

Provides a cached engine and a session factory. The engine URL comes from the
active configuration, so no database detail is hard-coded in the source.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_config
from .exceptions import DatabaseError

# SQLite stores a single file; ensure its parent directory exists before
# the engine tries to open it.
_SQLITE_PREFIX = "sqlite:///"


class Base(DeclarativeBase):
    """Declarative base for all AROS ORM models."""


_ENGINE: Engine | None = None


def get_engine(url: str | None = None) -> Engine:
    """Create a SQLAlchemy engine.

    If *url* is omitted the URL comes from configuration and the engine is
    cached process-wide. Passing an explicit *url* builds a fresh, uncached
    engine -- used when a :class:`DataManager` owns its own configuration.
    """
    if url is None:
        global _ENGINE
        if _ENGINE is not None:
            return _ENGINE
        url = get_config().database.url

    if url.startswith(_SQLITE_PREFIX):
        db_path = url[len(_SQLITE_PREFIX) :]
        if db_path and not db_path.startswith(":memory:"):
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    try:
        engine = create_engine(url, future=True, pool_pre_ping=True)
    except Exception as exc:  # pragma: no cover - defensive
        raise DatabaseError(f"Failed to create engine for {url!r}: {exc}") from exc

    if url is None:
        _ENGINE = engine
    return engine


def get_sessionmaker(engine: Engine | None = None) -> sessionmaker[Session]:
    """Return a :class:`sessionmaker` bound to *engine* (or the shared one)."""
    if engine is None:
        engine = get_engine()
    return sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        future=True,
    )
