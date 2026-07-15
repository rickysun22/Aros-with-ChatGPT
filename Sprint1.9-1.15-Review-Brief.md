# AROS Sprint 1.9–1.15 评审简报（Review Brief）

> 用途：供外部评审（如 ChatGPT）逐项核对每个 Sprint 的实现是否达成设计意图、门禁是否达标、是否存在未来函数泄漏。
> 配套设计案：`Sprint1.9-Watchlist-Design.md` … `Sprint1.15-Scheduler-Design.md`（同目录）。
> 仓库：`github.com/rickysun22/Aros-with-ChatGPT`（本地克隆：`/c/Users/ricky.sun/AppData/Local/Temp/aros-clone`）。

## 0. 统一评审基线

- **流水线全景**：`data → indicators → factors → strategies → backtest → ranking → report → watchlist → cache → universe → HTML → scheduler → portfolio`
- **四门门禁（每个 Sprint 都必须全绿）**：
  - `ruff check .`
  - `black --check .`
  - `mypy src tests main.py`
  - `pytest -q`
- **无未来函数铁律（no look-ahead）**：所有取数/回测/排名窗口上界必须收敛在各自 `as_of`，不得引用 `as_of` 之后的任何数据。
- **复用优先**：新模块一律复用既有 `RankingEngine` / `BacktestEngine` / `core.database` / `DataManager`，不在新层重复造轮子。
- **可测试性范式**：引擎 `__init__` 普遍支持注入桩函数（如 `backtest_fn` / `rank_fn` / `equity_fn`），单测不依赖真实数据与网络。

---

## Sprint 1.9 — 自选股追踪器（Watchlist Tracker）`commit 3b2a89f`
- **目标**：流水线每次都无状态重算，无历史记忆。本 Sprint 在末端加**持久化追踪层**，落库每日关注池的排名/打分，并派生「日环比变动」。
- **新增模块** `src/watchlist/`：
  - `models.py`：`WatchlistItem`（软删，`removed_at` 可空）、`RankingPoint`（每日快照，列 `as_of/code/rank/composite_score/scores_json/created_at`，唯一约束 `(as_of, code)`），继承 `core.database.Base`。
  - `engine.py`：`WatchlistEngine` / `WatchlistDigest` / `WatchlistMember` / `_classify`。
- **复用**：用 `RankingEngine.rank()` 的 `scored`（完整截面，含 `composite_score` 无 `rank`），自行 `composite_score.rank(method="first")` 算**全量 rank**（含跌出 Top-N 的成员也跟踪）。
- **六态环比**（`deltas`）：`new` / `dropped` / `up` / `down` / `steady` / `no_data`。无截面数据的 code 不落点 → 次日判 `dropped`；`no_data` 留给"有记录但 composite 为 NaN 不可排名"。
- **无未来函数**：snapshot 取数上界 = ranking 同一 `as_of`；deltas 纯读已落库历史。
- **CLI**：`watchlist add/remove/list/snapshot/history/digest`；配置 `WatchlistConfig.alert_rank_jump=5`。
- **评审核对点**：① 全量 rank 是否覆盖跌出 Top-N 的成员；② 无数据→`dropped` 语义；③ 软删 `removed_at`；④ sqlite 临时文件 `dispose()` 后再删（避免 Win32 锁）。
- 测试 12 项；四门门禁绿；pytest 累计 ~141。

