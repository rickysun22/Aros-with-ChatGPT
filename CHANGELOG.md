# Changelog

All notable changes to AROS are documented by Sprint.

## Sprint 3.1 — Strategy Library (2026-07-17)

Implements the 10 research strategies from Phase 3 design §7, each as a
:class:`ResearchStrategy` pairing the frozen `ResearchStrategySpec` contract
(D1–D5, D7) with a *pure, explainable* entry-signal generator. Per design
invariant: every signal at day T uses only data <= T (no look-ahead, no
leakage); logic is a small explicit rule set (no ML); output is a per-code,
per-date boolean `entry` signal feeding `EventBacktest` (T-day signal → T+1
open fill). The 3.1 `run_strategy` helper runs **every** strategy through
`EventBacktest` so all 10 share one comparable metric set (uniform V1.0
research); `portfolio`-engine strategies additionally expose `score()` for the
3.2 cross-sectional Top-N BatchRunner.

### Added

- `src/research/strategy_library.py` — the 10-strategy library, split by the
  D8 data-trust batches:
  - **Batch 1 (daily_full, high-confidence):** `ma_bull` 均线多头 (portfolio
    engine, MA cross + volume filter + Top-N), `high_breakout` 新高突破,
    `volume_breakout` 放量突破, `strong_pullback` 强势回踩, `leader_first_down`
    龙头首阴.
  - **Batch 2 (daily_approx):** `shrink_reversal` 缩量反包, `first_board` 首板,
    `second_board_relay` 二板接力 (board-specific limit rates land in 3.2).
  - **Batch 3 (needs_intraday, daily-approx research only — flagged as
    reference):** `high_board` 连板博弈, `sentiment_rebound` 情绪冰点修复 (uses
    an optional market-breadth index gate; intraday behaviour is out of scope
    and clearly marked).
  - Shared indicator helpers (`sma`, `is_limit_up` proxy at 9.5% close-to-prev
    close, `vol_ratio`); a module-level `STRATEGIES` registry; `get_strategy` /
    `list_strategies` / `run_strategy` entry points. Limit-up detection is a
    9.5% main-board proxy (board-specific 10%/20%/5% rates refined in 3.2).
- `tests/test_strategy_library.py` — 13 tests: every strategy's rule fires on
  crafted data; a no-look-ahead test pins "no entry before data exists"; the
  registry + `run_strategy` are wired; `ma_bull` runs the cross-sectional
  Top-N path. Two rules hardened during review: `strong_pullback` now requires
  a *recent shrinking-volume pullback* (not a low-volume relaunch day), and
  `shrink_reversal` uses the standard bullish-engulfing definition (close >=
  prior open, open <= prior close) instead of a gap-required one.

### Changed

- `src/research/__init__.py` — import `strategy_library` to trigger registration
  and export `ResearchStrategy`, `STRATEGIES`, `get_strategy`, `list_strategies`,
  `run_strategy` (the 3.1 strategy-instance API; the 3.0 contract-level
  `get_strategy` remains reachable via `research.strategy_spec`).

## Sprint 3.0 — Strategy Research Framework (2026-07-17)

Phase 3 foundation (the "地基" everything else builds on). Implements the
frozen Phase 3 design (🟢 Design Approved, `docs/Phase3-Technical-Design.md`):
the **Strategy Contract**, an **event-driven backtest engine** that coexists
with the 1.16 portfolio engine, and the **AROS Strategy Score** skeleton. No
strategy code yet — only standards + substrate. Three red-line gaps from the
design are honestly addressed: daily-only data, portfolio-only backtest, and
no broker interface.

### Added

- `src/research/strategy_spec.py` — the Phase 3 **Strategy Contract**
  (`ResearchStrategySpec`, alias `StrategySpec`): `category` (trend/strong/emotion),
  `engine` (portfolio/event), `universe` (csi800/all_a/custom, D7), holding
  period, entry/exit rules, `risk_control`, and `data_fidelity` (daily_full /
  daily_approx / needs_intraday, D3). Ships an in-process strategy registry
  (`register_strategy` / `get_strategy` / `list_strategies`) and a
  `UniverseResolver` whose `csi800` path **refuses an empty/undefined pool** to
  block the survivor-ship bias D6 forbids (the point-in-time constituent fetch
  itself lands in 3.2). Does not touch the 2.0 frozen `ExperimentConfig`.
- `src/backtest/event.py` — `EventBacktest` (constraint B answer): T-day close
  signal → **T+1 open entry**, position held until stop-loss / take-profit /
  max-holding-days expiry → **close exit** (daily approximation). Reuses the
  existing `CostModel` and `compute_metrics` exactly (no new metric math), so
  `event`-engine strategies emit the same metric set as `portfolio`-engine ones
  and are directly comparable. Equity is a cost-aware cash + mark-to-market book
  capped at `max_positions`; a no-look-ahead test pins "no position on day 0".
