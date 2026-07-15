# Sprint 1.10 — 报告接入回测指标（Report Backtest Enrichment）

## 目标
把已有的回测引擎（Sprint 1.6 `BacktestEngine`）接到刚做完的每日研究日报（Sprint 1.8）上：
给排序后的每个 Top-N 候选补一段**历史回测表现**，让"为什么排前面"多一层实证注脚。

## 为什么是"per-candidate"而不是"组合回测"
- 现有 `BacktestEngine` 是**单标的**引擎：`run_code(code, dm, start, end)` 一次只回测一只股票。
- 报告是**截面**层（对候选池排序取 Top-N），两者天然对接方式是"给每个候选补一段回测指标"。
- "Top-N 组合再平衡回测"需要跨标的组合层，当前引擎不支持，改造量大，**单独排期**，不塞进本环节。

## 设计要点
1. **复用，不重写**：`ReportEngine` 内部惰性构建 `BacktestEngine.from_config(indicators, factors, strategies, backtest)`，对每个排序后的候选调用 `run_code`。
2. **无未来函数（no look-ahead）**：回测窗口 = `[start_date, as_of]`。报告里价格快照的上界 `snap_end` 已经等于 `as_of`（或最新），回测直接复用同一个 `snap_end`，与排名截面同源，不会泄漏未来数据。
3. **只回测 Top-N**：回测只在排序后、展示的候选上跑，成本有界（不会给宇宙里每只都跑全历史）。
4. **配置化**：
   - `ReportConfig.include_backtest: bool`（默认 `false`）。
   - `backtest` 段（Sprint 1.6 已有）决定回测哪个 `signal_<name>`、费率、指标集；报告取其中的 `total_return / max_drawdown / sharpe / benchmark_return` 四项做紧凑展示。
   - CLI：`python main.py report CODE... --backtest`。
5. **可测试性**：`ReportEngine.__init__` 接受可注入的 `backtest_fn(code, dm, start, end) -> dict | None`，单测用桩函数验证接线、无未来函数窗口、markdown/json 渲染，无需真实数据与网络。

## 数据流
```
ranking Top-N 候选
   └─ 对每个候选 code:
        _backtest_snapshot(code, dm, start, snap_end)   # snap_end == as_of
              └─ BacktestEngine.run_code → {total_return, max_drawdown, sharpe, benchmark_return}
        ReportRow.bt_total_return / bt_max_drawdown / bt_sharpe / bt_benchmark_return
```
日报 `DailyReport.backtest_included` 标记本份报告是否含回测列，控制 markdown 表格/明细与 json 的字段输出。

## 改动文件
- `src/report/engine.py`：`ReportRow` 加 4 个 `bt_*` 字段；`ReportEngine` 加 `backtest_config` / 可注入 `backtest_fn`、惰性 `_get_bt_engine()`、`_backtest_snapshot()`；`generate()` 接回测快照；`to_markdown/to_dict` 输出回测列。
- `src/core/config.py`：`ReportConfig.include_backtest`。
- `config/settings.yaml`：`report.include_backtest: false`。
- `main.py`：`report` 命令加 `--backtest` 开关，开启时把 `cfg.backtest` 传入。
- `tests/test_report.py`：覆盖 默认关闭 / 注入指标生效 / 无未来函数窗口 / 空指标 / markdown 列 / json 字段 / 真实引擎空数据兜底。

## 门禁
ruff / black / mypy / pytest 四门全绿。
