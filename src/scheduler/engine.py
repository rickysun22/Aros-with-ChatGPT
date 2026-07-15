"""Scheduler for AROS (Sprint 1.15).

Runs a zero-argument task that produces a message body on a fixed interval and
delivers it through a :class:`Notifier`. The task is whatever the caller wires
up (e.g. generate the daily report, or the watchlist digest). The loop is
interruptible via a :class:`threading.Event` so a deployment can stop cleanly.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from scheduler.notify import Notifier

logger = logging.getLogger(__name__)

Task = Callable[[], str]


class Scheduler:
    """Run a task on an interval and notify with its output."""

    def __init__(self, notifier: Notifier) -> None:
        self.notifier = notifier

    def run_ntimes(self, task: Task, interval_seconds: float, n: int) -> None:
        """Run *task* exactly *n* times, sleeping *interval_seconds* between."""
        for i in range(n):
            self._tick(task)
            if i < n - 1:
                time.sleep(interval_seconds)

    def run_loop(self, task: Task, interval_seconds: float, stop_event: Any | None = None) -> None:
        """Loop forever (or until *stop_event* is set), running *task* each tick."""
        while stop_event is None or not stop_event.is_set():
            self._tick(task)
            if stop_event is not None:
                stop_event.wait(interval_seconds)
            else:
                time.sleep(interval_seconds)

    def _tick(self, task: Task) -> None:
        try:
            body = task()
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("scheduler: task failed: %s", exc)
            body = f"(task error: {exc})"
        self.notifier.notify("AROS 定时任务", body or "(空)")
