# Changelog

All notable changes to AROS are documented by Sprint.

## Sprint 1.5 — Strategy Engine (2026-07-14)

### Added

- `src/strategies/signal.py` — `SignalType` enum (SHORT=-1 / FLAT=0 / LONG=1) plus `to_position` / `coerce` helpers mapping a signal to a target position weight. A-share first: long and flat are fully supported, short is reserved for future extension.
- `src/strategies/base.py` — `BaseStrategy` base class + registry (`register`, `build`, `available`). Strategies read factor columns and emit a `signal_<name>` (and optional `score_<name>`) column; causal and future-leak free.
- `src/strategies/impl.py` — two strategy types: `weighted` (normalise each factor to [-1,1], form a weighted composite score, map to a signal via buy/sell thresholds) and `rule` (boolean AND/OR of factor conditions -> long/flat). A missing factor column raises `DataError`; malformed params raise `ConfigError`.
- `src/strategies/engine.py` — `StrategyEngine`: composes `FactorEngine` (indicators -> factors -> strategies), builds from `IndicatorConfig` + `FactorConfig` + `StrategyConfig`, computes per-stock, and reads bars through `DataManager` via `compute_code`.
- `src/strategies/portfolio.py` — `Portfolio`: turns signals into positions and marks the book to market with close-to-close returns, using only data known at bar *t* (the position held at t-1 earns the t->t+1 return) — no look-ahead.
- `src/strategies/__init__.py` — public exports.
- `core/config.py` — `WeightSpec` / `WeightedParams` / `ConditionSpec` / `RuleParams` / `StrategySpec` / `StrategyConfig` models, wired into `AppConfig.strategies`.
- `config/settings.yaml` — `strategies.enabled` default set: `weighted_momentum` (8-factor weighted composite) and `golden_cross_rule` (MA cross AND MACD cross AND RSI not overbought).
- `main.py` — new `strategies` command: `strategies --list` and `strategies CODE [--name ...] [--start ...] [--end ...]`.
- `tests/test_strategies.py` — strategy correctness, engine orchestration, missing-column `DataError`, malformed-param `ConfigError`, `Portfolio` position and equity behaviour, and a **no-future-leak** invariant test at the engine level (the signal at bar *t* computed on the full pipeline equals the value computed on bars `0..t`).

### Notes

- Strategies reference the factor **output columns** (for example `ma_dist_20`, `macd_cross`, `rsi_signal_14`) produced by the factor layer, not the factor registry names — keeping the factor/strategy wiring fully config-driven.
- The whole indicators -> factors -> strategies pipeline inherits the *禁止未来函数* guarantee: a signal at bar *t* depends only on data at bars `<= t`.
- `Portfolio` is the bridge to the backtest engine (Sprint 1.6): it derives positions from signals but does not yet apply costs, slippage, or sizing.

## Sprint 1.4 — Factor Engine (2025-07-14)

### Added

- `src/factors/base.py` — `BaseFactor` base class + registry (`register`, `build`, `available`). Factors are pure, causal functions built on top of indicator columns.
- `src/factors/impl.py` — eight factors, all config-driven and **future-leak free**: `ma_distance`, `ma_cross`, `rsi_signal`, `macd_cross`, `kdj_cross`, `vol_ratio`, `boll_position`, `momentum`.
- `src/factors/engine.py` — `FactorEngine`: composes the `IndicatorEngine` (indicators first, then factors), builds from `IndicatorConfig` + `FactorConfig`, computes per-stock, and reads bars through `DataManager` via `compute_code`.
- `src/factors/__init__.py` — public exports.
- `core/config.py` — `FactorSpec` / `FactorConfig` models, wired into `AppConfig.factors`.
- `config/settings.yaml` — `factors.enabled` default set (each factor references the indicator windows produced by the indicator layer).
- `main.py` — new `factors` command: `factors --list` and `factors CODE [--name ...]`.
- `tests/test_factors.py` — factor correctness, engine orchestration, missing-column `DataError`, and a **no-future-leak** invariant test (indicators + factor at bar *t* computed on the full series equals the value computed on bars `0..t`).

### Notes

- Factors only read columns already present in the frame (indicator outputs + raw `close`/`volume`), so the indicator + factor pipeline inherits the *禁止未来函数* guarantee.
- A factor whose required indicator column is missing (misconfigured `factors` vs `indicators`) raises `DataError` immediately.
- `Roadmap.md` added to track sprint status across the development workflow.

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
