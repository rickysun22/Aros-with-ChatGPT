# Sprint 1.8 - 每日研究日报引擎（Daily Report）

> 状态：实现中（本地）
> 上游：data -> indicators -> factors -> strategies -> backtest -> ranking -> **report**

## 1. 目标

把整条研究流水线的最终产出（排序层 Top-N 候选）聚合成一份**可读的每日研究日报**，
让研究员一眼看到"今天该重点看哪些票、它们的综合分与日涨跌如何、数据是否新鲜"。
日报引擎是一个**聚合/呈现层**，不引入任何新的因子或指标数学。

## 2. 复用关系（不重复造轮子）

- **RankingEngine**（Sprint 1.7）：负责截面复合打分、Top-N 选取、权重归一化、as_of 截面。
- **DataManager**（Sprint 1.2）：唯一数据入口；日报引擎向它取每个候选标的的最新 1~2 根 K 线，
  用于补全"最新价 / 日涨跌% / 数据日期 / 数据新鲜度"。
- 日报引擎本身**不计算** score，只搬运与渲染 RankingEngine 的结果。

## 3. 数据结构

- `ReportRow`：rank, code, composite_score, scores{name->score}, close, as_of_date, daily_change_pct, stale
- `DailyReport`：generated_at, as_of, universe_size, source, rows[]

## 4. 生成流程（ReportEngine.generate）

1. 用 ReportConfig 的 top_n / as_of 驱动 RankingEngine，得到 Top-N 排名表。
2. 对每个 code，向 DataManager 取**最新两根（<= as_of）K 线**：
   - close = 最新收盘价；as_of_date = 该 K 线日期；
   - daily_change_pct = (close/prev_close - 1) * 100；仅 1 根时记 None（不伪造涨跌）；
   - stale = as_of 给定且数据滞后超 freshness_days 时为 True。
3. 组装 DailyReport。

## 5. 无未来函数（项目铁律）

- 价格快照取数上界 = ranking 层同一 as_of；snapshot 只取该截面**及之前**的 K 线。
- 日涨跌只用"截面当根 vs 前一根"，两者都 <= as_of，无前视。

## 6. 配置（config/settings.yaml -> ReportConfig）

    report:
      top_n: 20
      as_of: null
      format: markdown        # markdown | json
      freshness_days: 5
      include_detail: true

## 7. 输出与 CLI

- `DailyReport.to_markdown()` / `to_json()`。
- CLI：`report CODE... [--top-n] [--as-of] [--start] [--end] [--format] [--out]`；`report --list`。

## 8. 验收（四门门禁）

- ruff / black / mypy / pytest 全绿。
- 覆盖：等权/Top-N/as_of、价格快照与日涨跌、空结果、markdown/json、include_detail、真实配置接线、CLI --list、无未来函数断言。
