# AROS — Sprint 1.6 回测引擎设计案

> 状态：待评审（ChatGPT PASS 后启动实现）
> 目标：把 Sprint 1.5 的 `signal` 列**模拟成真实可交易的 A 股组合**，产出权益曲线、成交明细与绩效指标。
> 约束（继承自项目原则，不可让步）：单一数据源 `DataManager`；禁止未来函数；全参数配置化；`pytest`/`ruff`/`black`/`mypy` 四门全绿才视为完成。

---

## 1. 目标与范围

Sprint 1.5 的策略层只负责"给信号"（每个交易日输出 `signal` 列：`+1` 多头 / `0` 空仓，`-1` 空头为保留位）。Sprint 1.6 负责"算收益"——把信号模拟成**带 A 股真实交易成本**的多/空组合，回答"按这个信号交易到底赚不赚钱"。

- 输入：策略层产出的 `signal_<name>` 列（经 `StrategyEngine` 计算）。
- 输出：
  1. **权益曲线**（含手续费/印花税/过户费/滑点），追加 `equity` 列；
  2. **成交明细**（每次换仓的日期、方向、价格、成交金额、成本、已实现盈亏）；
  3. **绩效指标**（总收益、年化、最大回撤、Sharpe、Sortino、胜率、交易次数、换手率，可选基准对比）。
- 不在此 Sprint：跨标的组合配置（1.7 排序决定持有哪些标的/策略）、参数寻优、日内/盘口级滑点建模、做空交易（A 股现实暂不支持）。

设计必须保证：**bar *t* 的权益与指标只依赖 ≤ *t* 的数据**（收益曲线继承 `Portfolio` 的"t-1 仓位吃 t→t+1 收益"约定，成本在 t-1 收盘按已知价格计提），由自动化截断测试兜底。

---

## 2. 会计约定（无未来函数的核心）

复用 `Portfolio` 的持仓约定（见 `src/strategies/portfolio.py`）：

- `pos[t]` = 第 *t* 根 bar 的目标仓位（来自 `signal[t]`：`LONG → 1.0`，`FLAT → 0.0`）。
- 在区间 `[t-1, t]` 内实际持有的仓位是 `pos[t-1]`（在 *t-1* 收盘依据 `signal[t-1]` 建仓），赚取 *t-1→t* 的收益。
- 换仓发生在 *t-1* 收盘：从 `pos[t-2]` 变为 `pos[t-1]`，成本在 *t-1* 收盘按已知价格计提。

收益序列（递归，`t ≥ 1`）：

```
ret[t]      = close[t] / close[t-1] - 1
chg[t-1]    = pos[t-1] - pos[t-2]                 # t=1 时 pos[t-2] 视作 0
notional    = |chg[t-1]| * price[t-1] * equity[t-1]   # 成交金额
cost[t-1]   = commission(notional)                 # 双边，单笔最低 ¥5
            + stamp_tax(notional)  if chg[t-1] < 0  # 仅卖出收
            + transfer(notional)                    # 双边
            + slippage(notional)                    # 双边（默认 0）
equity[t]   = (equity[t-1] - cost[t-1]) * (1 + pos[t-1] * ret[t])
equity[0]   = initial_cash （首根 bar 不建仓、不计提成本）
```

无未来函数校验：上式右侧每一项（`pos[t-1]`、`pos[t-2]`、`price[t-1]`、`equity[t-1]`、成本）均在 *t-1* 及之前已知；`ret[t]` 用的 `close[t-1]` 也已知，仅 `close[t]` 用于标记已决定仓位的市值，不影响 *t-1* 的建仓决策。✅

---

## 3. A 股成本模型（默认费率，2024）

| 费用 | 方向 | 默认费率 | 备注 |
|------|------|----------|------|
| 佣金 commission | 双边 | `0.00025`（万 2.5） | 单笔最低 `¥5`（按侧计） |
| 印花税 stamp_tax | 仅卖出 | `0.0005`（万 5） | 2023-08-28 由万 10 减半 |
| 过户费 transfer_fee | 双边 | `0.00001`（万 0.1） | 中国结算收取 |
| 滑点 slippage | 双边 | `0.0`（可配） | 以成本拖累形式计入，简化模型 |

所有费率集中在 `CostConfig`，默认即上表；费率变动只改配置不改代码。

---

## 4. 模块结构（沿用"三件套" + 复用 `Portfolio`）

新增 `src/backtest/`：

```
src/backtest/
├── __init__.py      # 导出 BacktestEngine / CostModel / compute_metrics / available / build
├── cost.py          # CostModel：给定仓位变化与价格，计提四项成本
├── metrics.py       # 纯函数：由权益序列 + 成交明细计算各项绩效指标
└── engine.py        # BacktestEngine：组合 StrategyEngine + CostModel + metrics
```

