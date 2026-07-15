# AROS Phase 2 修订案（对齐 Sprint 1.16）

> 目的：把 GPT 的 `AROS_Phase2_Quant_Research_Engine_Plan.md`（位于用户 Documents，基于 1.1–1.8 旧基线）与 AROS **实际代码状态（1.1–1.16）** 对齐，消除信息不一致，明确复用边界，避免重复造轮子。
> 本文件是仓库内的**唯一对齐源**；GPT 原案仅作输入参考，落地以本修订案为准。

## 0. 为什么要修订

GPT 原案的 "Current Status" 表只列到 **1.1–1.8（PASS）**，完全不知道 **1.9–1.16 已经落地并推到 `origin/main`**。若照原案直接写代码，会出现：

1. `research/metrics.py` 与已有 `src/backtest/metrics.py`（1.6）大量重叠（total_return / max_drawdown / sharpe / sortino / win_rate / num_trades …）。
2. "Load Universe" 重做，而 `UniverseEngine`（1.13）已存在。
3. 没有实验落库设计，而 1.9–1.16 全部走 `core.database` ORM 持久化。
4. 指数基准（CSI300/1000/上证综指）需要 `DataManager` 支持指数行情，原案未列数据前置。
5. 首个要吃真实 11 年 A 股历史的环节，原案未强调真实数据联调（Phase 1 测试全程 Fake 桩）。

## 1. 当前已完成内容（修正后的 Current Status，对齐到 1.16）

完整流水线（实际）：

```text
data → indicators → factors → strategies → backtest → ranking → report
     → watchlist → backtest-cache → universe → html-report → scheduler → portfolio-backtest
```

| Sprint | 模块 | 一句话内容 | 状态 |
| --- | --- | --- | --- |
| 1.1 | Foundation | 脚手架 + Pydantic/YAML 配置 + Loguru + SQLAlchemy2 库 + 异常体系 + Typer CLI + 测试 | ✅ |
| 1.2 | Data Layer | `Stock`/`DailyBar`/`SyncState` ORM；`AkShareProvider` + `AStockDataProvider` 兜底；`DataManager` 单入口 | ✅ |
| 1.3 | Indicator Engine | 7 指标（MA/EMA/RSI/MACD/KDJ/BOLL/VOL_MA），配置驱动，无未来函数 | ✅ |
| 1.4 | Factor Engine | 8 因子（ma_distance/ma_cross/rsi_signal/macd_cross/kdj_cross/vol_ratio/boll_position/momentum），无未来函数 | ✅ |
| 1.5 | Strategy Engine | `SignalType`(SHORT 保留为 FLAT) + `weighted`/`rule` 策略；`StrategyEngine`；`Portfolio`（无未来函数） | ✅ |
| 1.6 | Backtest Engine | `CostModel`（A 股费用）；`metrics.py`（total_return/cagr/max_drawdown/sharpe/sortino/win_rate/num_trades/turnover/benchmark_return + `compute_metrics` 分发）；`BacktestEngine`（成本敏感净值 + 成交明细，单标的/分组） | ✅ |
| 1.7 | Ranking Engine | `RankingEngine` 截面复合分（权重归一，可负）；Top-N | ✅ |
| 1.8 | Daily Report | `ReportEngine`/`DailyReport`/`ReportRow`；最新价快照 + 日涨跌 + 新鲜度；markdown/json | ✅ |
| 1.9 | Watchlist Tracker | `WatchlistItem`（软删）+ `RankingPoint`（每日快照）；`WatchlistEngine`；六态环比（new/dropped/up/down/steady/no_data） | ✅ |
| 1.10 | Report Backtest | 报告给每个 Top-N 候选补 per-candidate 回测四项（收益/回撤/Sharpe/基准）；`--backtest`；可注入 `backtest_fn` | ✅ |
| 1.11 | Watchlist Backtest | `BacktestPoint` ORM；自选股回测落库 + 收益Δ环比；`--backtest` | ✅ |
| 1.12 | Backtest Cache | `BacktestCache` ORM + `params_hash`；`run_code_cached`；best-effort 降级；`cache_enabled` | ✅ |
| 1.13 | Universe | `UniversePool` ORM + `UniverseEngine`（增/删/查/列举/删，去重排序）；`universe` 命令；`report --universe` | ✅ |
| 1.14 | Report HTML | `DailyReport.to_html()` 自包含（内联 CSS + SVG 柱状图，离线）；`--format html` | ✅ |
| 1.15 | Scheduler | `Notifier`（Console/File/Webhook 无 URL 时 no-op）+ `Scheduler`（`run_ntimes`/`run_loop`）；`schedule` 命令（`--once`/`--every`） | ✅ |
| 1.16 | Portfolio Backtest | `PortfolioBacktest`（Top-N 再平衡，单标的净值等权组合；基准=全候选集买入持有）；`portfolio` 命令 | ✅ |

> 统一状态：1.1–1.16 全部在 `origin/main`（tip `313bc51` 为评审简报，其上 `ab5e0de` 为 1.16）；四门门禁（ruff/black/mypy/pytest）本地全绿；**ChatGPT 逐 sprint 评审收口待走**（流程硬门禁）。

## 2. GPT 原案中应当保留的部分

