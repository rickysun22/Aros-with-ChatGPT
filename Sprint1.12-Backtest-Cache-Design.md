# Sprint 1.12 — 回测结果缓存落库（Backtest Cache）

## 目标
把「单标的回测」这一最耗时的环节做结果缓存：相同窗口 + 相同参数组合的结果落库，
重复跑时直接命中，跳过仿真循环。这是对 1.10（报告回测）与 1.11（自选股回测落库）
的性能地基——两者现在每次都调用 `BacktestEngine.run_code`，命中缓存后几乎零成本。

## 设计
- **新增 `BacktestCache` ORM 模型**（`src/backtest/cache.py`，挂在 `core.database.Base`）：
  - 列：`code`、`params_hash`、`start`、`end`、`signal_col`、`metrics_json`、`equity_json`、`created_at`
  - 唯一约束 `(code, params_hash)`，一个窗口+参数组合只存一行（命中即覆盖）。
- **缓存键 `params_hash`**：折叠一切会改变仿真结果的输入——
  `signal` 列名 + `cost` 费率 + `initial_cash` + `max_position` + `benchmark` 开关 + `start/end` 窗口。
  换个 `as_of`（即换 `end`）就是自然的 miss。
- **`run_code_cached(engine, code, dm, start, end, signal_col, session=None)`**：
  先查缓存；命中则把 `equity_json` 重新挂回新加载的价量帧（保证读 `df['equity']` 的调用方照常工作），
  返回缓存 `metrics`；未命中则调用 `engine.run_code(..., use_cache=False)` 实算并存库。
- **接入 `BacktestEngine.run_code`**：新增 `use_cache: bool = True` 形参；
  当 `use_cache and config.cache_enabled` 时走 `run_code_cached`。
  **缓存层全部 best-effort**：任何 DB 异常都被捕获并降级为实时计算，缓存永远不会让回测报错。
- **配置**：`BacktestConfig.cache_enabled`（默认 `True`）；`settings.yaml` 暴露。

## 无未来函数
缓存只存「已算完的历史结果」，读取时不影响任何截面/回测窗口计算，与 1.10/1.11 同源同源、零泄漏。

## 测试
- `test_backtest_cache_hit_avoids_recompute`：同窗口第二次调用不触发重算（计数=1），换窗口触发重算。
- `test_backtest_cache_persists_rows`：不同 code 各落一行。
- `test_backtest_params_hash_deterministic`：同输入哈希稳定，改窗口哈希变。
- 复用隔离 sqlite session，不依赖真实数据库。

## 改动文件
- `src/backtest/cache.py`（新增）
- `src/backtest/engine.py`（`run_code` 加 `use_cache`、接入 `run_code_cached`）
- `src/backtest/__init__.py`（导出 `BacktestCache`）
- `src/core/config.py`（`BacktestConfig.cache_enabled`）
- `config/settings.yaml`（`backtest.cache_enabled`）
- `tests/test_backtest.py`（3 项缓存测试）
