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
| **2.1** | Research CLI Surface | completed | `research` Typer sub-app (`init|list|show|delete`); `init` via flags or `--config` (JSON/YAML) with `--dry-run`; `--universe` XOR `--codes`, universe resolved via `UniverseEngine`; `--strategy` validated; `delete` cascades to metrics/equity; 7 new CLI + cascade tests |
| **2.2** | Metrics Extension | completed | Five metrics added into `src/backtest/metrics.py` dispatcher (no new module): `profit_factor` / `calmar` / `avg_holding_days` / `max_consecutive_losses` / `exposure`; 10 hand-checked unit tests; `compute_metrics` signature unchanged |
| **2.3** | Benchmark Comparison | completed | `BenchmarkEngine.compare(...)` → typed `BenchmarkComparison` with `excess_return` / `alpha` / `beta` / `tracking_error` / `information_ratio` on the inner-joined window; benchmark bars via `DataManager.get_index_daily` (`as_of` no-look-ahead, default = portfolio end); `_daily_returns` promoted to public `daily_returns` (reused, no duplicated math); `IndexDataSource` Protocol for injectable data; 6 unit tests (β=1/β=0/hand-values/no-look-ahead/missing→`DataError`/unknown key→`ConfigError`); no ORM/CLI change |
| **2.4** | Research Runner | completed | `ResearchRunner.run(...)` orchestrates resolve-candidates → portfolio backtest → `compute_metrics` → `BenchmarkEngine.compare` → persist → `ExperimentResult`; `portfolio_fn` injection seam (default `PortfolioBacktest.from_config`); 3 registry helpers `record_metrics`/`record_equity`/`mark_done` (non-finite→`None`, equity as `{date:value}` JSON, tz-aware `finished_at`); benchmark metrics stored under `bench_` prefix; no-look-ahead capped at portfolio's own last date; `research run` CLI reuses 2.1 config helper; 6 new tests (e2e persist + hand-checked bench metrics / no-look-ahead / missing→`DataError` / unknown key→`ConfigError` / empty candidates→`DataError` / CLI dry-run); 213 passed, 1 skipped; no ORM schema change, no new metric math |
| **2.5** | Walk-Forward / OOS | completed | `WalkForwardSplitter.split(spec, start, end)` rolling IS/OOS windows via `pd.DateOffset` (leap-safe; OOS `test_start == train_end` no-look-ahead boundary; too-short range ⇒ `[]`); `WalkForwardRunner.run(...)` reuses the 2.4 pipeline via a new `ResearchRunner._execute_window` seam — one `run_id`, `is_<i>`/`oos_<i>` folds, aggregated `is_agg`/`oos_agg` (per-metric mean, `None`/non-finite skipped); `walk_forward=None` delegates to `ResearchRunner`; `research run --walk-forward TRAIN TEST STEP` prints IS vs OOS aggregates; double no-look-ahead guarantee (window isolation + within-window `as_of` ceiling); 8 new tests; no ORM schema change, no new metric math |
| **2.6** | Research Report | completed | `ResearchReport` aggregates metrics + benchmark + walk-forward IS/OOS into markdown/json/html (reuses `DailyReport` inline-CSS + inline-SVG style; HTML self-contained/offline, single-run has no chart); `from_run(run, result)` (DB metadata) + `from_result(result)` (stub fallback); `to_dict/to_json/to_markdown/to_html`; markdown shows `中文标签 \`raw_key\``; `render_experiment_report` stub delegates to `from_result`; `ExperimentRegistry.load_result(run_id)` reconstructs `ExperimentResult` from `ExperimentMetric`+`ExperimentEquity`; `research report <id> [--format markdown|json|html]` CLI; 8 new tests; no ORM schema change, no new metric math |
| **3.0** | Strategy Research Framework | completed | Phase 3 地基（设计 🟢 Design Approved）：`StrategySpec` 契约（category/engine/universe/holding/exit/risk/data_fidelity）+ 注册表 + `UniverseResolver`（D6 拒空池防幸存者偏差）；`EventBacktest`（T日信号→T+1开盘入场→止损/止盈/到期收盘离场，复用 CostModel+compute_metrics，与 portfolio 产出统一 metrics）；`Scorecard`（AROS Strategy Score 7维加权 0–100，E1–E5，含 OOS 衰减惩罚）；`ScorecardConfig` 接入 `settings.yaml`；18 新测试；四门禁全绿 |
| **3.1** | Strategy Library | completed | §7 的 10 套策略落地，`ResearchStrategy` = 冻结 `StrategySpec` 契约 + 纯函数可解释入场信号（无未来函数，T日信号→T+1开盘由 `EventBacktest` 执行）；按 D8 数据可信度分批：Batch1(daily_full) 均线多头/新高突破/放量突破/强势回踩/龙头首阴，Batch2(daily_approx) 缩量反包/首板/二板接力，Batch3(needs_intraday 仅日线近似研究、明确标注) 连板博弈/情绪冰点修复；指标 helper `sma`/`is_limit_up`(9.5%主板代理)/`vol_ratio`；`STRATEGIES` 注册表 + `get_strategy`/`list_strategies`/`run_strategy`；`run_strategy` 全策略走 `EventBacktest` 得统一 metrics 可比；13 新测试；四门禁全绿 |
| **3.2** | Batch Strategy Experiment | completed | `BatchRunner` 遍历 策略 × 冻结 `ExperimentConfig` × walk-forward（复用 2.5 切分 + 3.1 统一 `EventBacktest` 路径），每策略落库独立 `ExperimentRun`（`{config.name}:{strategy}`，`load_result` 可复现）；D7 池绑定经 `UniverseResolver` 取每策略 `universe`（csi800/all_a/custom）；无未来函数（基准截断到 equity 末日 + 事件引擎 reindex 交易日）；可选 regime 分段稳健性：每笔交易按入场日市场状态（Bull/Neutral/Bear/Extreme，`regime.py` 可解释规则）聚合；`price_provider`/`benchmark_provider`/`benchmark_engine` 可注入，合成数据端到端可测；8+9 新测试；四门禁全绿（含 CI `mypy src tests main.py`） |
| **3.3** | Strategy Evaluation & Ranking | completed | `Scorecard` 完整评分 + 排名落地（§4 E1–E5）：`build_score_inputs` 把 `BatchResult` 桥接为 `ScoreInput`（按 **OOS** walk-forward 指标评分，IS/OOS 供 E3 衰减惩罚，丢 `None`/非有限值防 `nan`）；`RankingReport` 渲染 §4 冻结排名表（md/json/html，含 OOS衰减 低/中/高 标签）并接入 `ResearchReport`；`BatchRunner` 增补 `profit_factor`/`avg_holding_days`/`max_consecutive_losses`（默认未算但 `compute_metrics` 可产）使评分维度齐全；E5 权重经 `settings.yaml` `research.scorecard` + `Scorecard.from_config` 驱动；14 新测试（手算锚定/反向指标/OOS惩罚/排名表）；四门禁全绿（含 CI `mypy src tests main.py`） |