- `src/research/scorecard.py` — `Scorecard` (§4, E1–E5): 7-dimension weighted
  score (0–100) over the realised metric keys via cross-sectional min-max
  normalisation; `max_drawdown` is abs-then-reversed, `holding_experience`
  averages `avg_holding_days` + `max_consecutive_losses`. The E3 anti-overfit
  guard discounts the Sharpe dimension when walk-forward OOS decays > 50% vs IS.
  Pure function of `ScoreInput` list, hand-anchor tested.
- `src/core/config.py` — `ScorecardConfig` (weights + `oos_decay_*`); wired into
  `ResearchConfig.scorecard` (E5 — weights configurable, no code change needed).
- `config/settings.yaml` — `research.scorecard` block with the frozen 7 weights.
- Exports: `EventBacktest`/`EventResult` in `backtest`, and `Scorecard`/
  `ScoreInput`/`ScoreRow`/`StrategySpec`/`UniverseResolver`/registry helpers in
  `research`.
- Tests — 18 new cases: strategy contract enum guards + custom-universe guard +
  `UniverseResolver` D6 path; event backtest take-profit / stop-loss /
  max-holding-days / no-signal / no-look-ahead; scorecard hand-anchor (A=100,
  B≈52.67, C=0) + reverse-direction + holding-experience composite + OOS-decay
  penalty.

### Scope / non-goals

- No concrete strategy (those are Sprint 3.1). No point-in-time constituent
  fetch (Sprint 3.2). The runner injection of `EventBacktest` lands in 3.2.

## Sprint 2.6 — Research Report (2026-07-17)

Sprint 2.6 fills the `src/research/report.py` stub with `ResearchReport`, which
aggregates an experiment's metrics + benchmark comparison + walk-forward IS/OOS
into a shareable report (markdown / json / html). Rendering reuses the 1.8 / 1.14
`DailyReport` style — inline CSS and inline SVG bars — so the HTML is fully
self-contained and renders offline (no external JS/CSS). No new metric math: the
report only *presents* data the runner (2.4) and walk-forward runner (2.5) already
produced and persisted. A new `ExperimentRegistry.load_result(run_id)` reconstructs
an `ExperimentResult` from the DB (`ExperimentMetric` + `ExperimentEquity` rows,
windows ordered, IS/OOS flag derived) so a report can be rendered from a persisted run.

### Added

- `src/research/report.py`
  - `ResearchReport` dataclass with builders `from_run(run, result)` (DB row + reconstructed result; carries name / strategy / start / end / benchmark / status) and `from_result(result)` (stub fallback when only an in-memory result exists).
  - `to_dict` / `to_json` (UTF-8, indented) / `to_markdown` / `to_html`. Markdown shows each metric as `中文标签 \`raw_key\`` (raw key + Chinese label, machine-referenceable). HTML is self-contained: metadata header, IS-vs-OOS diverging-bar SVG (walk-forward runs only; single-run reports have no chart), and per-window detail tables — no `http(s)://` references.
  - `render_experiment_report(result)` stub entry point delegates to `ResearchReport.from_result(result).to_markdown()`.
- `src/research/registry.py` — `load_result(run_id) -> ExperimentResult | None` reads `ExperimentMetric` + `ExperimentEquity` grouped by window; returns `None` when the run is missing.
- `src/research/__init__.py` — export `ResearchReport` / `render_experiment_report`.
- `main.py` — `research report <id> [--format markdown|json|html]` (default markdown) loads the run + result via the registry and prints the report; the `research show` command is unchanged.
- `tests/test_research.py` — eight new 2.6 cases: markdown carries id + OOS flag + raw/bench keys; `render_experiment_report` stub; json round-trip; html self-contained + offline (no `<svg>` for single run); walk-forward report has IS/OOS section + SVG + IS-OOS decay; `load_result` DB round-trip (in-memory DB) feeding `from_run`; CLI `research report` for markdown / json / html (tmp DB).

### Scope / non-goals

- No ORM schema change, no new metric functions — only presentation + DB reconstruction.

## Sprint 2.5 — Walk-Forward / Out-of-Sample (2026-07-17)

Sprint 2.5 fills the `src/research/walk_forward.py` stub with `WalkForwardSplitter`
(date-only rolling-window arithmetic) and `WalkForwardRunner` (rolling OOS
orchestration). The runner reuses the entire 2.4 pipeline through a new
`ResearchRunner._execute_window` seam, so the backtest / metric / benchmark /
persist logic is written exactly once. No new metric math, no ORM schema change.

