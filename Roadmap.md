# AROS Roadmap

Sprint plan for the A-Share Research Operating System. Status is updated after
each sprint passes review (ChatGPT PASS) and CI is green.

> Workflow: WorkBuddy develops + commits + pushes + updates CHANGELOG;
> ChatGPT reviews + updates this Roadmap; GitHub Actions runs CI. The next
> sprint starts **only after** ChatGPT announces PASS.

## Pipeline

`data → indicators → factors → strategies → backtest → ranking → report → watchlist → backtest-cache → universe → html-report → scheduler → portfolio-backtest`

## Capability Architecture（四大引擎，对齐交易时间轴）

> **战略重定位**：AROS 从"选股系统"升级为 **AI 辅助投资决策系统**。能力建设顺序严格对齐真实交易时间轴（发现 → 买入 → 持有 → 卖出 → 复盘），而非按架构模块切分。

```
市场 → 发现股票 → 等待机会 → 买入 → 持有 → 退出 → 复盘
```

| 引擎 | 交易环节 | 解决痛点 | 落地阶段 |
|---|---|---|---|
| **Alpha Discovery Engine** | 发现 | 买什么？ | 已完成（4.0–4.6：知识库→验证→共识→市场/资金→报告→反馈→评分校准） |
| **Alpha Entry Engine** | 买入 | 什么时候买？ | Phase 4.7（Entry Score 合成层） |
| **Alpha Management Engine** | 持有 | 买了以后怎么办？ | 4.7/4.8 引擎内实现，Phase 5.5 组合层成熟 |
| **Alpha Exit Engine** | 卖出 | 什么时候卖？ | Phase 4.8（分级 Exit Signal） |

**三大核心评分（贯穿每日决策）**：① **Alpha Score**（股票质量，"值不值得研究？"）② **Entry Score**（买入时机，"现在是否适合买？"）③ **Exit Score / Exit Risk**（持仓风险，"是否应该离场？"）。

