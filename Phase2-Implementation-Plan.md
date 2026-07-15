# AROS Phase 2 — Quant Research Engine (Implementation Plan)

> Status: **Implementation plan** (aligned to code on `main` = Sprints 1.1–1.16); direction accepted by ChatGPT.
> **Primary reference**: `Phase2-Research-Engine-Revision.md` — single source of truth
> reconciling GPT's original idea (1.1–1.8 baseline) with the real 1.1–1.16 state.
> **Foundation contract**: `Sprint2.0-Technical-Design.md` — the framework (schemas /
> interfaces / module boundaries) both sides freeze **before** any code lands.
> This file is the sprint-by-sprint implementation roadmap (2.0–2.6). Each sprint still
> requires ChatGPT PASS + CI green before the next begins.

## 1. Goal of Phase 2

Phase 1 built a *lab*: per-stock signals, cost-aware backtests, cross-sectional
ranking, daily reports, watchlist tracking, caching, universe pools, HTML
reports, scheduling, and a basic equal-weight portfolio backtest — all on
`main`, four gates green.

Phase 2 turns that lab into a *research engine*: a systematic way to **define,
run, compare, and validate** strategies as named, reproducible **experiments**
with **benchmarks** and **out-of-sample (walk-forward) proof** — answering
"which strategy is actually best?" instead of eyeballing single backtests.

Confirmed principles (carry from Phase 1, non-negotiable):
- **No future functions** — every value at bar *t* depends only on data `<= t`.
- **Single data entry** — all prices through `DataManager`.
- **Configurable** — every knob in `config/settings.yaml`.
- **Testable + gated** — `ruff` / `black` / `mypy` / `pytest`; a sprint advances
  only after **ChatGPT PASS** and **CI green**.
- **Reuse, don't rebuild** — Phase 2 is a *thin orchestration + persistence +
  reporting* layer over the existing engines.

## 2. Reuse Map (the part GPT's original plan got wrong)

GPT's original plan proposed `research/metrics.py`, `research/benchmark.py`,
etc. as *new* modules. They must instead **reuse / extend** what already exists,
so we don't fork the metric math:

| Phase 2 need | Reuse / extend | Do NOT |
|---|---|---|
| Performance metrics (profit factor, calmar, avg holding days, max consecutive losses, exposure) | **EXTEND** `src/backtest/metrics.py` + `compute_metrics` dispatcher (1.6) | create `research/metrics.py` |
| Strategy signals | `StrategyEngine` (1.5) | re-implement |
| Single-code backtest | `BacktestEngine` (1.6) | re-implement |
| Multi-code portfolio | `PortfolioBacktest` (1.16) | re-implement |
| Candidate universe | `UniverseEngine` (1.13) | new pool module |
| Persistence | `core.database` (`Base`, `get_engine`, `get_sessionmaker`) — same ORM pattern as `BacktestPoint` / `RankingPoint` | new DB layer |
| Report rendering | follow `DailyReport.to_markdown/to_json/to_html` style (1.8 / 1.14) | new renderer |
| Periodic experiments (later) | `Scheduler` (1.15) | new scheduler |

## 3. Prerequisites — Sprint 2.0 (foundation)

Two gaps must close before the research engine is meaningful. They are *data and
persistence* work, not "research" per se, so they are a standalone foundation sprint.

> **Sprint 2.0 has its own frozen contract** in `Sprint2.0-Technical-Design.md`
> (ORM schemas, provider/manager interfaces, `research/` skeleton, config, test
> contract, and 6 open decisions for sign-off). The summary below is the roadmap
> view; the technical design is authoritative for implementation.

### 2.0a — Index / benchmark data in `DataManager` (1.2)
- Add an index-data path: AKShare index daily (`ak.index_zh_a_hist` / `ak.stock_zh_index_daily`), wrapped behind the existing `DataProvider` protocol.
- New ORM `IndexBar` (separate from per-stock `DailyBar`): `code`, `date`, `open/high/low/close/volume`, unique `(code, date)`; `DataManager.get_index_daily(code, start, end)`.
- `config/settings.yaml`: `benchmark.indices` mapping (name → code), default `{csi300: 000300, csi500: 000905, csi1000: 000852, sh_composite: 000001}`.
- Tests: FakeProvider returning synthetic index bars; as_of truncation (no future leak).

### 2.0b — Experiment persistence on `core.database`
- New ORM models (on `core.database.Base`):
  - `ExperimentRun` — `id` (short uuid), `name`, `config_json`, `status` (created/running/done/failed), `created_at`, `finished_at`, `notes`.
  - `ExperimentMetric` — `run_id`, `metric_name`, `value`, `is_oos` (bool), `window` (nullable).
  - `ExperimentEquity` — `run_id`, `window`, `is_oos`, `equity_json`.
- `get_sessionmaker` already supports explicit engines; reuse it.
- Tests: CRUD on in-memory sqlite; `config_json` round-trip.

## 4. Sprint plan

