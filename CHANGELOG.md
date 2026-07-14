# Changelog

All notable changes to AROS are documented by Sprint.

## Sprint 1.3 — Indicator Engine (2025-07-13)

### Added

- `src/indicators/base.py` — `BaseIndicator` base class + registry (`register`, `build`, `available`). Indicators are pure, causal functions of historical bars.
- `src/indicators/impl.py` — seven indicators, all config-driven and **future-leak free**: `ma`, `ema`, `rsi`, `macd`, `kdj`, `boll`, `vol_ma`.
- `src/indicators/engine.py` — `IndicatorEngine`: builds from `IndicatorConfig`, computes per-stock (`compute`), and reads bars through the single data entry via `compute_code(data_manager, ...)`.
- `src/indicators/__init__.py` — public exports.
- `core/config.py` — `IndicatorSpec` / `IndicatorConfig` models, wired into `AppConfig.indicators`.
- `config/settings.yaml` — `indicators.enabled` default set (multi-window `ma` demonstrates parameterization).
- `main.py` — new `indicators` command: `indicators --list` and `indicators CODE [--name ...]`.
- `tests/test_indicators.py` — indicator correctness, engine orchestration, and a **no-future-leak** invariant test (value at bar *t* computed on the full series equals the value computed on bars `0..t`).

### Notes

- Every indicator value at bar *t* depends only on data at bars `<= t` (rolling windows / EMA recursions / trailing min-max). The test-suite enforces this automatically.
- Indicators obtain prices exclusively through `DataManager`, preserving the single-data-entry principle.

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
