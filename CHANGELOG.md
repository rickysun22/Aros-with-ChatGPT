# Changelog

All notable changes to AROS are documented by Sprint.

## Sprint 1.7 — Ranking Engine (2026-07-15)

### Added

- `src/ranking/engine.py` — `RankingEngine`: cross-sectional composite-score ranking over candidate stocks. Reuses `StrategyEngine` to produce `score_<name>` columns, then combines them (configured weights, normalised by sum of absolute weights) into a composite score per stock at a chosen cross-section (latest bar, or `as_of`), sorts descending, and returns the Top-N watch-list plus the full scored cross-section.
- `src/ranking/__init__.py` — public export `RankingEngine`.
- `src/ranking` package + `Sprint1.7-Ranking-Design.md` (design doc).
- `core/config.py` — `DimensionSpec` (strategy + weight, weight may be negative) and `RankingConfig` (top_n, as_of, dimensions), wired into `AppConfig.ranking`.
- `config/settings.yaml` — `ranking` section (top_n=20, as_of=null, dimensions=null => all enabled strategies equal weight).
- `main.py` — new `ranking` command: `ranking --list`, `ranking CODE [CODE ...] [--top-n N] [--as-of YYYY-MM-DD] [--start ...] [--end ...]`; prints a ranked Top-N table with composite + per-strategy score columns.
- `tests/test_ranking.py` — composite score correctness (equal / explicit / negative weights), Top-N cutoff, `as_of` cross-section selection, no-look-ahead guard, missing `code` column `DataError`, missing score column `DataError`, real-config wiring, and a CLI smoke test.

### Notes

- Sorting semantics (user-confirmed): each candidate keeps its strategy `score_<name>` at the cross-section; those scores are combined into a composite and sorted descending. This is a thin layer over the strategy engine and inherits the no-look-ahead guarantee from Sprint 1.5.
- `as_of` filters on the `date` column (get_daily returns an integer-indexed frame with a `date` column), so no future bar is ever visible at the cross-section.
- Cross-instrument allocation beyond ranking is out of scope; this sprint produces a ranked candidate list, not a portfolio.

## Sprint 1.6 — Backtest Engine (2026-07-15)

### Added

- `src/backtest/cost.py` — `CostModel`: A-share transaction cost model. Per-side commission (wan 2.5, min RMB 5), stamp tax (wan 5, sell-only), transfer fee (wan 0.1, both sides), and slippage (configurable, default 0). Pure, unit-testable `charge(notional, is_sell)`.
- `src/backtest/metrics.py` — pure performance-metric functions: `total_return`, `cagr`, `max_drawdown`, `sharpe`, `sortino`, `win_rate`, `num_trades`, `turnover`, `benchmark_return`, plus a `compute_metrics` dispatcher that selects metrics from `BacktestConfig.metrics` and raises `ConfigError` on unknown names.
- `src/backtest/engine.py` — `BacktestEngine`: composes `StrategyEngine` + `CostModel` + metrics. Reuses `Portfolio.positions` for target weights, then layers A-share costs on top of the no-cost mark-to-market primitive. Produces a cost-aware equity curve, a trade blotter, and a metrics dict. Supports single-code and per-code grouped (multi-code) backtests.
- `src/backtest/__init__.py` — public exports.
- `core/config.py` — `CostConfig` / `BacktestConfig` models, wired into `AppConfig.backtest` (strategy, initial_cash, max_position, risk_free, metrics list, benchmark flag, cost).
- `config/settings.yaml` — `backtest` section with `weighted_momentum` as the default strategy and 2024 A-share default rates.
- `main.py` — new `backtest` command: `backtest --list`, `backtest CODE [--strategy ...] [--start ...] [--end ...]`; prints metric summary + benchmark + last 10 equity rows.
- `tests/test_backtest.py` — cost model, metric correctness, cost-aware <= no-cost, trade blotter, `max_position` clamp, no-look-ahead truncation invariant, missing-signal `DataError`, unknown-metric `ConfigError`, full-pipeline integration on synthetic data, and a CLI smoke test.

### Notes

- No look-ahead is preserved: the position held at bar t is decided at t-1 close and earns the t-1 to t return; rebalance costs are charged at t-1 close using only data known by then. A truncation test guards this.
- Single instrument only (or per-code grouped); cross-instrument allocation is deferred to Sprint 1.7. Shorting (-1) is reserved and treated as FLAT with a warning.
- The cost notional is the traded dollar amount (absolute delta weight times equity); the design note literal price times equity product was a typo and is not used.

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