### Added

- `src/research/walk_forward.py`
  - `WalkForwardFold` dataclass (`index`, `train_start`, `train_end`, `test_start`, `test_end`; all `YYYY-MM-DD` strings).
  - `WalkForwardSplitter.split(spec, start, end) -> list[WalkForwardFold]` — pure `pd.DateOffset(years=N)` arithmetic (leap-day safe, never `date.replace`). A fold is included only when its *whole* test window fits inside `[start, end]`; the OOS window starts exactly where training ends (`test_start == train_end`) — the core no-look-ahead boundary. Returns `[]` when the range is shorter than `train + test`.
  - `WalkForwardRunner(config, session, notes)` — builds one `run_id`, computes IS (`is_<i>`) and OOS (`oos_<i>`) folds, then aggregates `is_agg` / `oos_agg` (per-metric mean over IS folds / OOS folds; `None`/`non-finite` skipped). `walk_forward=None` transparently delegates to `ResearchRunner` (single `"full"` window).
- `src/research/runner.py` — extract `ResearchRunner._execute_window(config, session, *, window, run_id, is_oos) -> ExperimentResult` from `run()`. `run()` now creates the run and delegates the single `"full"` window to it; the public signature is unchanged.
- `src/research/__init__.py` — export `WalkForwardSplitter` / `WalkForwardRunner` / `WalkForwardFold`.
- `main.py` — `research run` transparently dispatches to `WalkForwardRunner` when `--walk-forward TRAIN TEST STEP` is supplied; prints IS vs OOS aggregates side by side. Single-range runs are unchanged.
- `tests/test_research.py` — eight new walk-forward cases: splitter correctness + `test_start == train_end` boundary; too-short range ⇒ no folds; leap-year start (`2020-02-29` → `2021-02-28`); e2e produces the 6 windows and persists aggregates (`oos_agg` with `is_oos=True`); aggregation is the per-metric mean; range too short ⇒ `DataError`; `walk_forward=None` delegates to the single runner; CLI dispatch routes `--walk-forward` to `WalkForwardRunner`.

### No-look-ahead (double guarantee)

1. **Window isolation** — each fold runs on a `config.model_copy` bounded to that fold's `[start, end]`; the OOS fold's `start == train_end`, so it can never consume train-window data.
2. **Within-window ceiling** — `_execute_window` keeps the 2.4 `as_of` ceiling: the benchmark is capped at the portfolio's *own* last date inside the fold, so a later benchmark bar never leaks into the fold's metrics.

### Scope / non-goals

- Report rendering (2.6) is still untouched.
- No ORM schema change, no new metric functions — only splitting + orchestration + persistence.

## Sprint 2.4 — Research Runner (2026-07-17)

Sprint 2.4 fills the `src/research/runner.py` stub with `ResearchRunner`, the
orchestration + persistence layer that chains the engines shipped in 1.16 / 2.2 /
2.3 into one runnable, persistable experiment — and adds the `research run` CLI
that drives it. No new metric math: it reuses `PortfolioBacktest.from_config`,
`compute_metrics`, `BenchmarkEngine.compare`, and `ExperimentRegistry` exactly as
they are.

### Added

- `src/research/runner.py` — `ResearchRunner(data_manager=None, portfolio_fn=None, benchmark_engine=None, config=None).run(config, session=None, notes=None) -> ExperimentResult`. Pipeline: resolve candidates (universe XOR codes via `UniverseEngine`) → portfolio backtest (injected `portfolio_fn` seam, default `PortfolioBacktest.from_config`) → `compute_metrics` → `BenchmarkEngine.compare` → persist → return `ExperimentResult` keyed by window `"full"`.
- `src/research/registry.py` — three persistence helpers (`record_metrics` / `record_equity` / `mark_done`); all ORM writes stay in the registry. `record_metrics` coerces non-finite values (`inf`/`nan`) to `None` (sqlite-safe); `record_equity` serialises the curve as `{iso_date: value}` JSON; `mark_done` sets `status="done"` + `finished_at` (tz-aware UTC, naive column).
- `research run` CLI — `research run --name/--universe/--codes/--strategy/--start/--end/--benchmark/--metrics [--config] [--dry-run]`; reuses the 2.1 `_resolve_cli_experiment_config` helper. Dry-run prints the resolved config and never calls the runner.
- `research/__init__.py` — export `ResearchRunner`.
- `tests/test_research.py` — six new cases: end-to-end run persists metrics + equity and matches the independent benchmark reference; no-look-ahead (extra later benchmark bar never leaks); missing benchmark ⇒ `DataError`; unknown benchmark key ⇒ `ConfigError`; empty candidate set ⇒ `DataError`; `research run --dry-run` persists nothing.

