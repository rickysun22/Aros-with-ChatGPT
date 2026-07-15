# Sprint 1.16 — 组合回测（Top-N 再平衡）

## 目标
把「单标的回测」(1.6) 升级为「跨标的组合层」：在多个再平衡日，按截面排名选出 Top-N，
等权持有到下一次再平衡，组合净值 = 各标的净值按当前持仓加权求和。这是之前列表里
「组合回测」这一档的落地——不重写 1.6 引擎，而是复用它的单标的净值曲线做组合。

## 设计
- **`PortfolioBacktest`**（`src/backtest/portfolio.py`）：
  - `from_config(indicators, factors, strategies, ranking, backtest, top_n, rebalance_freq)` 内部构造
    `RankingEngine` + `BacktestEngine`。
  - `run(codes, dm, start, end, rank_fn, equity_fn)`：
    1. 用 `equity_fn` 取每只标的的净值序列（按日期对齐到公共交易日历，ffill/bfill 补齐）。
    2. 再平衡日 = `pd.date_range(..., freq=rebalance_freq)` 快照到「不晚于该日的最近交易日」；
       首个交易日强制再平衡（建仓）。
    3. 每个再平衡日：`rank_fn` 给出当日 Top-N → 平掉旧仓、按当前组合市值等权建新仓；
       记录一次 `rebalance` 交易（用于 num_trades / turnover）。
    4. 组合净值逐日 = Σ 持仓_i × 净值_i(t)。
    5. 基准 = 全候选集等权买入持有（不调仓）。
  - **可测试**：`rank_fn` / `equity_fn` 可注入，单测不依赖真实流水线/数据。
- **`PortfolioResult`**：`equity` / `metrics` / `selections` / `trades` + `to_dict()`。
- **无未来函数**：再平衡日 *t* 的选股只用截至 *t* 的数据（排名 as_of = *t*）；每只净值来自 1.6 的成本感知曲线，本身无泄漏。
- **CLI `portfolio`**：`portfolio CODE... --top-n --rebalance ME --universe POOL --start --end`。

## 与 1.10/1.11 的关系
1.10/1.11 是把单标的回测附到报告/自选股；1.16 是把单标的净值「组合」起来，回答
「按排名买一篮子、定期再平衡」的实证表现。三者共用 `BacktestEngine`。

## 测试
- `tests/test_portfolio.py`：组合净值增长、Top-N 持仓约束、空数据优雅退出、to_dict。
- 全部用注入的 `rank_fn`/`equity_fn`，无需真实数据。

## 改动文件
- `src/backtest/portfolio.py`（新增）
- `src/backtest/__init__.py`（导出 `PortfolioBacktest` / `PortfolioResult`）
- `main.py`（导入；新增 `portfolio` 命令）
- `tests/test_portfolio.py`（新增，4 项测试）