- **`cost.py` — `CostModel`**：`__init__(commission_rate, commission_min, stamp_tax_rate, transfer_fee_rate, slippage)`；`charge(notional, is_sell) -> float` 返回本次成交成本（元）。纯函数、可单测。
- **`metrics.py`**：`total_return / cagr / max_drawdown / sharpe / sortino / win_rate / profit_factor / num_trades / turnover` 等纯函数，输入 `equity: pd.Series` 与 `trades: pd.DataFrame`，输出 `dict[str, float]`。附带 `benchmark_return(close)` 计算同名标的买入持有收益。
- **`engine.py` — `BacktestEngine`**：编排层，复用 `Portfolio.positions` 取目标仓位序列，再套用 §2 的含成本模拟；`from_config` 构建 `StrategyEngine` 后注入成本与回测配置。

> 为何不复用 `Portfolio.mark_to_market` 直接出权益？`mark_to_market` 是无成本的"标记"原语（1.5 已测、1.7 仍会用）。1.6 在其之上叠加成本，二者职责分离：`Portfolio` = 仓位/无成本市值；`BacktestEngine` = 含成本模拟 + 指标。回测引擎通过 `Portfolio.positions(df, signal_col)` 复用经过测试的仓位推导。

---

## 5. 引擎 API（`src/backtest/engine.py`）

```python
class BacktestEngine:
    def __init__(
        self,
        strategy_engine: StrategyEngine,
        cost: CostModel,
        config: BacktestConfig,
    ) -> None:
        ...

    @classmethod
    def from_config(
        cls,
        indicators: IndicatorConfig,
        factors: FactorConfig,
        strategies: StrategyConfig,
        backtest: BacktestConfig,
    ) -> "BacktestEngine":
        se = StrategyEngine.from_config(indicators, factors, strategies)
        cost = CostModel(**backtest.cost.model_dump())
        return cls(se, cost, backtest)

    def run(self, df: pd.DataFrame, signal_col: str | None = None) -> tuple[pd.DataFrame, dict]:
        """返回 (含 equity / position / trades 列的 DataFrame, 指标 dict)。

        signal_col 缺省时取 backtest.strategy 指定的 signal_<name>，
        再缺省取第一个已配置策略的 signal 列。缺失该列 -> DataError。
        """
        ...

    def run_code(
        self, code: str, data_manager, start_date=None, end_date=None, signal_col=None
    ) -> tuple[pd.DataFrame, dict]:
        df = data_manager.get_daily(code, start_date, end_date)
        return self.run(df, signal_col) if not df.empty else (df, {})

    @property
    def names(self) -> list[str]:           # 委托 StrategyEngine
        ...
```

多标的：`run` 内若 `df` 含多 `code`，按 code 分组各自回测后合并（1.6 不做跨标的配置，仅分别出指标；组合配置留给 1.7）。

---

## 6. 配置 schema（`config/settings.yaml` 新增段）

```yaml
# Backtest Engine (Sprint 1.6) - 把信号模拟成真实 A 股组合
backtest:
  strategy: weighted_momentum        # 回测哪个策略的 signal_<name>；缺省取第一个
  initial_cash: 1000000.0
  max_position: 1.0                  # 单标的仓位上限（1.0 = 满仓）
  risk_free: 0.0                     # 无风险年化，用于 Sharpe/Sortino
  metrics:
    - total_return
    - cagr
    - max_drawdown
    - sharpe
    - sortino
    - win_rate
    - num_trades
    - turnover
  benchmark: true                    # 与同名标的买入持有对比
  cost:
    commission_rate: 0.00025
    commission_min: 5.0
    stamp_tax_rate: 0.0005
    transfer_fee_rate: 0.00001
    slippage: 0.0
```

一致性约束：`backtest.strategy` 必须对应某条已启用的策略（即存在 `signal_<strategy>` 列），否则 `run` 时抛 `DataError`；`max_position` 越界、`metrics` 含未知指标名 → `ConfigError`。

---

## 7. 核心配置模型（`src/core/config.py`）

```python
class CostConfig(BaseModel):
    commission_rate: float = 0.00025
    commission_min: float = 5.0
    stamp_tax_rate: float = 0.0005
    transfer_fee_rate: float = 0.00001
    slippage: float = 0.0


class BacktestConfig(BaseModel):
    strategy: str | None = None            # 回测哪个策略；None -> 第一个启用策略
    initial_cash: float = 1_000_000.0
    max_position: float = 1.0             # 单标的仓位上限
    risk_free: float = 0.0
    metrics: list[str] = Field(default_factory=lambda: [
        "total_return", "cagr", "max_drawdown", "sharpe",
        "sortino", "win_rate", "num_trades", "turnover",
    ])
    benchmark: bool = True
    cost: CostConfig = Field(default_factory=CostConfig)
```

并接入 `AppConfig.backtest`（`get_config()` 可见）。

---