### Sprint 2.1 — Experiment Registry & Config
- **Scope**: define a fully serializable experiment and a registry to create / store / list / show / delete runs.
- **Files**: `src/research/experiment.py` (`ExperimentConfig` pydantic — universe ref-or-codes, strategy spec ref, date range, train/test split params, seed, metrics list, benchmark code; `ExperimentRun`; `ExperimentRegistry`); extend `core/config.py` (`ResearchConfig` → `AppConfig.research`); `config/settings.yaml` `research` section; `main.py` `research init|list|show|delete`.
- **Reuse**: `core.database` for `ExperimentRun`/`ExperimentMetric`/`ExperimentEquity`; `UniverseEngine` (1.13) to resolve `universe` → codes.
- **Acceptance**: config round-trip; registry CRUD on in-memory sqlite; CLI smoke; four gates green. No network needed.

### Sprint 2.2 — Metrics Extension (no new module)
- **Scope**: add the metrics GPT's plan wanted, **into** `src/backtest/metrics.py`.
- **New metrics**: `profit_factor`, `calmar`, `avg_holding_days`, `max_consecutive_losses`, `exposure`. Register each in `compute_metrics` dispatcher; extend `BacktestConfig.metrics` allowed set.
- **Files**: edit `src/backtest/metrics.py` + `metrics` tests only.
- **Acceptance**: each new metric has a unit test with a hand-checked value; all pre-existing `test_backtest.py` still green; four gates green.

### Sprint 2.3 — Benchmark Comparison
- **Scope**: compare a portfolio's equity curve against an index benchmark.
- **Files**: `src/research/benchmark.py` (`BenchmarkEngine.compare(portfolio_equity, benchmark_code, range)` → `excess_return`, `alpha`, `beta`, `tracking_error`, `information_ratio`); `core/config.py` `BenchmarkConfig`; extend `main.py` `research` (optional `--benchmark`).
- **Reuse**: `DataManager.get_index_daily` (2.0a) + `src/backtest/metrics.py`.
- **No future functions**: benchmark bars fetched with the same `as_of` ceiling as the portfolio.
- **Acceptance**: synthetic portfolio vs synthetic index; known beta cases (β=1 flat, β=0); four gates green.

### Sprint 2.4 — Research Runner (orchestration)
- **Scope**: one entry point that runs an experiment end-to-end.
- **Files**: `src/research/runner.py` (`ResearchRunner.run(config)` → load universe (1.13) → signals (1.5) → backtest (1.6 / 1.16) → metrics (1.6 extended) → benchmark (2.3) → persist (2.1 ORM) → return `ExperimentResult`). Engines injectable for tests.
- **CLI**: `research run --name X --universe POOL [--benchmark CODE] [--backtest]`.
- **Reuse**: thin orchestration only — zero metric/strategy/backtest math of its own.
- **No future functions**: enforces the same `as_of` ceilings the underlying engines already guarantee.
- **Acceptance**: full run on FakeSE/FakeDM stubs; result persisted and re-readable; four gates green.

### Sprint 2.5 — Walk-forward / Out-of-sample
- **Scope**: split the date range into rolling train/test windows; run the experiment per window; report IS vs OOS.
- **Files**: `src/research/walk_forward.py` (`WalkForward.split(train, test, step)` → windows; `WalkForward.run(runner, config)` → per-window `ExperimentResult` tagged `is_oos`; aggregate IS vs OOS metric means). Tag OOS metrics/equity in the 2.1 ORM.
- **No future functions**: each test window uses **only** data after its own train end; never leaks across the train/test boundary.
- **Acceptance**: split correctness; an OOS-metric test proves test-window computation sees no train data; determinism; four gates green.

### Sprint 2.6 — Research Report
- **Scope**: aggregate experiment + benchmark + walk-forward OOS into a shareable report.
- **Files**: `src/research/report.py` (`ResearchReport.to_markdown/to_json/to_html`); reuse the 1.8 / 1.14 rendering style (inline CSS + inline SVG for IS-vs-OOS bars); `main.py` `research report <id> [--format markdown|json|html]`.
- **Reuse**: rendering patterns from `DailyReport`, not a new renderer.
- **Acceptance**: output contains experiment id, OOS flag, benchmark columns; HTML self-contained + offline; four gates green.

## 5. Acceptance baseline (every sprint)

- `ruff check .` + `black --check .` + `mypy src tests main.py` + `pytest -q` all green.
- At least one **no-look-ahead** invariant test where the sprint touches data windows (2.0a, 2.3, 2.4, 2.5).
- ChatGPT PASS on the per-sprint design note before merge; CI green on GitHub Actions.
- No new metric math outside `src/backtest/metrics.py`.

## 6. Open questions for ChatGPT review

1. **Default benchmarks** — propose `{csi300, csi500, csi1000, sh_composite}`. Any others (e.g. a bond index as risk-free proxy for Sharpe)?
2. **Walk-forward default** — propose `train=3y / test=1y / step=1y`. Sensible for 2015–2026 A-share regime shifts?
3. **Risk-free rate** — Sharpe/Sortino currently use `BacktestConfig.risk_free`; for Phase 2 should we source a real risk-free series or keep the configurable constant?
4. **Schedulability** — should experiments be triggerable via the 1.15 `Scheduler` now, or defer that integration to a later sprint?
5. **Experiment identity** — short uuid vs human name as primary key? (Plan uses short uuid + unique name.)

## 7. Suggested order

`2.0 (index data + persistence)` → `2.1 (registry)` → `2.2 (metrics)` →
`2.3 (benchmark)` → `2.4 (runner)` → `2.5 (walk-forward)` → `2.6 (report)`.
2.0 must land first because 2.3/2.4 depend on index data and 2.1/2.4/2.5 depend
on experiment persistence.
