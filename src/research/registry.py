"""Experiment registry (Sprint 2.0) -- CRUD only, no run logic.

Persists / retrieves :class:`ExperimentRun` rows. It deliberately contains *no*
execution logic in 2.0: the runner that fills metrics/equity lands in Sprint
2.4. Session handling mirrors :class:`~universe.engine.UniverseEngine` so tests
can inject an in-memory session.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from core.database import Base, get_engine, get_sessionmaker
from research.models import ExperimentEquity, ExperimentMetric, ExperimentRun


def _new_run_id(prefix: str = "exp_") -> str:
    """Return a short, human-searchable run id, e.g. ``exp_a1b2c3d4``."""
    return f"{prefix}{uuid.uuid4().hex[:8]}"


class ExperimentRegistry:
    """Create / fetch / list / delete :class:`ExperimentRun` records."""

    def __init__(self, session: Session | None = None) -> None:
        if session is None:
            engine = get_engine()
            Base.metadata.create_all(engine)
            self.session = get_sessionmaker(engine)()
        else:
            self.session = session

    def create(
        self,
        name: str,
        config_json: str,
        notes: str | None = None,
        id_prefix: str = "exp_",
    ) -> str:
        """Register a new experiment and return its generated run id."""
        run = ExperimentRun(
            id=_new_run_id(id_prefix),
            name=name,
            config_json=config_json,
            status="created",
            notes=notes,
        )
        self.session.add(run)
        self.session.commit()
        return run.id

    def get(self, run_id: str) -> ExperimentRun | None:
        """Return the run with ``run_id`` (or ``None`` if unknown)."""
        return self.session.get(ExperimentRun, run_id)

    def list(self) -> list[ExperimentRun]:
        """Return all runs, newest first."""
        return list(
            self.session.query(ExperimentRun).order_by(ExperimentRun.created_at.desc()).all()
        )

    def delete(self, run_id: str) -> bool:
        """Delete run ``run_id`` and its child rows. Returns True if it existed.

        The child FKs are plain ``ForeignKey(...)`` with no ``ondelete="CASCADE"``
        and SQLite ships FK enforcement off by default, so we purge the children
        explicitly before deleting the parent. The ORM schema is unchanged.
        """
        run = self.session.get(ExperimentRun, run_id)
        if run is None:
            return False
        self.session.query(ExperimentMetric).filter_by(run_id=run_id).delete()
        self.session.query(ExperimentEquity).filter_by(run_id=run_id).delete()
        self.session.delete(run)
        self.session.commit()
        return True