> **模拟交易（Paper Trading）= 验证环境，不占 Phase 编号**：贯穿 4.6–4.8，在无券商、不下单前提下验证"评分/买点/卖点"是否有效。已实现 `research/papertrade.py`（双轴正交、无前视）。

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
| **3.4** | Strategy Combination | completed | `CombinationEngine` 分市场环境（趋势市=Bull+Bear / 震荡市=Neutral+Extreme）对 Top-N AROS 策略做配权：每环境 raw=基准+类别适配偏置+该环境 regime 绩效倾斜，floor 后归一化（**权重归一**）；组合指标 = 按权重对各策略 **OOS 指标加权混合**（复用 `compute_metrics` 既有产物，丢 `None`/非有限值，不重新计算）；附合成示意净值（明确标注、不参与派生指标避免伪造波动）；`env_for_regime()` 供 3.5 动态选策略调用；`CombinationConfig` 接入 `settings.yaml` `research.combination`（E5）；接入 `ResearchReport` 与 `__init__`；8 新测试；四门禁全绿 |
| **3.5** | Market Regime Engine + V1.0 Report | completed | 可解释规则分类器 `classify_market_regime`（5 标签 Bull/Neutral/Bear/EmotionHot/EmotionCold，非黑盒、无未来函数）：前三者由指数动量+已实现波动率判定，`EmotionHot/Cold` 由可选"涨停家数"净宽度序列判定（无宽度时永不触发，保证价格单输入确定性）；`MarketRegimeEngine` 按环境动态选策略（类别适配 `REGIME_CATEGORY_FIT` + 复用 3.2 各策略 regime_breakdown 经验 OOS 收益；情绪状态无独立宽度分段回测，诚实标注按 AROS 总评分择优）；`FinalReport.from_batch` 汇总策略库+3.3 排名+3.4 组合+3.5 引擎，输出 md/json/html 的 **V1.0 最终报告**并给出"若明天做 A 股短线最值得用哪套/哪组"的明确结论；`MarketRegimeConfig` 接入 `settings.yaml` `research.market_regime`（E5）；20 新测试（分类确定性/无未来函数/情绪驱动/趋势驱动/类别适配/动态选股/全5状态/报告结构）；四门禁全绿 |
| **4.0** | Strategy Knowledge Base | completed | ORM `raw_strategies`/`strategy_registry`; `kb.py` (RawPool + StrategyRegistry, seeds 10 built-ins as `active`); `universe_provider.py` (CSI800/Watchlist/Custom, not hard-coded); `research kb` CLI (seed/list/add-raw/retire) |
| **4.1** | Research Integrity Framework | completed | `validate.py` OOS Composite (return30/sharpe25/dd25/stability20) → quality_star + vetoes + param-sensitivity + period-stability + Reliability Score + Strategy Validation Gate; persists `strategy_validations`, auto-updates `strategy_registry`; `research validate` CLI; 6 new tests; four CI gates green |
| **4.2** | Multi-Strategy Consensus Engine | completed | `consensus.py` ConsensusEngine: 信号聚合→相关性去重（Pearson OOS fold-returns，按 category+corr-cluster 并查集保留最高星）→Consensus Score(100)=H20+Q30+I20+R15+S15 与 AROS Score(100)=0.35·consensus+0.20·env+0.30·money+0.15·risk；3 张新 ORM（DailyScreening/ScreeningHit/DailyAlphaCandidate，全链路可追溯）；Provider 协议中性默认（暗盘 4.3 接入，不淘汰候选）；`alpha daily` CLI；9 新测试；四门禁全绿 |
| **4.3** | Market Context & Money Flow | completed | `data/providers/moneyflow.py`：`AkShareMoneyFlowProvider`（get_stock_flow→MoneyFlowSignal，个股主力净流入+行业相对强弱）+ `AkShareHiddenFlowProvider`（infer→HiddenFlowSignal，纯量价行为推断评分+解释，**无金额**）；纯评分函数可单测；任意网络/列漂移异常降级为中性(50)不中断整轮；`DataManager.get_fund_flow`/`get_sector_concept` 入口；`alpha daily` 接线（--no-money-flow 可退回中性）；13 新测试；四门禁全绿 |
| **4.4** | Daily Alpha Report | completed | `report/daily_alpha.py`：每日 Top-N 候选渲染为三格式并按 `reports/<date>/` 归档——`daily_alpha.xlsx`（Sheet1 候选表 + Sheet2 决策跟踪模板，系统列预填·人工列留空）、`daily_alpha.html`（自包含离线页 + AROS SVG 柱状图）、`daily_alpha.md`（AI/知识库友好）；`query_candidates(session,run_date)` 经 DailyScreening.run_date 取数，全链路可追溯；纯离线渲染无网络/无打分；`alpha daily` 自动产出报告；`openpyxl` 入 `requirements.txt`；6 新测试；四门禁全绿 |
| **4.5** | Human Feedback Loop | completed | `research/feedback.py` + 2 张新 ORM（`decision_tracking`/`personal_trades`）+ `alpha decide`/`review`/`trades-add`/`trades-list` 子命令；`post_hoc(code,signal_date,price_provider)` 纯函数算 1/3/5/10 日结果+最大浮盈浮亏+最终收益（entry=T+1，无未来函数，无数据降级 None）；`review` 自动补后验、人工填 verified_system/复盘总结；`personal_trades` 仅 schema+录入不推导；`alpha daily` 报告 Sheet2 经 `query_decisions` 回填人工列（无决定则留空，4.4 行为保留）；11 新测试；四门禁全绿 |
| **4.6** | Rating Validation & Calibration | completed | `research/calibration.py` + 新 ORM `candidate_performance`（每位候选自动后验 T+1/3/5/10/20+浮盈浮亏+目标命中日，增量填充）；`post_hoc` 扩展 T+20 与目标命中；评级改名 `A+ → S`（历史一次性迁移 `migrate`，幂等）；`rating_distribution`/`significance_test`（bootstrap 95% CI + 手写 Mann-Whitney，无 scipy）验证 S>A>B>C 单调与显著；`baseline_excess`/`strategy_contribution`/`human_vs_ai` 归因；`propose_calibration` 两阶段（≥60 交易日才可校准，否则仅观察）；`generate_validation_reports` 输出 md/html/xlsx；`alpha validate migrate|fill|report|calibrate` 子命令；14 新测试；四门禁全绿 |
| **4.7** | Entry Intelligence（入场智能）| in_progress | 主责"什么时候买"：**Entry Score 合成层**（策略组合+标的当期实况+市场判断，独立于 AROS Score）。入场选择机制（`picker` S/A/B 入、C 不入 + `entry_mode`）已落；**模拟交易验证环境** `research/papertrade.py`（双轴正交、无前视、Alpha 指标）已落，用于验证买点/卖点；退出框架 v1.0 在该环境中已单测覆盖。剩余：**真实 Entry Score 引擎**（合成层，非 follow 原始 `entry_rules`）。详见 `Phase4.6-4.8_Technical_Design.md` Part II |
| **—** | Paper Trading（验证环境，非阶段）| completed | 不是能力模块，是贯穿 4.6–4.8 的验证环境：`research/papertrade.py` 双轴正交（S1/S2/S3 × E1/E2/E3）、无前视、账户由成交簿重建、Alpha 指标（年化/Sharpe/Calmar/最大连亏）。4.7 验证买点、4.8 验证卖点 |
| **4.8** | Exit Intelligence（退出智能）| in_progress | 主责"什么时候卖"：退出框架 v1.0 四层（硬止损 fixed/atr、固定止盈、移动止盈、评分衰减 proxy、时间退出 min 优先级）已在验证环境实现并单测覆盖；剩余：**真实 Daily Exit Intelligence**（proxy→真实 AROS Score 驱动 score_decay）+ 分级 Exit Alert（High/Med/Low，原因可解释）。`ExitConfig`/`entry_mode`/`entry_score`/`score_type` 已在 4.7 入 schema，无迁移。详见 `Phase4.6-4.8_Technical_Design.md` Part III |
| **5.1** | Dashboard | pending | 把现有 Excel/HTML 升级为 Web Dashboard：每日市场状态、候选股票、策略命中、Entry 状态、Exit 状态、模拟盘一览 |
| **5.2** | AI Research Assistant | pending | 让 AI 成为"研究员"：自然语言问答（如"近三月 S 级股票表现？出现次数/胜率/最大收益/失败原因"），基于 4.5 反馈库 + 4.6 校准库 |
| **5.3** | Strategy Discovery Engine | pending | AI 主动扫描研报/论坛/公开策略/学术论文，提取策略规则 → 进入 4.1 验证 → 形成自动进化策略库 |
| **5.4** | Adaptive Weighting | pending | 动态调策略权重（如趋势策略贡献 70%，市场转震荡则降趋势、提套利/低波）|
| **5.5** | Risk Management | pending | 组合层：仓位 / 行业集中 / 风险预算 / 相关性（Alpha Management Engine 组合层成熟）|

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

