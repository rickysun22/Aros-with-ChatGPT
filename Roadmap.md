# AROS Roadmap

Sprint plan for the A-Share Research Operating System. Status is updated after
each sprint passes review (ChatGPT PASS) and CI is green.

> Workflow: WorkBuddy develops + commits + pushes + updates CHANGELOG;
> ChatGPT reviews + updates this Roadmap; GitHub Actions runs CI. The next
> sprint starts **only after** ChatGPT announces PASS.

## Pipeline

`data → indicators → factors → strategies → backtest → ranking → report`

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

## Principles (non-negotiable)

- `DataManager` is the **single data entry** point.
- **No future functions** — every indicator/factor value at bar *t* depends only on data `<= t` (enforced by an automated truncation test).
- All parameters are **configurable** (see `config/settings.yaml`).
- Every module is **testable** and gated by `pytest` / `ruff` / `black` / `mypy`.
- A sprint may advance only after ChatGPT PASS.

## Next up

Sprint 1.5 (Strategy Engine) turns the factor layer into concrete, testable
short-term trading signals/strategies. It will reuse `FactorEngine` outputs and
keep the same config-driven, no-future-leak, single-data-entry design.