## Sprint 1.10 — 报告接入回测指标（Report Backtest Enrichment）`commit 3836f9b`
- **目标**：把单标的 `BacktestEngine`（1.6）接到日报（1.8），给每个 Top-N 候选补**历史回测表现**作为实证注脚。
- **关键决策**：做 **per-candidate** 回测（每个候选跑一段），**不是组合回测**（组合需跨标的层，单独排期 = Sprint 1.16）。
- **复用不重写**：`ReportEngine` 惰性 `_get_bt_engine()`，对排序后候选调 `run_code` → 取 `total_return/max_drawdown/sharpe/benchmark_return` 四项。
- **无未来函数**：回测窗口 `[start_date, as_of]`，复用报告已有 `snap_end == as_of`。
- **只回测 Top-N**（成本有界）；默认关闭（`ReportConfig.include_backtest=False`）；可注入 `backtest_fn` 桩。
- **改动文件**：`src/report/engine.py`（ReportRow 加 4 个 `bt_*`；DailyReport 加 `backtest_included`；markdown/json 渲染回测列）、`src/core/config.py`、`config/settings.yaml`、`main.py`（`report ... --backtest`）。
- **评审核对点**：① 回测窗口上界是否严格 == `as_of`（无未来函数断言）；② 默认关闭不调用；③ 空指标返回 `None` 不报错。
- 测试 +7 项；pytest 累计 ~149。

## Sprint 1.11 — 自选股回测落库（Watchlist Backtest Persistence）`commit 117afd8`
- **目标**：把 1.10 的回测接到**自选股追踪器**并**持久化**，支持**收益Δ环比**。
- **新增 ORM** `BacktestPoint`（`src/watchlist/models.py`）：`as_of/code/total_return/max_drawdown/sharpe/benchmark_return/created_at`，`UniqueConstraint(as_of, code)`，字段可空（无数据不落点 → `deltas` 判 `dropped`）。
- `WatchlistMember.backtest/prev_backtest`（`BacktestSummary`）；`WatchlistDigest.backtest_included`；markdown 追加「## 回测表现」小节，收益Δ = 当前 `total_return` − 前次。
- 默认关闭（`WatchlistConfig.include_backtest`）；CLI `watchlist snapshot --backtest`；与 1.10 一致。
- **无未来函数**同 1.10；可注入 `backtest_fn` 桩。
- **评审核对点**：① 落库与 1.9 `RankingPoint` 同模式（upsert + 唯一约束 + 无数据不落点）；② 含 `test_snapshot_backtest_no_lookahead`。
- 测试 +4 项。

## Sprint 1.12 — 回测结果缓存落库（Backtest Cache）`commit 0125e54`
- **目标**：单标的回测最耗时，做结果缓存——相同窗口+参数组合命中即跳过仿真循环。是 1.10/1.11 的性能地基。
- **新增** `src/backtest/cache.py`：`BacktestCache` ORM（`code/params_hash/start/end/signal_col/metrics_json/equity_json/created_at`，唯一约束 `(code, params_hash)`）。
- **缓存键 `params_hash`** 折叠一切改变仿真结果的输入：`signal` 列名 + `cost` 费率 + `initial_cash` + `max_position` + `benchmark` 开关 + `start/end`；换 `as_of`（换 `end`）即自然 miss。
- `run_code_cached(...)`：命中则把 `equity_json` 重新挂回价量帧（保证 `df['equity']` 照常工作），返回缓存 metrics；未命中实算并存储。
- 接入 `BacktestEngine.run_code(use_cache=True)`；**全部 best-effort**——任何 DB 异常捕获降级实时计算，缓存永不阻断回测。
- 配置 `BacktestConfig.cache_enabled`（默认 `True`）。
- **评审核对点**：① 命中后是否真的跳过仿真（重算计数）；② 哈希确定性（同输入稳定、改窗口变）；③ DB 异常是否降级而非抛错。
- 测试：命中免重算 / 不同 code 各落一行 / 哈希确定性。

## Sprint 1.13 — Universe 股票池管理（Stock-pool）`commit b84431a`
- **目标**：提供「命名股票池」作为下游（尤其 `report`）的统一候选来源，免去每次手敲 codes。
- **新增** `src/universe/`：`UniversePool` ORM（`name` PK / `description` / `codes_json` / `created_at` / `updated_at`）+ `UniverseEngine`（session 化，复用共享库）。
- API：`add_codes`（去重+字典序排序）/ `remove_codes` / `get_codes` / `exists` / `list_pools` / `delete`。
- CLI `universe add|remove|list|show|delete`；`report --universe POOL` 解析候选（与位置参数互斥，给 `--universe` 即以池为准）。
- **边界**：Watchlist 自带成员表不依赖 universe；universe 只解决"codes 从哪来"，不改排序/回测语义。
- **评审核对点**：① 成员去重+排序；② `--universe` 与位置参数互斥；③ 不影响 ranking/backtest 语义。
- 测试 6 项，全隔离 in-memory sqlite。

