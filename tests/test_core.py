"""Smoke and unit tests for the AROS core foundation (Sprint 1.1)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from core.config import AppConfig, get_config
from core.exceptions import AROSError, ConfigError, DatabaseError, DataError
from core.logging import setup_logging
from main import app

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_YAML = REPO_ROOT / "config" / "settings.yaml"


def test_config_defaults() -> None:
    cfg = get_config()
    assert isinstance(cfg, AppConfig)
    assert cfg.data.source == "akshare"
    assert cfg.data.frequency == "daily"
    assert cfg.data.start_date == "2015-01-01"
    assert cfg.data.end_date == "2026-06-30"
    assert cfg.database.url.startswith("sqlite:///")


def test_config_from_explicit_file() -> None:
    cfg = AppConfig.from_file(SAMPLE_YAML)
    assert cfg.data.start_date == "2015-01-01"
    assert cfg.app_name


def test_config_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom = tmp_path / "custom.yaml"
    custom.write_text("app_name: TEST\n", encoding="utf-8")
    monkeypatch.setenv("AROS_DATABASE_URL", "sqlite:///tmp/override.db")
    cfg = AppConfig.from_file(custom)
    assert cfg.app_name == "TEST"
    assert cfg.database.url == "sqlite:///tmp/override.db"


def test_exceptions_hierarchy() -> None:
    assert issubclass(ConfigError, AROSError)
    assert issubclass(DataError, AROSError)
    assert issubclass(DatabaseError, AROSError)
    with pytest.raises(AROSError):
        raise DataError("boom")


def test_logging_setup() -> None:
    setup_logging()  # must not raise
    from loguru import logger

    logger.info("logging smoke test")


def test_database_engine_and_session() -> None:
    from core.database import Base, get_engine, get_sessionmaker

    engine = get_engine()
    assert engine is not None
    factory = get_sessionmaker()
    assert factory is not None
    # Base must be usable as a SQLAlchemy declarative base
    assert hasattr(Base, "metadata")


def test_cli_version() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "AROS 0.1.0" in result.stdout


def test_cli_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "A-Share Research Operating System" in result.stdout
