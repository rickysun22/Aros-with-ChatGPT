# Changelog

All notable changes to AROS are documented by Sprint.

## Sprint 1.2 — Database Layer (2025-07-13)

### Added

- `src/data/models.py` — SQLAlchemy ORM models: `Stock`, `DailyBar` (unique `(code, date)`), `SyncState`.
- `src/data/provider.py` — `DataProvider` protocol + `AkShareProvider` with AKShare column normalization.
- `src/data/manager.py` — `DataManager`, the single data entry point: `sync_stock_list`, `sync_daily`, `get_daily`, `get_stock_list`, `last_sync_date`.
- `src/data/providers/astockdata.py` — alternative `AStockDataProvider` (akshare-free, direct HTTP via Baidu K-line + Eastmoney stock list) selectable through `data.source`.
- `main.py` — new CLI commands: `sync --list`, `sync --code`, `bars`.
- `tests/test_data.py` + `tests/conftest.py` — data-layer tests using `FakeProvider` and mocked HTTP endpoints.
- `.github/workflows/ci.yml` — GitHub Actions CI running `pytest`, `ruff`, `black --check`, `mypy`.

### Changed

- `config/settings.yaml` — added `data.source` (`akshare`/`astockdata`) and `data.adjust` (`qfq`/`hfq`).
- `src/core/database.py` — `get_engine` / `get_sessionmaker` now accept an explicit URL/engine so `DataManager` can use its own config.
- `pyproject.toml` / `requirements.txt` — added `requests` for the a-stock-data HTTP path.

### Notes

- `AkShareProvider` remains the **default** and supports forward-adjusted bars via `data.adjust`.
- `AStockDataProvider` is a direct-HTTP fallback that returns raw (unadjusted) Baidu prices; useful when AKShare is unstable.

## Sprint 1.1 — Project Foundation (2025-07-13)

### Added

- Project scaffold: `pyproject.toml`, `config/settings.yaml`, `.env.example`, updated `.gitignore`.
- `src/core/` — `config` (Pydantic + YAML/.env), `logging` (Loguru), `database` (SQLAlchemy 2.x), `exceptions` (hierarchy).
- `main.py` — Typer CLI entry point (`version`, `info`).
- `tests/test_core.py` — smoke tests for config, logging, database, CLI.
- `README.md` — setup, quality gates, project layout, and planned modules.