## Principles (non-negotiable)

- `DataManager` is the **single data entry** point.
- **No future functions** — every indicator/factor value at bar *t* depends only on data `<= t` (enforced by an automated truncation test).
- All parameters are **configurable** (see `config/settings.yaml`).
- Every module is **testable** and gated by `pytest` / `ruff` / `black` / `mypy`.
- A sprint may advance only after ChatGPT PASS.

## Next up

Sprints 1.1–1.16 **and Sprints 2.0–2.5** are complete and on `main`; all four
quality gates (ruff / black / mypy / pytest) are green locally. Sprint 2.0 landed
the **Phase 2 foundation** — index/benchmark data through `DataManager` and
experiment-result persistence on `core.database` — Sprint 2.1 added the
`research` CLI surface (`init|list|show|delete`), Sprint 2.2 extended
`src/backtest/metrics.py` with five new metrics (no new module), Sprint 2.3
filled the `benchmark.py` stub with `BenchmarkEngine.compare(...)` producing
`excess_return` / `alpha` / `beta` / `tracking_error` / `information_ratio`
(no-look-ahead via `as_of`, `daily_returns` reused — no duplicated math), Sprint
2.4 chained those engines into `ResearchRunner.run(...)` + the `research run` CLI
(no new metric math, no ORM schema change), and Sprint 2.5 added rolling
walk-forward / out-of-sample validation via `WalkForwardSplitter` +
`WalkForwardRunner` (reusing the 2.4 pipeline through a new `_execute_window`
seam; `is_agg`/`oos_agg` aggregation; `research run --walk-forward TRAIN TEST STEP`
prints IS vs OOS side by side). The reconciled Phase 2 plan (aligned to 1.16)
remains in `Phase2-Research-Engine-Revision.md` and `Phase2-Implementation-Plan.md`
(single source of truth). Sprint 2.6 added `ResearchReport` — markdown / json /
html rendering of an experiment's metrics + benchmark comparison + walk-forward
IS/OOS, plus `ExperimentRegistry.load_result` to reconstruct a result from the DB
and a `research report <id> [--format ...]` CLI (reuses the `DailyReport` inline
CSS + SVG style; HTML self-contained and offline). All four quality gates are
green locally. **Phase 2 is now complete** — the research engine (2.0–2.6) is
fully implemented and on `main`.

## Phase 3 — Alpha Research / Strategy Discovery

**状态：Sprint 3.1 已完成（策略库，10 套策略落地）**，设计 `docs/Phase3-Technical-Design.md` 已 🟢
Design Approved（ChatGPT PASS，含 D6 幸存者偏差 / D7 股票池冻结 / D8 按数据可信度排序）。3.0 地基 + 3.1 策略库均已提交 `main`，四门禁全绿。

约束（三条红线，已在设计中诚实处理）：① 数据只有日线（无分钟/tick）；② 回测是
组合再平衡，3.0 新增 `EventBacktest` 补齐事件驱动；③ 无券商接口，「可实盘执行」=
信号可复现产出（不含真实下单）。

下一步（待 ChatGPT PASS 后推进）：
- **3.2 Batch Strategy Experiment** — `BatchRunner` 遍历 策略 × 冻结实验配置，全走
  walk-forward，落库；含 point-in-time 成分获取（D6）。3.1 已把所有策略收敛到统一的
  `EventBacktest` 指标集，3.2 直接复用即可公平横评。
- **3.3 Strategy Evaluation & Ranking** — `Scorecard` 完整评分 + 排名，接入 Report。
- **3.4 Strategy Combination** — 分市场环境配权。
- **3.5 Market Regime Engine** — 可解释规则分类（牛/震荡/熊/情绪冷热），产出 V1.0 报告。