### Changed

- Benchmark-relative metrics are stored under a `bench_` prefix (`bench_excess_return` / `bench_alpha` / `bench_beta` / `bench_tracking_error` / `bench_information_ratio`) alongside the portfolio metrics in `ExperimentMetric`.
- No-look-ahead ceiling is the **portfolio's own last date** (not the calendar experiment end), so a later benchmark bar cannot leak into `benchmark_return` during the metrics step.

### Scope / non-goals

- Single full-range window (`"full"`); walk-forward / OOS (2.5) and report rendering (2.6) are untouched.
- No ORM schema change, no new metric functions — only wiring + persistence.

## Sprint 2.3 — Benchmark Comparison (2026-07-16)

Sprint 2.3 fills the `src/research/benchmark.py` stub with a real
`BenchmarkEngine` that compares an experiment's equity curve against a benchmark
index pulled through `DataManager.get_index_daily` (the single data entry point,
with a no-look-ahead `as_of` ceiling). No new metric math leaves
`src/backtest/metrics.py`; the benchmark-relative maths (alpha/beta/TE/IR) lives
in `benchmark.py` and reuses the promoted `daily_returns` helper. No ORM/CLI
change — `BenchmarkConfig` (2.0), `ExperimentConfig.benchmark` (2.0) and the
`research init --benchmark` flag (2.1) already exist; the engine is consumed by
the 2.4 runner.

### Added

- `src/research/benchmark.py` — `BenchmarkEngine.compare(portfolio_equity, benchmark_code, range, risk_free=None, as_of=None)` returning a typed `BenchmarkComparison` dataclass (`+ to_dict()`), with five metrics computed on the inner-joined date window:
  - `excess_return` — portfolio period return minus benchmark period return (scale-invariant).
  - `beta` — `Cov(r_p, r_b) / Var(r_b)`; flat benchmark (`Var==0`) ⇒ `0.0`.
  - `alpha` — annualised CAPM alpha `(mean(excess_p) − beta·mean(excess_b)) × 252`.
  - `tracking_error` — annualised std of active returns `std(r_p − r_b) × √252`.
  - `information_ratio` — `mean(r_p − r_b) × 252 / tracking_error`; `TE==0` ⇒ `0.0`.
- `IndexDataSource` Protocol (mirrors `DataProvider`) so the data dependency is structurally injectable/testable.
- `research/__init__.py` — export `BenchmarkEngine` + `BenchmarkComparison`.
- `tests/test_research.py` — six cases: β=1 (equal), β=0 (flat portfolio), hand-checked five-metric values, no-look-ahead (default cap + explicit `as_of`), missing benchmark ⇒ `DataError`, unknown key ⇒ `ConfigError`.

### Changed

- `src/backtest/metrics.py` — promote private `_daily_returns` → public `daily_returns` (visibility-only; `compute_metrics` signature unchanged) so return math lives in one place and `benchmark.py` reuses it.

### No-look-ahead

- `as_of` defaults to `max(portfolio_equity.index)` and is passed straight to `get_index_daily`, so the benchmark fetch can never include data the portfolio could not have seen; an invariant test enforces this.

## Maintenance — CI gate hardening (2026-07-16)