已完成（含真实 A 股数据接入）：

- **3.2 Batch Strategy Experiment + 真实数据桥接（✅ 2026-07-19）** — `BatchRunner`
  遍历 策略 × 冻结实验配置，全走 walk-forward，落库；含 point-in-time 成分获取（D6）。
  真实数据桥接已打通：`research batch` 经 `DataManager` 取数，真实日线流入
  `EventBacktest`，OOS 指标非零。关键修复 `run_strategy` 把 `get_daily` 的 `RangeIndex`
  规整为 `DatetimeIndex`（否则事件引擎信号全清零、0 交易），并兼容 akshare 中英文列名漂移。
  情绪/涨停类策略因 qfq 复权价下涨停判定失真，OOS 仍接近 0%（spec 已标注
  `daily_approx`/`needs_intraday`），属已知数据保真度限制，非桥接缺陷。
- **3.3 Strategy Evaluation & Ranking（✅）** — `Scorecard` 完整评分 + 排名，接入 Report。
- **3.4 Strategy Combination（✅）** — 分市场环境配权。
- **3.5 Market Regime Engine（✅）** — 可解释规则分类（牛/震荡/熊/情绪冷热），产出 V1.0 报告。

后续可推进：
- **Phase 4 — 实盘/调度**：把 3.2 真实数据 + 3.3–3.5 选股/组合/市场状态接入定时调度，
  产出可执行的每日/每周研究简报（无券商下单接口，仍止步于「信号可复现产出」）。

