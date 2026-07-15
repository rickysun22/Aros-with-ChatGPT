"""Notifiers for scheduled AROS output (Sprint 1.15).

A :class:`Notifier` knows how to deliver a generated report/digest somewhere.
Three implementations ship: console (print), file (append), and webhook
(HTTP POST). The webhook notifier is *best-effort* and a no-op when no URL is
configured, so the scheduler runs fine with zero external credentials.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path

from core.config import SchedulerConfig

logger = logging.getLogger(__name__)


class Notifier(ABC):
    """Deliver a title + body somewhere useful."""

    @abstractmethod
    def notify(self, title: str, body: str) -> None: ...


class ConsoleNotifier(Notifier):
    """Print the message to stdout (default)."""

    def notify(self, title: str, body: str) -> None:
        print(f"[{title}]")
        print(body)


class FileNotifier(Notifier):
    """Append the message to a file (markdown)."""

    def __init__(self, path: str | None) -> None:
        self.path = path or "reports/scheduled.md"

    def notify(self, title: str, body: str) -> None:
        target = Path(self.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(f"# {title}\n\n{body}\n\n")
        logger.info("scheduler: wrote notification to %s", target)


class WebhookNotifier(Notifier):
    """POST ``{"title", "text"}`` JSON to a webhook URL (e.g. DingTalk/WeCom).

    Best-effort: network errors are logged and swallowed. With no URL the
    notify is a silent no-op, so the scheduler never crashes on missing creds.
    """

    def __init__(self, url: str | None) -> None:
        self.url = url

    def notify(self, title: str, body: str) -> None:
        if not self.url:
            logger.warning("scheduler: webhook notifier has no url; skipping")
            return
        try:  # pragma: no cover - requires network
            import urllib.request

            payload = json.dumps({"title": title, "text": body}).encode("utf-8")
            req = urllib.request.Request(
                self.url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
                logger.info("scheduler: webhook responded %s", resp.status)
        except Exception as exc:  # pragma: no cover - network dependent
            logger.warning("scheduler: webhook notify failed: %s", exc)


def build_notifier(config: SchedulerConfig) -> Notifier:
    """Construct the notifier selected by ``SchedulerConfig``."""
    if config.notifier_type == "file":
        return FileNotifier(config.file_path)
    if config.notifier_type == "webhook":
        return WebhookNotifier(config.webhook_url)
    return ConsoleNotifier()