The GitHub Actions CI ran `ruff` / `black` / `mypy` / `pytest` against
**unpinned** dev dependencies. Every time a new black/ruff/mypy release shipped,
the floating install diverged from the local venv and the `black --check .` gate
failed on otherwise-correct code (the 2.1 run #24 failure was this exact case).

### Changed

- `requirements.txt` — pin the gate toolchain to the versions already used in the
  local venv so CI reproduces local results:
  - `black==26.5.1`
  - `ruff==0.15.21`
  - `mypy==2.3.0`
  - `pytest==9.1.1`
- No source changes; `black .` is a no-op at the pinned version (68 files unchanged).

### Notes

- This also unblocks the three Sprint 2.0/2.1/2.2 commits that were authored
  locally but never pushed — remote `main` was still pre-2.0, so CI kept running
  against stale code. Pushing them together with the pin makes the gate stable.

## Sprint 2.2 — Metrics Extension (2026-07-16)

Sprint 2.2 adds the five performance metrics GPT's Phase 2 plan wanted — but
**into the existing `src/backtest/metrics.py` dispatcher**, not a new
`research/metrics.py` (forbidden by the 2.0 frozen decision). Pure functions
only; no signature change to `compute_metrics`, no ORM/CLI change, no network.

### Added

- `src/backtest/metrics.py` — five new scalar metrics:
  - `profit_factor` — gross profit / gross loss over daily equity returns (blotter carries no per-trade PnL); `inf` when no losing day, `0.0` when flat.
  - `calmar` — `cagr / abs(max_drawdown)`; `0.0` when `max_drawdown == 0`.
  - `avg_holding_days` — mean calendar-day gap between consecutive rebalances (from `trades["date"]`); `0.0` when `< 2` trades.
  - `max_consecutive_losses` — longest run of consecutive down days.
  - `exposure` — fraction of bars holding a non-zero weight, reconstructed from cumulative `weight_change` over the equity index.
  - All five registered in `compute_metrics`'s `available` dict (now selectable via `BacktestConfig.metrics`).
- `tests/test_backtest.py` — 10 hand-checked unit tests (each metric + edge cases: flat equity, no-drawdown, `< 2` trades, no trades).

### Frozen decisions (carried from 2.2 design, §6)

- D1 The five metrics are **not** added to the default `BacktestConfig.metrics` list — registered only in the dispatcher, so they are selectable without changing existing backtest outputs / snapshots.
- D2 `profit_factor` uses daily-return gross profit / gross loss (not per-trade PnL).
- D3 `exposure` reconstructs the held weight from cumulative `weight_change` over `equity.index`.
- D4 Edge values: `profit_factor` `inf` (no loss) / `0.0` (flat); `calmar` `0.0` (mdd==0); `avg_holding_days` `0.0` (`< 2` trades); `max_consecutive_losses` `0` (none).

### Notes

- Fully backward compatible: `compute_metrics` signature unchanged; the 2.1 `research` CLI and all existing callers unaffected. These metrics become the vocabulary for benchmark (2.3) / runner (2.4) / walk-forward (2.5) / report (2.6).
- All four gates green: ruff / black / mypy (68 files) / pytest 201 passed, 1 skipped.

## Sprint 2.1 — Research CLI Surface (2026-07-16)

Sprint 2.0 shipped the `ExperimentConfig` / `ExperimentRun` / `ExperimentRegistry`
classes and config wiring. Sprint 2.1 adds the command-line surface that the
Phase 2 plan owed under "2.1 — Registry & Config": a `research` Typer sub-app
(`init | list | show | delete`) plus a complete delete cascade that also clears
an experiment's `ExperimentMetric` / `ExperimentEquity` child rows.

### Added

- `main.py` — `research` Typer sub-app mounted on the root app (`app.add_typer(research_app, name="research")`).
  - `research init` — accepts either CLI flags (`--name --strategy --start --end --universe|--codes --benchmark --metrics --walk-forward --seed --notes`) **or** `--config <file.json|yaml>`; conflicts resolved with `--dry-run` (prints config, persists nothing). `--codes` and `--metrics` take comma-separated values. `--universe` and `--codes` are mutually exclusive; `--universe` is resolved against `UniverseEngine` and rejected (exit 1) if empty/unknown; `--strategy` is validated against `cfg.strategies.enabled` (exit 2 if absent).
  - `research list` — newest-first table of `RUN_ID | NAME | STATUS | CREATED_AT`.
  - `research show <run_id>` — full run metadata + validated `ExperimentConfig` JSON.
  - `research delete <run_id>` — cascades to `ExperimentMetric` / `ExperimentEquity`, then removes the run.
- `src/research/registry.py` — `delete` now deletes child `ExperimentMetric` / `ExperimentEquity` rows before the `ExperimentRun` (explicit cascade; no FK `ondelete`, per frozen decision D4).
- `tests/test_research.py` — 7 new CLI + cascade tests: init via flags / config file / both-sources reject / unknown-universe reject / dry-run / list-show-delete lifecycle / registry delete cascade.

### Frozen decisions (carried from 2.0 design, §10)

- D1 Typer sub-app `research init|list|show|delete`.
- D2 `universe` column stores the pool **name** only; code resolution deferred to the runner (2.4).
- D3 `--config` accepts both JSON and YAML.
- D4 Delete uses an explicit child-row cascade (no FK `ondelete`).
- D5 `WalkForwardSpec` is persisted now via `--walk-forward TRAIN TEST STEP`.
- D6 `init` includes `--dry-run`.
- D7 `init` validates `--strategy` against enabled strategies.

### Notes

- `ExperimentRegistry` still carries no run logic; the CLI only persists the
  frozen `ExperimentConfig`. Execution (runner) lands in Sprint 2.x.
- All four gates green: ruff / black / mypy (68 files) / pytest 191 passed, 1 skipped.

## Sprint 2.0 — Research Foundation (2026-07-16)

Phase 2 foundation: index/benchmark data + experiment persistence + `src/research/` skeleton. No forward-looking (2.1–2.6) logic — future modules are stubs that raise `NotImplementedError` with their target sprint.

### Added

- `src/data/models.py` — `IndexBar` ORM (separate table from `DailyBar`, `UniqueConstraint(code, date)`; nullable `volume`/`amount`).
- `src/data/provider.py` — `DataProvider.get_index_daily` added to the Protocol; `normalize_index_daily`; `AkShareProvider.get_index_daily` via `ak.index_zh_a_hist` (daily).
- `src/data/providers/astockdata.py` — `AStockDataProvider.get_index_daily` (deferred, raises `NotImplementedError`).
- `src/data/manager.py` — `sync_index` + `get_index_daily(..., as_of=...)` through the single `DataManager` entry; missing benchmark raises `DataError` (never silent).
- `src/core/config.py` — `BenchmarkConfig` (default `csi300`; csi300/csi500/csi1000/sh_composite index map) and `ResearchConfig` (experiment id prefix, metrics); wired into `AppConfig`.
- `config/settings.yaml` — `benchmark` and `research` sections.
- `src/research/models.py` — `ExperimentRun` (short-UUID string PK), `ExperimentMetric` (long-table form), `ExperimentEquity`.
- `src/research/experiment.py` — `WalkForwardSpec`, `ExperimentConfig` (frozen Phase 2 protocol; `universe`/`codes` mutually exclusive), `ExperimentResult`.
- `src/research/registry.py` — `ExperimentRegistry` CRUD (session-injected); no run logic.
- `src/research/{benchmark,runner,walk_forward,report}.py` — stubs only (Sprint 2.x pointers).
- `src/research/__init__.py` — public exports; explicit guard note: **no** `research/metrics.py` (metrics live in `src/backtest/metrics.py`).
- `tests/test_research.py` — 12 tests: index normalize/roundtrip, `as_of` no-look-ahead, missing-benchmark `DataError`, registry CRUD, metric uniqueness, config validation, UUID PK uniqueness, config wiring, network-gated real-index smoke.

### Frozen decisions

- `IndexBar` is a separate table from `DailyBar`.
- AKShare index interface: `index_zh_a_hist`.
- Experiment primary key: UUID (short-uuid string).
- `ExperimentMetric`: long-table design.
- No `research/metrics.py`; reuse `src/backtest/metrics.py`.
- `DataManager` remains the sole data entry point.
- `ExperimentConfig` is the frozen Phase 2 experiment protocol.

### Notes

- No look-ahead: `get_index_daily` honours an `as_of` ceiling identical to the equity path.
- Scope strictly limited to Sprint 2.0; walk-forward / runner / benchmark-alignment / report land in 2.1–2.6.

## Sprint 1.16 — Portfolio Backtest (2026-07-15)

### Added

- `src/backtest/portfolio.py` — `PortfolioBacktest` + `PortfolioResult`: selects Top-N candidates by composite score and builds an equal-weight rebalanced portfolio; reuses single-code equity curves from `BacktestEngine`; benchmark = buy & hold across the full candidate set. `rank_fn` / `equity_fn` are injectable for testing.
- `src/backtest/__init__.py` — public exports `PortfolioBacktest`, `PortfolioResult`.
- `main.py` — new `portfolio` command.
- `tests/test_portfolio.py` — selection, equal-weight combination, benchmark, no-data zeros, injectable stubs.
- `Sprint1.16-Portfolio-Backtest-Design.md` — design doc.

### Notes

- No future functions: the selection window and rebalance both converge on the per-candidate `as_of` ceiling.
- This is the equal-weight Top-N baseline; richer weighting / risk-based rebalancing is deferred.

## Sprint 1.15 — Scheduler + Notifier (2026-07-15)

### Added

- `src/scheduler/notify.py` — `Notifier` abstraction + three implementations: `ConsoleNotifier`, `FileNotifier`, `WebhookNotifier` (best-effort HTTP POST; no-op when URL is `None`); `build_notifier(SchedulerConfig)`.
- `src/scheduler/engine.py` — `Scheduler` with `run_ntimes(task, interval, n)` and `run_loop(task, interval, stop_event)`; task exceptions are caught so the loop never dies.
- `src/scheduler/__init__.py` — public exports.
- `core/config.py` — `SchedulerConfig` (notifier_type / webhook_url / file_path), wired into `AppConfig.scheduler`.
- `config/settings.yaml` — `scheduler` section.
- `main.py` — new `schedule` command: `--report [CODES...] [--universe POOL] [--backtest]`, `--watchlist [--backtest]`, `--every N` (minutes) / `--once`.
- `tests/test_scheduler.py` — offline tests (console/file, no-op webhook, interval ticking, error isolation).
- `Sprint1.15-Scheduler-Design.md` — design doc.

### Notes

- Runs without any external credentials; the webhook is a no-op when `webhook_url` is unset.
- Reuses existing report/watchlist generation; only repeats it on an interval, so the `as_of` window stays look-ahead free.

## Sprint 1.14 — Report HTML (2026-07-15)

### Added

- `src/report/engine.py` — `DailyReport.to_html(include_detail=True)`: self-contained HTML with inline CSS and inline SVG horizontal bar charts (bars normalised on composite score), full table (incl. 1.10 backtest columns), and a detail card grid. Text is HTML-escaped.
- `core/config.py` — `ReportConfig.format: Literal["markdown","json","html"]`.
- `main.py` — `report ... --format html` (optionally `--out report.html`).
- `tests/test_report.py` — HTML output assertions (doctype, svg, bars, codes, 综合分, backtest columns when enabled).
- `Sprint1.14-Report-HTML-Design.md` — design doc.

### Notes

- Zero-dependency and offline-openable; the render layer introduces no new data or window, so no future functions are introduced.

## Sprint 1.13 — Universe / Stock-pool (2026-07-15)

### Added

- `src/universe/models.py` — `UniversePool` ORM (`name` PK, `description`, `codes_json`, `created_at`, `updated_at`).
- `src/universe/engine.py` — `UniverseEngine` (session-bound, shared DB): `add_codes` (dedupe + lexical sort), `remove_codes`, `get_codes`, `exists`, `list_pools`, `delete`.
- `src/universe/__init__.py` — public exports.
- `main.py` — new `universe` command (`add|remove|list|show|delete`) and `report --universe POOL` (mutually exclusive with positional codes).
- `tests/test_universe.py` — 6 isolated in-memory SQLite tests.
- `Sprint1.13-Universe-Design.md` — design doc.

### Notes

- `Universe` only answers "where do the codes come from"; it does not change ranking/backtest semantics. Watchlist keeps its own membership table and does not depend on universe.

## Sprint 1.12 — Backtest Cache (2026-07-15)

### Added

- `src/backtest/cache.py` — `BacktestCache` ORM (`code`, `params_hash`, `start`, `end`, `signal_col`, `metrics_json`, `equity_json`, `created_at`; unique on `(code, params_hash)`) + `get_cached()` / `store()` (best-effort).
- `src/backtest/engine.py` — `run_code` now does get-or-compute against the cache; `BacktestEngine.run_code(use_cache=True)`.
- `core/config.py` — `BacktestConfig.cache_enabled` (default `True`).
- `config/settings.yaml` — `backtest.cache_enabled`.
- `tests/test_backtest.py` — cache hit skips recompute / distinct codes / hash determinism.
- `Sprint1.12-Backtest-Cache-Design.md` — design doc.

### Notes

- `params_hash` folds every input that changes the simulation (signal column, cost, initial cash, max position, benchmark flag, start/end), so a new `as_of` naturally misses.
- All cache access is best-effort: any DB error is caught and degrades to live computation, so caching never blocks a backtest.

## Sprint 1.11 — Watchlist Backtest Persistence (2026-07-15)

### Added

- `src/watchlist/models.py` — `BacktestPoint` ORM (`as_of`, `code`, `total_return`, `max_drawdown`, `sharpe`, `benchmark_return`, `created_at`; unique on `(as_of, code)`; fields nullable so no-data codes do not get a point).
- `src/watchlist/engine.py` — `BacktestSummary` dataclass; `WatchlistMember.backtest` / `prev_backtest`; `WatchlistDigest.backtest_included`; lazy `_get_bt_engine` + `_backtest_snapshot` / `_upsert_backtest_point` / `_backtest_point_map`; snapshot persists points and computes return deltas vs the previous point.
- `src/watchlist/__init__.py` — export `BacktestPoint` / `BacktestSummary`.
- `core/config.py` — `WatchlistConfig.include_backtest` (default `False`).
- `main.py` — `watchlist snapshot --backtest`.
- `tests/test_watchlist.py` — backtest coverage incl. `test_snapshot_backtest_no_lookahead`.
- `Sprint1.11-Watchlist-Backtest-Design.md` — design doc.

### Notes

- No future functions: same `as_of` ceiling as 1.10; deltas are a pure read of stored history. Backtest result rendering appends a "## 回测表现" section with return deltas.

## Sprint 1.10 — Report Backtest Enrichment (2026-07-15)

### Added

- `src/report/engine.py` — `ReportRow` gains `bt_total_return` / `bt_max_drawdown` / `bt_sharpe` / `bt_benchmark_return`; `DailyReport` gains `backtest_included`; `ReportEngine` gains a lazy `_get_bt_engine()` and `_backtest_snapshot`, and renders backtest columns in markdown/json.
- `core/config.py` — `ReportConfig.include_backtest` (default `False`).
- `config/settings.yaml` — `report.include_backtest`.
- `main.py` — `report ... --backtest`.
- `tests/test_report.py` — backtest coverage (injectable `backtest_fn` stub).
- `Sprint1.10-Report-Backtest-Design.md` — design doc.

### Notes

- Per-candidate backtest (one backtest per Top-N candidate), not portfolio backtest (deferred to 1.16).
- No future functions: backtest window `[start_date, as_of]` reuses the report's `as_of` ceiling. Only Top-N candidates are backtested to bound cost.

## Sprint 1.9 — Watchlist Tracker (2026-07-15)

### Added

- `src/watchlist/models.py` — two ORM models on `core.database.Base`: `WatchlistItem` (membership, soft-delete via `removed_at`) and `RankingPoint` (daily snapshot: as_of, code, full cross-sectional rank, composite_score, scores_json; unique on (as_of, code)).
- `src/watchlist/engine.py` — `WatchlistEngine` (add/remove/list_active/is_member, `snapshot` ranks the whole watchlist and persists every member including those that fall out of the Top-N, `history`, `deltas`) plus `WatchlistDigest` / `WatchlistMember` with `to_markdown()` / `to_json()`. `deltas` is a pure read of stored history (no network, no look-ahead).
- `src/watchlist/__init__.py` — public exports.
- `Sprint1.9-Watchlist-Design.md` — design doc.
- `core/config.py` — `WatchlistConfig` (alert_rank_jump) wired into `AppConfig.watchlist`.
- `config/settings.yaml` — `watchlist` section (alert_rank_jump=5).
- `main.py` — new `watchlist` command: `add/remove/list/snapshot/history/digest`.
- `tests/test_watchlist.py` — 12 tests (FakeSE + FakeDM + isolated temp SQLite): membership, full-rank snapshot incl. no-data codes, the six-state delta machine (new/dropped/up/down/steady/no_data), history ordering, as_of no-look-ahead, markdown/json rendering, real-config wiring, CLI smoke.

### Notes

- Reuses RankingEngine's full cross-section (`scored`) to compute a full cross-sectional rank so a watched code that drops out of the Top-N is still tracked; no new metric math is introduced.
- No future functions: `snapshot` drives RankingEngine with the same `as_of` ceiling; `deltas` only reads already-stored history.
- Rank relativity is internal to the watchlist (self-relative ranking), matching the "track my watched set" semantics.
- A code with no data at the cross-section is intentionally left without a point, so the next `deltas` reports it as `dropped` (not a null `no_data` row). The `no_data` state is reserved for a present-but-unrankable point (e.g. NaN composite score).

## Sprint 1.8 — Daily Report Engine (2026-07-15)

### Added

- `src/report/engine.py` — `ReportEngine` + `DailyReport` + `ReportRow`: a presentation/aggregation layer over the ranking output. It drives `RankingEngine` with its own `top_n`/`as_of`, takes the Top-N candidates, and enriches each with a latest price snapshot (close, daily change %, trade date, data-freshness flag) fetched from the `DataManager`. Renders to markdown (`to_markdown`) or json (`to_json`). No new metric math is introduced.
- `src/report/__init__.py` — public exports `ReportEngine`, `DailyReport`, `ReportRow`.
- `src/report` package + `Sprint1.8-Daily-Report-Design.md` (design doc).
- `core/config.py` — `ReportConfig` (top_n, as_of, format, freshness_days, include_detail), wired into `AppConfig.report`.
- `config/settings.yaml` — `report` section (top_n=20, as_of=null, format=markdown, freshness_days=5, include_detail=true).
- `main.py` — new `report` command: `report --list`, `report CODE [CODE ...] [--top-n N] [--as-of YYYY-MM-DD] [--start ...] [--end ...] [--format markdown|json] [--out FILE]`; prints (or writes) the daily research report.
- `tests/test_report.py` — sorted/scored output, price snapshot + daily change, Top-N cutoff, `as_of` cross-section with no-look-ahead snapshot, data-freshness (stale) flag, empty result, markdown table/detail toggles, json round-trip, dataclass helpers, real-config wiring, and a CLI smoke test.

### Notes

- No look-ahead is preserved end-to-end: the price snapshot ceiling follows the same `as_of` the ranking layer uses, so a candidate's close / daily change never sees a bar dated after the cross-section. A dedicated test asserts the snapshot uses only bars at/before `as_of`.
- The report is an aggregation/rendering layer only; it reuses the ranking composite score and adds no factor/indicator/metric computation.
- Daily change is computed only when at least two bars are visible; with a single visible bar it is reported as `None` rather than fabricated.

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