## Sprint 1.14 — 报告 HTML 可视化（Report HTML）`commit e16b520`
- **目标**：给日报加自包含、可离线打开的 HTML 渲染（`DailyReport.to_html()`），内联 CSS + 内联 SVG 横向柱状图，保留 markdown 全列（含 1.10 回测指标）。
- **`DailyReport.to_html(include_detail=True)`**：内联 `<style>`（浅色主题、表格 hover、卡片网格）；SVG 按 `composite_score` 归一化画条；表格与 markdown 同列；明细卡片网格；文本经 HTML 转义（`& < >`）防注入。
- 配置 `ReportConfig.format: Literal["markdown","json","html"]`；CLI `report ... --format html`（可 `--out report.html` 落盘）。
- **零依赖离线可用**；渲染层不引入新数据/窗口，无未来函数。
- **评审核对点**：① 含 `<!DOCTYPE html>` + `<svg>` + 柱状；② 开启回测含「回测收益」「Sharpe」列；③ 文本转义防注入。
- 测试：渲染图表与表格 / 回测列。

## Sprint 1.15 — 定时生成 + 推送（Scheduler + Notifier）`commit 2a15a12`
- **目标**：日报/自选股可「定时自动跑 + 推送」。**不要求任何外部凭据**——webhook 无 URL 时 no-op，调度器照样跑（默认 console）。
- **`Notifier` 抽象 + 三实现**（`src/scheduler/notify.py`）：`ConsoleNotifier` / `FileNotifier` / `WebhookNotifier`（HTTP POST JSON，best-effort 吞异常，URL 为 `None` 直接 no-op）；`build_notifier(SchedulerConfig)`。
- **`Scheduler`**（`src/scheduler/engine.py`）：`run_ntimes(task, interval, n)`（测试用）、`run_loop(task, interval, stop_event)`（threading.Event 可中断）；`task` 零参 callable 返回正文，tick 异常被捕获不挂循环。
- 配置 `SchedulerConfig`（`notifier_type`/`webhook_url`/`file_path`）挂在 `AppConfig.scheduler`；settings.yaml 暴露。
- CLI `schedule`：`--report [CODES...] [--universe POOL] [--backtest]` 或 `--watchlist [--backtest]`；`--every N`（分钟）/ `--once`（验证用）。
- **无未来函数**：仅按间隔重复调用已有生成逻辑，窗口仍收敛 `as_of`。
- **评审核对点**：① webhook 无 URL 不报错（no-op）；② `run_ntimes` 次数正确；③ 无凭据可全跑。
- 测试 7 项全离线。

---

## 统一评审清单（逐项勾选）
- [ ] 四门门禁（ruff/black/mypy/pytest）在 1.9–1.15 全部绿
- [ ] 无未来函数：1.9/1.10/1.11 回测窗口上界严格 == as_of；1.12 缓存只读已算结果；1.14/1.15 渲染/调度不引入新窗口
- [ ] 复用：新层均复用 `RankingEngine`/`BacktestEngine`/`core.database`，无重复数学
- [ ] 默认关闭：1.10/1.11 回测、1.12 缓存均默认安全、best-effort 降级
- [ ] 边界：1.13 universe 只解决候选来源、不改排序/回测语义
- [ ] 可测试：桩注入 + 隔离 sqlite/in-memory，无真实数据/网络依赖
- [ ] 安全：PAT 曾在会话中明文暴露，建议 GitHub Settings 轮换吊销
