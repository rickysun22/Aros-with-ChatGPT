"""Centralized logging setup built on Loguru."""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

from .config import get_config


def setup_logging() -> None:
    """Configure Loguru sinks from the active configuration.

    Logs are written to stderr (colorized) and to ``<logging.dir>/aros.log``
    (rotated). Safe to call multiple times — it resets sinks each call.
    """
    cfg = get_config()
    logger.remove()
    logger.add(sys.stderr, level=cfg.logging.level, colorize=True)

    log_dir = Path(cfg.logging.dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.add(
        sink=log_dir / "aros.log",
        level=cfg.logging.level,
        rotation="10 MB",
        retention=5,
        encoding="utf-8",
    )
