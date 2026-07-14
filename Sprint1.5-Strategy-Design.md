# AROS — Sprint 1.5 策略引擎设计案

> 状态：待评审（ChatGPT PASS 后启动实现）
> 目标：把 Sprint 1.4 的因子层组合成**可解释的短线交易信号**。
> 约束（继承自项目原则，不可让步）：单一数据源 `DataManager`；禁止未来函数；全参数配置化；`pytest`/`ruff`/`black`/`mypy` 四门全绿才视为完成。

---

## 1. 目标与范围

Sprint 1.5 在已有的"指标 → 因子"管线之后，新增一层**策略（Strategy）**：

- 输入：因子层产出的各因子列（如 `ma_cross`、`rsi_signal`、`macd_cross` …）。
- 输出：每只股票每个交易日的 **`signal` 列**（`+1` 多头 / `0` 空仓 / `-1` 空头），可选同时输出连续 `score` 列便于排序（1.7）与回测（1.6）消费。
- 不在此 Sprint：回测、排序、报告、参数寻优。策略只负责"给信号"，不负责"算收益"。

设计必须保证：**bar *t* 的 signal 只依赖 ≤ *t* 的数据**（因子本身已无未来泄漏，策略仅做列上的纯函数变换，天然继承该保证，并由自动化截断测试兜底）。

---

## 2. 策略模型

一个策略 = 一个命名、配置驱动的纯函数，读取 DataFrame 中已存在的因子列，追加 `signal`（及可选 `score`）。

Sprint 1.5 提供两类可组合策略，均通过注册表注册，沿用 `BaseFactor` 的模式：

### 2.1 `weighted`（加权打分）
把每个因子列归一化到 `[-1, 1]`，按权重求和得到连续 `score`，再按阈值映射为 `signal`：

- `score > buy_threshold` → `+1`（多头）
- `score < sell_threshold` → `-1`（空头）
- 否则 → `0`（空仓）

每个因子在配置中给出 `clip: [min, max]`，映射公式：
`norm = clip((v - min)/(max - min), 0, 1) * 2 - 1`。
未给 `clip` 时回退到该因子列的滚动分位或项目默认 `[-1, 1]`（见 §5 风险项）。

### 2.2 `rule`（布尔规则）
用布尔条件组合因子，输出 `+1` / `0`：

- `combine: all` → 全部条件满足才 `+1`，否则 `0`（适合"共振"型短线信号）
- `combine: any` → 任一条件满足即 `+1`，否则 `0`

每个条件：`{ factor: <列名>, op: ">"|">="|"<"|"<="|"=="|"!=", value: <数> }`。

> 为什么两类并存：`weighted` 给出可微、可排序的连续分，`rule` 给出人类可读、易解释的硬规则。两者都用同一套 `BaseStrategy` 接口，后续可加 `ml` 等类型而不破坏管线。

---

## 3. 模块结构（复制既有"三件套"模式）

```
src/strategies/
├── __init__.py      # 导出 StrategyEngine / available / build
├── base.py          # BaseStrategy 抽象类 + 注册表(register/build/available)
├── impl.py          # WeightedStrategy, RuleStrategy（import 即注册）
└── engine.py        # StrategyEngine：组合 FactorEngine，compute / compute_code
```

API 与 `FactorEngine` 对称：

```python
class StrategyEngine:
    def __init__(self, factor_engine, strategies: list[BaseStrategy]): ...

    @classmethod
    def from_config(cls, factor_engine, strategies: StrategyConfig) -> "StrategyEngine":
        # factor_engine 由 FactorEngine.from_config(...) 传入
        # 逐个 build(spec.name, spec.params)，未知名抛 ConfigError

    def compute(self, df) -> pd.DataFrame:
        df = self.factor_engine.compute(df)      # 先指标再因子
        for s in self.strategies:
            df = s.compute(df)                   # 再叠加策略
        return df

    def compute_code(self, code, data_manager, start_date=None, end_date=None) -> pd.DataFrame:
        df = data_manager.get_daily(code, start_date, end_date)
        return self.compute(df) if not df.empty else df

    @classmethod
    def available(cls) -> list[str]: ...
    @property
    def names(self) -> list[str]: ...
```

`BaseStrategy` 与 `BaseFactor` 同构（类名/`register`/`build`/`available`），保证一致性。

---

## 4. 配置 schema（`config/settings.yaml` 新增段）

```yaml
# Strategy Engine (Sprint 1.5) - 组合因子为可交易信号
strategies:
  enabled:
    - name: weighted_momentum
      type: weighted
      params:
        weights:
          - { factor: ma_distance, weight: 0.15, clip: [-0.15, 0.15] }
          - { factor: ma_cross,    weight: 0.20 }
          - { factor: rsi_signal,  weight: 0.15 }
          - { factor: macd_cross,  weight: 0.20 }
          - { factor: kdj_cross,   weight: 0.15 }
          - { factor: vol_ratio,   weight: 0.05, clip: [0.5, 2.5] }
          - { factor: boll_position, weight: 0.05 }
          - { factor: momentum,    weight: 0.05, clip: [-0.1, 0.1] }
        buy_threshold: 0.30
        sell_threshold: -0.30
    - name: golden_cross_rule
      type: rule
      params:
        combine: all
        conditions:
          - { factor: ma_cross,   op: ">",  value: 0 }
          - { factor: macd_cross, op: ">",  value: 0 }
          - { factor: rsi_signal, op: "<",  value: 70 }
```

