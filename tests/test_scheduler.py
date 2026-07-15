"""Tests for the Sprint 1.15 scheduler + notifier.

No external credentials required: the webhook notifier is a no-op without a URL,
so these tests run fully offline.
"""

from __future__ import annotations

from core.config import SchedulerConfig
from scheduler.engine import Scheduler
from scheduler.notify import (
    ConsoleNotifier,
    FileNotifier,
    WebhookNotifier,
    build_notifier,
)


def test_console_notifier(capsys):
    ConsoleNotifier().notify("TITLE", "body text")
    out = capsys.readouterr().out
    assert "TITLE" in out and "body text" in out


def test_file_notifier(tmp_path):
    p = tmp_path / "out.md"
    FileNotifier(str(p)).notify("TITLE", "hello")
    assert p.read_text(encoding="utf-8") == "# TITLE\n\nhello\n\n"


def test_webhook_noop_without_url():
    # Must not raise when no URL is configured.
    WebhookNotifier(None).notify("TITLE", "x")


def test_build_notifier_types():
    assert isinstance(build_notifier(SchedulerConfig(notifier_type="console")), ConsoleNotifier)
    assert isinstance(build_notifier(SchedulerConfig(notifier_type="file")), FileNotifier)
    assert isinstance(build_notifier(SchedulerConfig(notifier_type="webhook")), WebhookNotifier)


class _RecordingNotifier:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def notify(self, title: str, body: str) -> None:  # noqa: D401 - test double
        self.calls.append(body)


def test_scheduler_run_ntimes():
    rec = _RecordingNotifier()
    sched = Scheduler(rec)
    count = {"n": 0}

    def task() -> str:
        count["n"] += 1
        return f"run{count['n']}"

    sched.run_ntimes(task, 0, 3)
    assert count["n"] == 3
    assert rec.calls == ["run1", "run2", "run3"]


def test_cli_schedule_once():
    from typer.testing import CliRunner

    import main

    runner = CliRunner()
    result = runner.invoke(main.app, ["schedule", "--once", "--report", "A", "B"])
    assert result.exit_code == 0, result.output