## 8. CLI（`main.py` 新增 `backtest` 命令）

```bash
python main.py backtest --list                              # 列出可用策略（供 --strategy 选择）
python main.py backtest 600000                              # 回测默认策略，打印指标摘要
python main.py backtest 600000 --strategy weighted_momentum
python main.py backtest 600000 --start 2024-01-01 --end 2024-12-31
```

输出：指标摘要（总收益 / 年化 / 最大回撤 / Sharpe / Sortino / 胜率 / 交易次数 / 换手率）+ 基准对比 + 权益曲线末 10 行。命令体结构与 `strategies` 命令对称（先 `from_config` 构建 `StrategyEngine` 再包 `BacktestEngine`，缺失 `--strategy` 名 `exit(2)`）。

---

## 9. 与上下层的接口

- **上游（1.5）**：消费 `signal_<name>` 列，约定为 int 值域 `{+1, 0}`（`-1` 保留），`NaN` 视为 `0`（已由 `Portfolio.positions` 处理）。`BacktestEngine` 通过 `StrategyEngine` 一次跑完指标→因子→策略→信号，不重复取数。
- **下游（1.7 排序）**：`metrics` 字典（尤其 `sharpe`/`max_drawdown`/`total_return`）作为排序输入；多标的分别回测后，1.7 按指标排名选出最优标的/策略组合。
- **下游（1.8 报告）**：权益曲线 + 成交明细 + 指标摘要直接喂给报告渲染。

---

## 10. 测试计划（`tests/test_backtest.py`，镜像 `test_strategies.py`）

- **成本模型**：佣金最低 ¥5 生效阈值；印花税仅卖出计；过户费双边；滑点叠加。`charge()` 纯函数手算一致。
- **含成本模拟**：含成本权益 ≤ 无成本权益；多空信号下权益曲线方向正确。
- **无未来函数不变量**：bar *t* 的 `equity` 与指标在全序列上计算 == 仅在 `bars[0..t]` 上计算（与策略层同款截断测试）。
- **仓位上限**：`max_position < 1.0` 时实际仓位被裁剪。
- **指标正确性**：在合成权益序列上，总收益/年化/最大回撤/Sharpe 手算一致；胜率/交易次数与成交明细一致。
- **成交明细**：换仓次数、买卖方向、成本金额正确。
- **编排**：`BacktestEngine.run_code` 产出指标 dict + `equity` 列；缺失 `signal` 列 → `DataError`。
- **CLI 冒烟**：`backtest --list` 与 `backtest 600000` 退出码 0 且含指标名。

---

## 11. 完成定义（提交 ChatGPT 评审的验收清单）

- [ ] `src/backtest/`（cost.py / metrics.py / engine.py / `__init__.py`）+ `core/config.py` 模型 + `settings.yaml` 段 + `main.py backtest` 命令全部落地
- [ ] `pytest` / `ruff` / `black --check` / `mypy src tests main.py` **四门全绿**（GitHub Actions 通过）
- [ ] `tests/test_backtest.py` 覆盖 §10 七类
- [ ] `CHANGELOG.md` 新增 Sprint 1.6 段
- [ ] `Roadmap.md` 将 1.6 标为 completed（**待 ChatGPT PASS 后由评审方落章**）
- [ ] 本设计案经 ChatGPT 评审通过

---

## 12. 风险与开放问题（请 ChatGPT 评审时一并确认）

1. **单标的回测**：1.6 只做单标的（或按 code 分组分别回测），不做跨标的资金配置。组合层（如何把资金分配到多个入选标的）由 1.7 排序结果驱动，1.6 先不实现。
2. **做空**：A 股暂不支持裸卖空，1.6 仅处理 `signal ∈ {+1, 0}`；`-1` 保留为扩展位，出现 `-1` 时按 `0`（空仓）处理并记一条 warning。
3. **滑点建模**：1.6 用"固定成本拖累"近似滑点（`slippage * notional`），不做盘口冲击/逐笔撮合；若评审认为需要更真实，可升级为"执行价偏移"模型（仍无未来函数）。
4. **仓位规模**：1.6 仓位 = 信号权重（LONG→`max_position`），无波动率/风险平价/凯利等规模控制；这些留待策略层或 1.7 组合层。
5. **基准**：单标的基准 = 同名标的买入持有；未来多标的组合基准应为等权/沪深300，1.7 再定。
6. **费率来源**：默认费率取自 2024 年 A 股通用值，全部可配；若项目有券商实际费率，改 `settings.yaml` 即可，无需改码。
7. **换仓时点**：信号在 *t* 收盘判定，仓位在 *t* 收盘生效、吃 *t→t+1* 收益（与 `Portfolio` 一致）。若评审希望"信号次日开盘生效"，需调整 `ret` 取 `open[t+1]/close[t]-1` 类约定——本设计采用更常见的"收盘换仓"。
