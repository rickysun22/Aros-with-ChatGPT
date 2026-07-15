# Sprint 1.9 - 自选股追踪器（Watchlist Tracker）

> 状态：实现中（本地，写完直接推送）
> 上游：data -> indicators -> factors -> strategies -> backtest -> ranking -> report -> **watchlist**

## 1. 目标

前序 Sprint 把流水线跑通了：indicators -> factors -> strategies -> backtest -> ranking(截面复合分 Top-N) -> report(每日研究日报)。
但**排名与日报每次都是无状态重算**，没有任何历史记忆——研究员无法回答"这只票上周排名第几、今天跃升了还是掉队了、新进了哪些候选"。

本 Sprint 在流水线末端加一层**持久化追踪**：把每日关注池的排名/打分落库，并派生"日环比变动"（新进 / 掉出 / 上升 / 下降 / 持平 / 无数据），形成可持续跟踪的**自选股追踪日报**。

## 2. 复用关系（不重复造轮子）

- **RankingEngine**（Sprint 1.7）：`rank()` 返回 `(ranking, scored)`，`scored` 是**完整截面**（含 `composite_score` 但无 `rank` 列）。Watchlist 需要对**所有关注成员**算全量排名（含跌出 Top-N 的），因此本引擎在 `scored` 上自行 `composite_score.rank(ascending=False, method="first")` 得到全量 rank，而非仅用 `ranking`(Top-N)。
- **core.database**（Sprint 1.1）：`Base` / `get_engine` / `get_sessionmaker`，已有 `Stock/DailyBar/SyncState`。本 Sprint 新增 `WatchlistItem` / `RankingPoint` 两张表，复用同一引擎与 Session 管理。
- **DataManager**（Sprint 1.2）：快照取数入口，与 ranking 共用，无新增数据逻辑。

## 3. 数据结构（ORM，继承 core.database.Base）

- `WatchlistItem`：`code`(PK), `added_at`, `removed_at`(可空, 软删), `note`。活跃 = removed_at 为 None。
- `RankingPoint`：`id`(PK), `as_of`(date), `code`, `rank`(int 可空), `composite_score`(float 可空), `scores_json`(JSON 可空), `created_at`；唯一约束 `(as_of, code)`。

## 4. 核心 API（WatchlistEngine）

- `add(code, note=None)` / `remove(code)` / `list_active() -> list[str]` / `is_member(code)`：成员管理（upsert + 软删）。
- `snapshot(as_of=None, codes=None, data_manager=None, start_date, end_date)`：
  1. codes = codes or 活跃成员；
  2. 用 RankingEngine 对 codes 跑截面，得到 `scored`（完整截面，含 composite_score）；
  3. 在 scored 上算**全量 rank**（含跌出 Top-N 的成员）；
  4. as_of = config.as_of 或 scored 最大日期；
  5. 对 codes 中每个 code upsert 一条 RankingPoint（含跌出 Top-N 的成员）；无数据（无截面）的 code 不落点，环比时判为「掉出 dropped」；
  6. 返回 `WatchlistDigest`（基于本次快照 + 上一次快照的环比）。
- `history(code, limit=20) -> list[RankingPoint]`：该 code 的历史快照（as_of 倒序）。
- `deltas(as_of=None) -> WatchlistDigest`：**纯读库**，对比最近两个 as_of 的环比，不触网、无未来函数。

## 5. 环比状态机（deltas）

对每个活跃成员，比较当前/上一次快照：

- 当前无记录 → `dropped`（掉出）
- 上一次无记录 → `new`（新进）
- 当前 rank 为 None → `no_data`
- 否则 `rank_change = prev_rank - cur_rank`：>0 `up` / <0 `down` / ==0 `steady`
- `|rank_change| >= alert_rank_jump` 在 markdown 中标记"显著变动"

`WatchlistDigest` 汇总：n_new / n_dropped / n_up / n_down / n_steady / n_no_data，并提供 `to_markdown()` / `to_json()`。

## 6. 无未来函数（项目铁律）

- snapshot 的取数上界 = ranking 同一 `as_of`（RankingEngine 已保证 scored 不越截面）；
- deltas 只读已落库的历史快照，不触网、不参考未来；
- 排名相对性仅限关注池内部（自相对排名），与外部 universe 无关，符合"关注池内跟踪"语义。

## 7. 配置（config/settings.yaml -> WatchlistConfig）

    watchlist:
      alert_rank_jump: 5     # |rank_change| 达到该值标记"显著变动"

## 8. 输出与 CLI

- `WatchlistDigest.to_markdown()` / `to_json()`。
- CLI：`watchlist <action> [CODE] [--note] [--limit] [--as-of] [--start] [--end] [--format]`
  - `add CODE [--note]` / `remove CODE` / `list` / `snapshot [--as-of]` / `history CODE [--limit]` / `digest [--as-of] [--format]`

## 9. 验收（四门门禁）

- ruff / black / mypy / pytest 全绿。
- 覆盖：add/remove/list/is_member、snapshot 记录全量排名（含跌出 Top-N）、deltas 六态、history、markdown/json、真实配置接线、CLI smoke、snapshot 不越 as_of 的无未来函数断言。