一致性约束（与因子层一致）：策略引用的因子名必须已在 `factors.enabled` 中产出，否则 `build`/`compute` 时抛 `ConfigError` / `DataError`，立即失败而非静默。

---

## 5. 核心配置模型（`src/core/config.py`）

```python
class WeightSpec(BaseModel):
    factor: str
    weight: float
    clip: tuple[float, float] | None = None

class WeightedParams(BaseModel):
    weights: list[WeightSpec]
    buy_threshold: float = 0.30
    sell_threshold: float = -0.30

class ConditionSpec(BaseModel):
    factor: str
    op: Literal[">", ">=", "<", "<=", "==", "!="]
    value: float

class RuleParams(BaseModel):
    combine: Literal["all", "any"] = "all"
    conditions: list[ConditionSpec]

class StrategySpec(BaseModel):
    name: str
    type: Literal["weighted", "rule"]
    params: dict = {}

class StrategyConfig(BaseModel):
    enabled: list[StrategySpec] = []
```

并接入 `AppConfig.strategies`（`get_config()` 可见）。

---

## 6. CLI（`main.py` 新增 `strategies` 命令）

```bash
python main.py strategies --list                       # 列出可用/已配置策略
python main.py strategies 600000                        # 计算因子+策略信号
python main.py strategies 600000 --name weighted_momentum
python main.py strategies 600000 --start 2024-01-01 --end 2024-03-31
```

输出列：`date, close, <因子列…>, signal`（可选 `score`）。命令体结构与现有 `factors` 命令对称（先 `from_config` 构建 `FactorEngine` 再包 `StrategyEngine`，缺失名 `exit(2)`）。

---

## 7. 与 FactorEngine 的集成 & 无未来函数

- `StrategyEngine.from_config` 接收已构建的 `FactorEngine`，`compute` 内顺序执行 指标→因子→策略，**一次遍历**，不重复取数。
- 策略仅在"已存在的因子列"上做纯函数变换（归一化、加权、布尔比较），不引入任何跨 bar 的滞后/前瞻，因此**自动继承**指标与因子的无未来函数保证。
- 由 §9 的截断测试在 CI 中自动验证。

---

## 8. 具体候选策略（默认启用前两个，可在评审中增删）

1. **`weighted_momentum`**（weighted）：8 因子加权连续分，适合 1.6 回测与 1.7 排序。
2. **`golden_cross_rule`**（rule）：MA 金叉 + MACD 金叉 + RSI 未超买 的"共振"硬规则，解释性最强。
3. （备选，评审决定）**`mean_reversion_rule`**：`boll_position < 0.2` 且 `rsi_signal < 30` → 超跌反弹信号。

---

## 9. 测试计划（`tests/test_strategies.py`，镜像 `test_factors.py`）

- **正确性**：weighted 手算加权分与阈值映射一致；rule 的 `all`/`any` 布尔组合一致。
- **编排**：`StrategyEngine.compute` 在单只/多只股票上一次性产出 指标+因子+signal。
- **缺失列**：策略引用未启用的因子 → 抛 `ConfigError`/`DataError`。
- **无未来函数不变量**：bar *t* 的 `signal` 在全序列上计算 == 仅在 `bars[0..t]` 上计算（与因子层同款截断测试）。

---

## 10. 完成定义（提交 ChatGPT 评审的验收清单）

- [ ] `src/strategies/` 三件套 + `core/config.py` 模型 + `settings.yaml` 段 + `main.py strategies` 命令全部落地
- [ ] `pytest` / `ruff` / `black --check` / `mypy src tests main.py` **四门全绿**（GitHub Actions 通过）
- [ ] `tests/test_strategies.py` 覆盖 §9 四类
- [ ] `CHANGELOG.md` 新增 Sprint 1.5 段
- [ ] `Roadmap.md` 将 1.5 标为 completed（**待 ChatGPT PASS 后由评审方落章**）
- [ ] 本设计案经 ChatGPT 评审通过

---

## 11. 风险与开放问题（请 ChatGPT 评审时一并确认）

1. **归一化默认值**：`weighted` 中未给 `clip` 的因子（如 `rsi_signal`/`ma_cross` 本就是 `[-1,1]` 或 `{0,±1}`，可直接用；`boll_position` 是 `[0,1]`）是否需要统一强制 `clip`，还是信任因子原生区间？建议：因子原生已在 `[-1,1]` 内的不要求 `clip`，其余必须给。
2. **信号语义**：`weighted` 用 `+1/0/-1` 三态；`rule` 用 `+1/0` 两态（无显式做空）。是否需要在 1.5 就支持 A 股"只能平/多"的现实（即 signal ∈ {+1, 0}），把 `-1` 留给未来做空扩展？建议 1.5 先只产出 `{+1, 0}`，与 A 股 T+1/禁止裸卖空一致，`-1` 保留为扩展位。
3. **多策略并存**：`compute` 同时跑多个策略会追加多个 `signal` 列（如 `signal_weighted_momentum`、`signal_golden_cross_rule`）。列名是否带策略名前缀以避免冲突？建议带前缀。
4. **与 1.6 回测的接口**：回测消费 `signal` 列。1.5 是否需约定 `signal` 为 int8 且 `NaN` 视为 `0`？建议约定。