- 研究引擎定位：Phase 1 是"实验室"，Phase 2 应回答"哪个策略最好"。
- `experiment_id` + 可复现 `ExperimentConfig` + 标准化指标 + 基准对比 + walk-forward 样本外验证。
- 研究原则：No Future Data / Benchmark Required / Sample Size Matters / OOS Required / Explainability。
- Non-goals 克制：不碰 ML/AI/实盘/intraday/tick，2.0 不实现 15 个生产策略。
- Acceptance：四门 CI + ChatGPT 评审。

## 3. 复用清单（2.0 必须建在现有引擎之上，不得平行重写）

| GPT 2.0 模块 | 复用现有（不重写） | 真正需要新增 |
| --- | --- | --- |
| `experiment.py` | `core.database.Base` / `get_engine` / `get_sessionmaker`（落库模式同 `BacktestPoint`/`RankingPoint`） | `ExperimentConfig` / `ExperimentResult` 模型 + ORM |
| `metrics.py` | **扩展** `src/backtest/metrics.py` 的 `compute_metrics` 分发器 | `profit_factor` / `calmar` / `annual_return` / `avg_gain` / `avg_loss` / `avg_holding_days` / `max_consecutive_losses`（纯函数，挂进已有分发） |
| `benchmark.py` | `src/backtest/metrics.py` 的 `benchmark_return` 思路；`PortfolioBacktest`（1.16）的买入持有基准思路 | **指数行情数据**（见 §4.1）+ CSI300/CSI1000/SSE/EqualWeight 基准 |
| `runner.py` | `BacktestEngine`（1.6）+ `UniverseEngine`（1.13）+ `RankingEngine`（1.7）+ 上述 metrics | 仅薄编排，不含任何计算逻辑 |
| `walk_forward.py` | `BacktestEngine` 窗口切分 + 既有"无未来函数"截断测试 | 训练/测试窗口拆分 + 样本内/外对比 + "仅样本内有效→标记高风险" |
| `reports.py` | `DailyReport.to_markdown` / `to_json` 渲染模式 | 实验报告（含 Pass/Fail 研究结论） |

## 4. 必须新增的前置（原案遗漏，落地前先解决）

### 4.1 指数行情数据（benchmark 的数据前置）
- `DataManager` 需支持指数标的（如 `000300.SH` / `000905.SH` / `000001.SH`），新增 provider 方法取指数日线。
- 缺失基准数据应**清晰报错**（原案已要求，但未列数据来源）。
- 建议作为 Sprint 2.0 的数据前置（可单列 `2.0a` 或并入 2.0 第一步）。

### 4.2 实验落库
- `ExperimentResult` 应落 `core.database`（仿 `BacktestPoint`/`RankingPoint` 的 ORM + 唯一约束），保证 `experiment_id` 稳定可复现。

### 4.3 真实数据联调
- 2.0 是首个要吃真实 2015–2026 共 11 年 A 股历史的环节；Phase 1 测试全程 `FakeSE`/`FakeDM` 桩。需真实 `akshare`/`astockdata` 跑通一份端到端样例。

## 5. 与 1.9–1.16 的衔接（避免 research 成孤岛）

- 实验候选池直接复用 `UniverseEngine`（`report --universe` 同源）。
- 实验结果可落 `BacktestPoint` 同类表；`watchlist` 可消费实验排名做跟踪。
- `scheduler` 可排 `research` 实验的定时运行。
- 组合基准可复用 `PortfolioBacktest`（1.16）的买入持有思路，不另起炉灶。

## 6. 修订后的 Sprint 2.0 验收（对齐）

- [ ] `src/research/` 存在（experiment/metrics/benchmark/runner/walk_forward/reports）
- [ ] 实验模型 + **落库**（ORM，仿既有模式）
- [ ] 指标**扩展**进 `src/backtest/metrics.py`（不新建平行 metrics 模块）
- [ ] 基准含指数（数据前置 §4.1 已就位）
- [ ] walk-forward（训练/测试不泄漏 + 样本外对比）
- [ ] runner **复用**现有引擎（无重复计算）
- [ ] 报告 markdown/json + Pass/Fail 结论
- [ ] 单元测试（含无未来函数断言、空交易优雅处理）
- [ ] 四门 CI 绿
- [ ] ChatGPT 评审 PASS
- [ ] **明确不重复实现已有指标 / Universe / 基准**

## 7. 建议开发顺序（修订）

1. 数据前置：`DataManager` 指数行情（§4.1）—— 可单列或并入 2.0 首步
2. `src/backtest/metrics.py` 扩展新指标（§3 表格）
3. `experiment.py`（模型 + ORM 落库）
4. `benchmark.py`（接指数数据）
5. `runner.py`（薄编排）
6. `walk_forward.py`
7. `reports.py`
8. tests
9. 文档对齐：`ROADMAP.md` / `CHANGELOG.md` 补到 1.16 + 本修订案入仓库

## 8. 一句话结论

方向认可、原则一致；但**不能直接照原案写代码**。以本修订案为唯一对齐源，复用 1.6 / 1.13 / 1.16 / 核心库，补齐指数数据与实验落库两个前置，再开工 2.0。这样 GPT 原案与仓库实际状态两侧信息一致。
