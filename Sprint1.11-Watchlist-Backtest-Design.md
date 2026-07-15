# Sprint 1.11 — 自选股追踪器接入回测并落库

> 收口 Sprint 1.10 的故事：1.10 把 `BacktestEngine` 接到了**日报(报告)**；本 Sprint 把它接到**自选股追踪器**，并且**持久化**回测指标，支持**环比**。

## 目标

- 给 `watchlist` 的每个活跃成员，在 `snapshot` 时附上历史回测表现，存入一张新的 `backtest_points` 表。
- 在 `digest`（日环比）里展示每只标的的回测指标，并给出相对前一次的**收益Δ**环比。
- 复用 1.9 `RankingPoint` 的「upsert + 唯一约束(as_of, code) + 无数据不落点」模式，保持行为一致。

## 关键设计决策

1. **新增 ORM 表 `BacktestPoint`**（`src/watchlist/models.py`）
   - 列：`as_of` / `code` / `total_return` / `max_drawdown` / `sharpe` / `benchmark_return` / `created_at`
   - `UniqueConstraint("as_of", "code")` —— 与 `RankingPoint` 同款，保证每日每标的唯一快照。
   - 字段均为可空，与 `RankingPoint` 对齐（无数据则**不落点**，由 `deltas` 判为 `dropped`）。

2. **`WatchlistMember` 增加可选字段** `backtest` / `prev_backtest`（`BacktestSummary`），`deltas` 读取时填充。

3. **`WatchlistDigest` 增加 `backtest_included` 标志**，markdown 渲染时追加「## 回测表现」小节（代码 | 收益% | 最大回撤% | Sharpe | 基准% | 收益Δvs前次），收益Δ = 当前 total_return − 前次 total_return。

4. **默认关闭，配置化**：`WatchlistConfig.include_backtest` 默认 `False`。CLI `watchlist snapshot --backtest` 开启；与 1.10 报告的 `report ... --backtest` 一致。

5. **无未来函数（与 1.10 同约束）**：回测窗口 = `[start_date, as_of_date]`，其中 `as_of_date` 是排名截面的上界，绝不超过 `as_of`。单测 `test_snapshot_backtest_no_lookahead` 专门守住这条。

6. **可测试**：`WatchlistEngine.__init__` 支持注入 `backtest_fn` 桩，单测无需真实 `BacktestEngine` / 数据，覆盖：默认关闭不调用、开启后落库、无未来函数、digest 环比。

## 改动文件

- `src/watchlist/models.py` — 新增 `BacktestPoint`
- `src/watchlist/engine.py` — `BacktestSummary` / `WatchlistMember` 字段 / `WatchlistDigest.backtest_included` / markdown 回测小节 / 懒加载 `BacktestEngine` / `_backtest_snapshot` / `_upsert_backtest_point` / `_backtest_point_map` / `snapshot` 落库 / `deltas` 环比
- `src/watchlist/__init__.py` — 导出 `BacktestSummary` / `BacktestPoint`
- `src/core/config.py` — `WatchlistConfig.include_backtest`
- `main.py` — `watchlist` 命令加 `--backtest`，并把 `backtest/indicators/factors/strategies` 配置传入引擎
- `tests/test_watchlist.py` — 4 项新增单测

## 四门门禁

`ruff` ✅ / `black` ✅ / `mypy` ✅ / `pytest` ✅