## Phase 4 — AROS Trading Intelligence Core（4.0–4.8，交易智能核心）

> **战略重定位（2026-07-20）**：Phase 4 从"研究完整性 / 知识库"重新定义为 **AROS Trading Intelligence Core**——覆盖真实交易全闭环（发现→买入→持有→卖出→复盘）。四大引擎（Discovery/Entry/Management/Exit）对齐交易时间轴；模拟交易降级为贯穿 4.6–4.8 的**验证环境**（不占 Phase 编号）。Phase 5 另作智能化平台阶段（见下）。

Phase 4 设计 `Phase4_Technical_Design_v2.1.md` §9「建议首切」：先落 **4.0 知识库 + 4.1 研究诚信框架**，
作为 4.2–4.5 的依赖根。4.0 + 4.1 + 4.2 + 4.3 + 4.4 均已提交 `main`，四门禁全绿。

- **4.0 Strategy Knowledge Base（✅）** — `raw_strategies`/`strategy_registry` ORM + `kb.py`
  （RawPool + StrategyRegistry，从 `strategy_library` 幂等 seed 10 内置策略为 `active`）+ `universe_provider.py`
  （CSI800/Watchlist/Custom 三种 Provider，非硬编码）+ `research kb` CLI（seed/list/add-raw/retire）；11 新测试。
- **4.1 Research Integrity Framework（✅）** — `validate.py`：OOS Composite（收益30/夏普25/回撤25/稳健20）
  → quality_star(1–5, 含否决) + 参数敏感性（±1/±0.1 扰动）+ 周期稳定性 + Reliability Score
  （OOS40/参数20/周期20/交易20）+ Strategy Validation Gate（无未来函数/OOS收益>0/OOS夏普>0.5/回撤<40%/交易≥100/参数稳定）；
  落库 `strategy_validations` 并自动更新 `strategy_registry`；`research validate` CLI（run/all）；6 新测试。
- **4.2 Multi-Strategy Consensus Engine（✅）** — `consensus.py` `ConsensusEngine`：自 `strategy_registry`
  (active) 取已验证策略 → T 日信号聚合（无未来函数，T+1 入场）→ Pearson OOS fold-returns 相关性去重
  （按 `category` + 相关簇并查集，每簇保留最高 `quality_star`，非幸存仍计入命中数 H）→
  Consensus Score(0–100) = H20 + Q30 + I20 + R15 + S15 与 AROS Score(0–100) =
  0.35·consensus + 0.20·market_sector_env + 0.30·money_flow + 0.15·risk_filter；
  评级 A+≥85 / A≥70 / B≥55 / C<55；3 张新 ORM（DailyScreening → ScreeningHit → DailyAlphaCandidate，全链路可追溯）；
  资金流/暗盘走 Provider 协议并给中性默认（暗盘 4.3 接入，按宪法「暗盘永不淘汰候选」取中性分不淘汰）；
  `research alpha daily` CLI（--universe/--date/--limit/--regime，自动 seed 内置策略）；9 新测试；四门禁全绿。
- **4.3 Market Context & Money Flow（✅）** — `data/providers/moneyflow.py`：`AkShareMoneyFlowProvider`
  （`get_stock_flow(code)→MoneyFlowSignal`，个股主力净流入百分位 `public_money_score` + 相对所属行业强弱
  `sector_score`，经 akshare `stock_individual_fund_flow`/`stock_board_industry_rank_em`/`stock_individual_info_em`）
  + `AkShareHiddenFlowProvider`（`infer(code)→HiddenFlowSignal`，**纯量价行为推断**评分+解释，绝无金额，守住 v2 红线）；
  评分数学抽为纯函数（`public_money_score`/`sector_score`/`hidden_flow_infer`）可单测；所有外部抓取包 try/except，
  任一异常/限流/列漂移降级为中性(50)不中断整轮（保留 4.2 离线可测性与「暗盘永不淘汰候选」）；
  `DataManager.get_fund_flow`/`get_sector_concept` 作为接入入口（设计 §5 4.3）；`alpha daily` 自动接线真实 Provider
  （`--no-money-flow` 退回 4.2 中性行为）；13 新测试；四门禁全绿。
