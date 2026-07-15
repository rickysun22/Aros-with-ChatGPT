# AROS Roadmap

Sprint plan for the A-Share Research Operating System. Status is updated after
each sprint passes review (ChatGPT PASS) and CI is green.

> Workflow: WorkBuddy develops + commits + pushes + updates CHANGELOG;
> ChatGPT reviews + updates this Roadmap; GitHub Actions runs CI. The next
> sprint starts **only after** ChatGPT announces PASS.

## Pipeline

`data → indicators → factors → strategies → backtest → ranking → report → watchlist → backtest-cache → universe → html-report → scheduler → portfolio-backtest`

## Sprints

| Sprint | Scope | Status | Notes |
|--------|-------|--------|-------|
| **1.1** | Project Foundation | ✅ completed | scaffold, config, logging, db, CLI, tests |
| **1.2** | Data Layer | ✅ completed | ORM models, AKShare provider, `DataManager` (single entry), `astockdata` fallback |
| **1.3** | Indicator Engine | ✅ completed | MA/EMA/RSI/MACD/KDJ/BOLL/VOL_MA; config-driven; no future leakage |
| **1.4** | Factor Engine | ✅ completed | 8 factors on indicator columns; config-driven; no future leakage |
| **1.5** | Strategy Engine | completed | weighted + rule strategies; StrategyEngine + Portfolio; config-driven; no future leakage |
| **1.6** | Backtest Engine | completed | cost-aware A-share backtest over strategy signals; CostModel + metrics + BacktestEngine |
| **1.7** | Ranking Engine | completed | cross-sectional composite-score ranking over candidates; RankingEngine + RankingConfig + CLI |
| **1.8** | Daily Report | completed | aggregate ranking Top-N into a markdown/json daily research report; ReportEngine + ReportConfig + CLI |
| **1.9** | Watchlist Tracker | completed | persist daily ranking of watched stocks + day-over-day deltas (new/dropped/up/down/steady); WatchlistEngine + WatchlistConfig + CLI |
| **1.10** | Report Backtest Enrichment | completed | per-candidate backtest metrics in daily report (total return / max drawdown / sharpe / benchmark); ReportConfig.include_backtest; `report --backtest` |
| **1.11** | Watchlist Backtest Persistence | completed | `BacktestPoint` ORM + return deltas; WatchlistMember.backtest/prev_backtest; `watchlist snapshot --backtest`; WatchlistConfig.include_backtest |
| **1.12** | Backtest Cache | completed | `BacktestCache` ORM + get-or-compute; results cached by params_hash; best-effort (DB errors degrade to live); BacktestConfig.cache_enabled |
| **1.13** | Universe / Stock-pool | completed | `UniversePool` + `UniverseEngine` (add/remove/list/contains); `universe` CLI + `report --universe` |
| **1.14** | Report HTML | completed | `DailyReport.to_html()` self-contained (inline CSS + SVG bars, backtest columns); ReportConfig.format=markdown/json/html; `report --format html` |
| **1.15** | Scheduler + Notifier | completed | `Scheduler` (run_ntimes/run_loop) + `Notifier` (Console/File/Webhook no-op without URL); `schedule` CLI (--every/--once/--report/--watchlist) |
| **1.16** | Portfolio Backtest | completed | `PortfolioBacktest` Top-N rebalanced equal-weight portfolio vs buy&hold benchmark; injectable rank_fn/equity_fn; `portfolio` CLI |
| **2.0** | Research Foundation | completed | Phase 2 foundation: `IndexBar` + `DataManager.sync_index/get_index_daily` (`index_zh_a_hist`, `as_of` safe); `BenchmarkConfig`/`ResearchConfig`; `src/research/` skeleton — `ExperimentRun`/`ExperimentMetric`/`ExperimentEquity` ORM, `ExperimentConfig` (frozen protocol), `ExperimentRegistry` CRUD; runner/walk-forward/benchmark/report are 2.x stubs |

## Principles (non-negotiable)

- `DataManager` is the **single data entry** point.
- **No future functions** — every indicator/factor value at bar *t* depends only on data `<= t` (enforced by an automated truncation test).
- All parameters are **configurable** (see `config/settings.yaml`).
- Every module is **testable** and gated by `pytest` / `ruff` / `black` / `mypy`.
- A sprint may advance only after ChatGPT PASS.

## Next up

Sprints 1.1–1.16 **and Sprint 2.0** are complete and on `main`; all four quality
gates (ruff / black / mypy / pytest) are green locally. Sprint 2.0 landed the
**Phase 2 foundation** — index/benchmark data through `DataManager` and
experiment-result persistence on `core.database` — per
`Sprint2.0-Technical-Design.md` and the seven frozen decisions. The reconciled
Phase 2 plan (aligned to 1.16) remains in `Phase2-Research-Engine-Revision.md`
and `Phase2-Implementation-Plan.md` (single source of truth). Next up is
**Sprint 2.1+**: benchmark alignment, experiment runner, and walk-forward /
out-of-sample validation — currently `NotImplementedError` stubs in
`src/research/`.
