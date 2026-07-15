"""Universe (stock-pool) engine (Sprint 1.13).

Manages named pools of stock codes persisted in the shared database. Pools are
the reusable candidate source that ``report`` can resolve via ``--universe``.
Membership is kept as a de-duplicated, sorted JSON list on ``UniversePool``.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from core.database import Base, get_engine, get_sessionmaker
from universe.models import UniversePool

logger = logging.getLogger(__name__)


class UniverseEngine:
    """Create / extend / shrink / query named stock pools."""

    def __init__(self, session: Session | None = None) -> None:
        if session is None:
            engine = get_engine()
            Base.metadata.create_all(engine)
            self.session = get_sessionmaker(engine)()
        else:
            self.session = session

    # ------------------------------------------------------------------ #
    # Membership
    # ------------------------------------------------------------------ #
    def add_codes(self, name: str, codes: list[str]) -> list[str]:
        """Add *codes* to pool *name* (creating it if new). Returns sorted list."""
        pool = self.session.get(UniversePool, name)
        if pool is None:
            pool = UniversePool(name=name, codes_json=[])
            self.session.add(pool)
        existing = set(pool.codes_json or [])
        existing.update(codes)
        pool.codes_json = sorted(existing)
        self.session.commit()
        return list(pool.codes_json)

    def remove_codes(self, name: str, codes: list[str]) -> list[str]:
        """Remove *codes* from pool *name*. Returns the remaining sorted list."""
        pool = self.session.get(UniversePool, name)
        if pool is None:
            return []
        existing = set(pool.codes_json or [])
        existing.difference_update(codes)
        pool.codes_json = sorted(existing)
        self.session.commit()
        return list(pool.codes_json)

    def get_codes(self, name: str) -> list[str]:
        """Return the sorted code list for pool *name* (empty if unknown)."""
        pool = self.session.get(UniversePool, name)
        return list(pool.codes_json or []) if pool is not None else []

    def exists(self, name: str) -> bool:
        return self.session.get(UniversePool, name) is not None

    def list_pools(self) -> list[str]:
        """All pool names, alphabetically."""
        return [p.name for p in self.session.query(UniversePool).order_by(UniversePool.name).all()]

    def delete(self, name: str) -> bool:
        """Delete pool *name*. Returns True if it existed."""
        pool = self.session.get(UniversePool, name)
        if pool is None:
            return False
        self.session.delete(pool)
        self.session.commit()
        return True
