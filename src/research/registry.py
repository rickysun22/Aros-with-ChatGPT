"""Experiment registry (Sprint 2.0) -- CRUD + result persistence.

Persists / retrieves :class:`ExperimentRun` rows and records the metrics /
equity produced by the runner (Sprint 2.4). Session handling mirrors
:class:`~universe.engine.UniverseEngine` so tests can inject an in-memory
session. All ORM writes live here -- the runner calls these helpers rather than
touching the models directly (2.1 owns the schema).
"""

from __future__ import annotations

import json
import math
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from core.database import Base, get_engine, get_sessionmaker
from research.experiment import ExperimentResult
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

    # ------------------------------------------------------------------ #
    # Result persistence (Sprint 2.4) -- all ORM writes stay in the registry
    # ------------------------------------------------------------------ #
    @staticmethod
    def _coerce_value(value: float | None) -> float | None:
        """Coerce non-finite metric values to ``None`` (sqlite-safe, nullable)."""
        if value is None:
            return None
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return value

    def record_metrics(
        self,
        run_id: str,
        metrics: Mapping[str, float | None],
        window: str = "full",
        is_oos: bool = False,
    ) -> None:
        """Append long-form metric rows for ``run_id`` (non-finite -> ``None``)."""
        rows = [
            ExperimentMetric(
                run_id=run_id,
                metric_name=name,
                value=self._coerce_value(value),
                is_oos=is_oos,
                window=window,
            )
            for name, value in metrics.items()
        ]
        if rows:
            self.session.add_all(rows)
            self.session.commit()

    def record_equity(
        self,
        run_id: str,
        equity: dict[str, float],
        window: str = "full",
        is_oos: bool = False,
    ) -> None:
        """Persist an equity curve as a JSON blob (``{iso_date: value}``)."""
        blob = json.dumps({str(k): float(v) for k, v in equity.items()})
        self.session.add(
            ExperimentEquity(run_id=run_id, window=window, is_oos=is_oos, equity_json=blob)
        )
        self.session.commit()

    def mark_done(self, run_id: str, status: str = "done") -> None:
        """Mark ``run_id`` finished (sets status + ``finished_at``)."""
        run = self.session.get(ExperimentRun, run_id)
        if run is None:
            return
        run.status = status
        run.finished_at = datetime.now(UTC).replace(tzinfo=None)
        self.session.commit()

    # ------------------------------------------------------------------ #
    # Result reconstruction (Sprint 2.6) -- rebuild ExperimentResult from DB
    # ------------------------------------------------------------------ #
    def load_result(self, run_id: str) -> ExperimentResult | None:
        """Reconstruct the :class:`ExperimentResult` persisted for ``run_id``.

        Reads the long-form :class:`ExperimentMetric` rows and the JSON
        :class:`ExperimentEquity` blobs grouped by window. Returns ``None`` when
        the run is unknown (mirrors :meth:`get`). Window order is preserved by
        first appearance across metric rows, then any equity-only windows.
        """
        if self.get(run_id) is None:
            return None

        metric_rows = self.session.query(ExperimentMetric).filter_by(run_id=run_id).all()
        equity_rows = self.session.query(ExperimentEquity).filter_by(run_id=run_id).all()

        raw_metrics: dict[str, dict[str, float | None]] = {}
        equity: dict[str, dict[str, float]] = {}
        windows: list[str] = []

        def _add_window(w: str) -> None:
            if w not in windows:
                windows.append(w)

        for m_row in metric_rows:
            w = m_row.window or "full"
            _add_window(w)
            raw_metrics.setdefault(w, {})[m_row.metric_name] = m_row.value

        for e_row in equity_rows:
            w = e_row.window or "full"
            _add_window(w)
            equity[w] = {str(k): float(v) for k, v in json.loads(e_row.equity_json).items()}

        metrics: dict[str, Mapping[str, float | None]] = {
            w: raw_metrics[w] for w in windows if w in raw_metrics
        }
        return ExperimentResult(run_id=run_id, metrics=metrics, equity=equity, windows=windows)
