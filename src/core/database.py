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


def get_engine() -> Engine:
    """Create (and cache) the SQLAlchemy engine from configuration."""
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE

    cfg = get_config()
    url = cfg.database.url
    if url.startswith(_SQLITE_PREFIX):
        db_path = url[len(_SQLITE_PREFIX) :]
        if db_path and not db_path.startswith(":memory:"):
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    try:
        _ENGINE = create_engine(url, future=True, pool_pre_ping=True)
    except Exception as exc:  # pragma: no cover - defensive
        raise DatabaseError(f"Failed to create engine for {url!r}: {exc}") from exc
    return _ENGINE


def get_sessionmaker() -> sessionmaker[Session]:
    """Return a :class:`sessionmaker` bound to the shared engine."""
    return sessionmaker(
        bind=get_engine(),
        autoflush=False,
        autocommit=False,
        future=True,
    )