- **4.4 Daily Alpha Report（✅）** — `report/daily_alpha.py`：`DailyAlphaReport.generate(candidates, run_date, out_dir)`
  把每日 Top-N 候选渲染为三格式、按 `reports/<date>/` 归档——`daily_alpha.xlsx`（Sheet1 候选表按设计 §7/v2 Sheet1；
  Sheet2 决策跟踪模板系统列预填、人工列留空，待 4.5 人工闭环）、`daily_alpha.html`（自包含离线页 + AROS SVG 柱状图 +
  候选明细）、`daily_alpha.md`（AI/知识库友好）。`query_candidates(session, run_date)` 经 `DailyScreening.run_date`
  取数，全链路可追溯；渲染**纯离线无网络/无打分**。设计所谓「复用 report.py」实为 `report/engine.py` 的 ReportEngine，
  二者数据结构不同，故新建独立模块并沿用其 HTML/Markdown 风格。`alpha daily` 在 screening 后自动产出报告；
  `openpyxl` 加入 `requirements.txt`；6 新测试；四门禁全绿。
- **4.5 Human Feedback Loop（✅）** — `research/feedback.py` + 两张新 ORM（`decision_tracking`/`personal_trades`）：
  `post_hoc(code, signal_date, price_provider)` 纯函数算 1/3/5/10 日结果 + 最大浮盈浮亏 + 最终收益
  （entry=T+1 交易日，无未来函数；无数据降级为 `None`，绝不编造数字）；`record_decision` 落人工判断（关注/买入/放弃/忽略）
  并冗余存 `signal_date` 锚定后验；`review` 经 `DataManager.get_daily` 自动补后验、人工填 `verified_system`/复盘总结；
  `personal_trades` 仅 schema + 录入接口，系统不自动推导（对应「上线后自选标的自行记录充实数据库」）。CLI：`alpha decide`
  /`alpha review`/`alpha trades-add`/`alpha trades-list`。`alpha daily` 报告经 `query_decisions` 回填 Sheet2 人工列
  （无决定则留空，4.4 行为不变）。11 新测试；四门禁全绿。

## Phase 5 — AROS Intelligent Platform（智能化平台阶段）

> Phase 4 已完成"从发现到退出的研究闭环"。Phase 5 不再开发交易逻辑，而是把核心能力**产品化 / 自动化 / 智能增强**，把 AROS 真正做成"AI 辅助投资决策系统"。详见 `Phase5_Intelligent_Platform.md`。

- **5.1 Dashboard** — 现有 Excel/HTML 升级为 Web Dashboard：每日市场状态、候选股票、策略命中、Entry 状态、Exit 状态、模拟盘一览。
- **5.2 AI Research Assistant** — 让 AI 成为"研究员"：自然语言问答（如"近三月 S 级股票表现？出现次数 / 胜率 / 最大收益 / 失败原因"），基于 4.5 反馈库 + 4.6 校准库。
- **5.3 Strategy Discovery Engine** — AI 主动扫描研报 / 论坛 / 公开策略 / 学术论文，提取策略规则 → 进入 4.1 验证 → 形成自动进化策略库。
- **5.4 Adaptive Weighting** — 动态调策略权重（如趋势策略贡献 70%，市场转震荡则降趋势、提套利 / 低波）。
- **5.5 Risk Management** — 组合层：仓位 / 行业集中 / 风险预算 / 相关性（Alpha Management Engine 组合层成熟）。

**三大核心评分贯穿 Phase 5 每日输出**：Alpha Score（值不值得研究）/ Entry Score（现在是否适合买）/ Exit Risk（是否应该离场）。
