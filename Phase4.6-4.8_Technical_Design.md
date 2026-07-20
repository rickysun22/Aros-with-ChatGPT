# AROS Phase 4.6–4.8 技术设计：试运行验证与执行智能（Pilot Validation & Execution Intelligence）

> 状态：**定稿（GPT + WorkBuddy 联合评审通过，待开发）**
> 范围：Phase 4.6 评分校准 → Phase 4.7 模拟交易（退出实验）→ Phase 4.8 执行智能架构占位（不开发）
> 文档性质：一份贯通 4.6–4.8 的设计契约，取代此前分散的 4.6 / 4.7 草稿用于统一评审。

---

## 0. 设计背景与三大引擎定位

AROS 在 4.0–4.5 已具备：策略知识库、策略验证、共识引擎（选股）、市场环境+资金流、每日 Alpha 报告、人工反馈闭环。

本设计把系统从"研究工具"推进到"经真实市场验证的辅助决策系统"，并冻结**三大核心引擎**定义：

| 引擎 | 解决痛点 | 落地阶段 | 组成 |
|---|---|---|---|
| **Alpha Selection Engine** | 不会选（不知道买什么） | 已完成（4.2 共识引擎） | Strategy Consensus + 资金流 + 市场环境 |
| **Alpha Execution Engine** | 不会买（何时进场） | Phase 4.8 设计 / Phase 5 实现 | Entry Signal + Entry Confidence Score + Position Sizing + Timing |
| **Alpha Protection Engine** | 不会卖（何时离场） | 4.7 起实证验证 | Stop Loss + Take Profit + Trailing + Score Decay |

**核心方法论原则（贯穿 4.6–4.8）**：把"选股能力"与"卖出能力"**拆开验证**，避免变量混杂（Confounding Variable）。否则模拟盘盈亏无法归因——不知道是选股强、人工强、还是卖点强。

**入场信号的特别说明（针对 StrategySpec.entry_rules 的澄清）**：
`src/research/strategy_spec.py` 中每个策略自带的 `entry_rules: list[str]` 是**收集来的策略原文买入规则**，属于参考资料（inputs），**不等于** AROS 自己的进场信号。AROS 的 Entry 引擎（Phase 4.8）是一个**合成层**：结合（a）命中策略组合、（b）标的当期实况（价格行为/量/位置）、（c）市场判断（regime/资金流），产出统一的 **Entry Signal + Entry Confidence Score**。"集百家之所长"，而非直接 follow 任一原始策略规则。

---

## 路线图（更新）

```
Phase4.5  Human Feedback Loop
    │
    ↓
Phase4.6  Rating Validation & Calibration      ← 证明评分体系有效
    │
    ↓
Phase4.7  Paper Trading (Exit Experiment)      ← 验证"卖法"，隔离执行价值
    │
    ↓
Phase4.8  Execution Intelligence Design         ← 架构占位（Entry/Exit/Position）
    │
    ↓
Phase5     Execution Engine                      ← 真正实现 Entry/Exit Intelligence
```

---

# Part I — Phase 4.6：评分体系验证与校准（Rating Validation & Calibration）

## I.1 目标

Phase 4.6 **不进行新策略开发**，只回答一个最关键验收问题：

> **高评分股票是否长期显著优于低评分股票？**（关注 S>A>B>C 的单调性 + 统计显著性，而非单只涨跌。）

## I.2 与现有代码的复用

| 现有能力 | 位置 | 4.6 用法 |
|---|---|---|
| `post_hoc()` 后验 | `src/research/feedback.py` | 扩到 T+20 + 目标达成时间 |
| `DecisionTracking` | `src/research/models.py` | 人工 Top5 记录（人处理的子集） |
| `hit_strategies_json` | `DailyAlphaCandidate` | 策略贡献归因 |
| `BenchmarkProvider` | `src/research/consensus.py` | 基线对比（沪深300/中证500/等权） |
| `DailyAlphaReport.generate` | `src/report/daily_alpha.py` | 报告三件套模式复用 |
| `CandidatePerformance`（新增） | `src/research/models.py` | 全量自动复盘 |

## I.3 三个硬冲突的修正（延续此前评审）

1. **评级命名冲突**：现有 `rating_from_score()` 产 `A+ / A / B / C`。4.6 顶部桶改名为 **`S`**（历史 `"A+"` 需一次性 `UPDATE` 迁移）。
2. **全量自动复盘缺表**：新增 `CandidatePerformance`（按 `candidate_id` 一行，自动由 `post_hoc` 填充），与 `DecisionTracking` 平级、可选 JOIN。
3. **模拟盘独立成 4.7**：4.6 只做评分有效性统计，不含账户。

## I.4 数据模型：`CandidatePerformance`

```python
class CandidatePerformance(Base):
    __tablename__ = "candidate_performance"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)   # cp_<candidate_id>
    candidate_id: Mapped[str] = mapped_column(ForeignKey("daily_alpha_candidates.id"))
    code: Mapped[str]
    signal_date: Mapped[date]
    aros_score: Mapped[float]
    rating: Mapped[str]            # S / A / B / C
    # 后验收益（T+1 入场价 = signal_date 后第1交易日收盘，无前视）
    result_1d: Mapped[float | None]
    result_3d: Mapped[float | None]
    result_5d: Mapped[float | None]
    result_10d: Mapped[float | None]
    result_20d: Mapped[float | None]
    max_float_profit: Mapped[float | None]   # 区间内最大涨幅（有利漂移）
    max_float_loss: Mapped[float | None]     # 区间内最大回撤（不利漂移）
    target_hit_date: Mapped[date | None]     # 首次触达 +X% 目标的交易日（新增）
    status: Mapped[str | None]               # success / fail / pending（定义见 I.6）
    filled_at: Mapped[date | None]
```

`post_hoc` 扩展：`POSTHOC_DAYS = (1, 3, 5, 10, 20)`，`window` 调大；新增 `target_hit`（首次触达 +5% 的交易日）。

## I.5 量化验收方法论（最核心）

**三层指标，缺一不可：**
1. **档内单调性**：S ≥ A ≥ B ≥ C（严格递减为理想）。
2. **档间显著性**：相邻档用 **Mann-Whitney U / bootstrap CI**，要求 p < 0.05 或收益区间不重叠，才算"具备区分能力"。单纯单调不够。
3. **基线超额**：各档相对同期沪深300 / 中证500 / 全部候选等权的超额收益（证明"比市场强"，不仅是"能排序"）。

**两阶段校准（关键：不急着调参数）：**
- 阶段一（观察）：用当前分差或分位法（top 5%=S、next 15%=A、next 30%=B、其余=C）跑统计，量各档真实表现与分离度。
- **首校门槛：累计 ≥ 60 个交易日**才可正式校准（30 天仅观察、60–90 天正式校准、90 天复校）。理由：A 股月内可能单边行情，30 天易误判。
- 阶段二（校准）：据实测把 `ConsensusConfig.rating_s/a/b` 阈值调到档间干净分离，**反写配置**并写入 CHANGELOG + 校准报告，保证可回溯。

**样本/时间约束**：T+20 指标需最早批次满 20+ 交易日才有值；连续每日运行约 1 个月后报告才可靠。T+20 / 长期指标一律标注「as available / 样本不足 N」。

**复盘节奏（新增）**：每日记录标的表现 → 每周复盘 → 每月 summary；在 30 / 60 / 90 交易日设检查点。

## I.6 成功率定义

以最长可用 horizon（T+10）收益 > 0 为 `success`；或 `max_float_profit` 触达目标（+5%）为成功。规则写死，复盘不各填各的。

## I.7 四个产物报告（`reports/validation/<date>/`）

1. **AROS Rating Calibration Report** — 评分有效性（分层单调性 + 显著性 + 基线超额）。
2. **Strategy Contribution Report** — 按 `hit_strategies_json` 解析统计各策略贡献（趋势/情绪/突破占比）。
3. **Human Decision Report** — 人工 Top5 vs AI Top20 对比（样本不足显式标注）。
4. **Paper Trading Report（占位）** — 4.7 产出，4.6 仅预留入口。

## I.8 Done 标准（Phase 4.6）

1. `CandidatePerformance` 覆盖目标区间 ≥ **95%** 候选，T+10 填充率 ≥ 90%（T+20 按可用样本计）。
2. 分层显示 **S > A > B > C** 严格单调，且相邻档 **Mann-Whitney p < 0.05**。
3. 完成首次校准（≥ 60 交易日后），反写配置并二次验证分离度。
4. 四报告可生成；Human Decision Report 不虚构。
5. 策略贡献分析 + 人工 Top5 vs AI Top20 对比完成。

---

# Part II — Phase 4.7：模拟交易盘（退出实验，Paper Trading / Exit Experiment）

## II.1 目标

验证**执行后的组合收益**，重点是**找到 AROS 最佳卖法**。Stage 与 4.6 因果分离：4.6 证"选股有效"，4.7 证"卖法有效"。

## II.2 红线（宪法）

- **不接券商、不下单、不自动交易**。模拟盘只生成假设性成交。
- 守住 AROS 宪法「不接入自动交易」。

## II.3 实验设计：双轴正交分离（防变量混杂）

**核心问题**：此前的 P1/P2/P3（按退出规则）与 S1/S2/S3（按选股来源）是**两个不同维度**。若混在一起（如 "AI选股+固定止盈" vs "人工选股+动态止盈"），无法归因。故拆为两个独立实验轴，6 个组合**数据永不通用的**：

### Selection Experiment（选股实验轴）
| 组合 | 规则 | 回答 |
|---|---|---|
| **S1** AI Selection | 系统 S/A 级自动进入 | AI 筛选有没有价值？ |
| **S2** Human Enhanced | AI 候选池，人工 Top3-5 | 人工判断是否提升？ |
| **S3** Benchmark | 随机 / 沪深300 | AROS 是否跑赢随机 |

### Exit Experiment（退出实验轴）
| 组合 | 规则 |
|---|---|
| **E1** Fixed Exit | 固定止损 + 固定止盈 + 固定时间 |
| **E2** Trailing Exit | 移动止盈（盈利 +15% 启动，峰值回撤 8% 退出） |
| **E3** Dynamic Exit | 止损 + 移动止盈 + Score Decay + 市场环境/资金变化 |

### 第一阶段范围（拍板）
**只跑退出实验、固定 Selection = S1**：即 **S1+E1 / S1+E2 / S1+E3**，先找到 AROS 最佳卖法；S2/S3 后续再开（人工增强本身是独立实验）。
> 理论上有 3×3=9 组合，但第一阶段不全部跑，避免数据量与维护复杂度爆炸。

## II.4 退出框架 v1.0（三层 + 时间）

**Layer 1 — 硬风控（必须有）**
- 止损模式可配置：`stop_loss.mode ∈ {fixed, atr}`。
  - `fixed`: `fixed_percent = 8`（默认，先建 baseline）。
  - `atr`: `period=14, multiplier=2` → `Stop = Entry - ATR×N`。不同波动股票自适应（v1 默认 fixed，ATR 作为可选模式纳入）。

**Layer 2 — 盈利保护（移动止盈）**
- 启动条件：盈利 ≥ +15%。
- 退出：自峰值回撤 ≥ 8%（如买 100→120，跌到 110.4 卖）。抓趋势、防卖飞。

**Layer 3 — 信号衰减（Score Decay）**
- 触发：连续 N 天（默认 5）代理评分 < 阈值（默认 70）。
- **v1 采用 Lightweight Proxy Score**（不假装真实 AROS）：用当前价格 + 板块状态 + 资金变化等简化因子合成 `proxy_score`，字段标记 `score_type = "proxy"`。Phase 5 再做真实 Daily Exit Intelligence（每日重跑 Consensus Engine）。

**Layer 4 — 时间退出（实际持有期 = min 取小）**
```
actual_holding_days = min(strategy_max_holding, rating_cap, portfolio_risk_limit)
```
**优先级（拍板）**：`Strategy Exit Rule`（最高）> `Rating Risk Limit` > `Portfolio Risk Limit`。
- 例 A：情绪策略 `max_holding=5`、评级 S(60天) → 取 **5 天**（策略生命周期优先）。
- 例 B：趋势策略 `max_holding=60`、评级 B(15天) → 取 **15 天**（评级风控上限）。

**评级联动上限表（rating_cap）：**
| 评级 | 最大持有 | 止损 |
|---|---|---|
| S | 60 天 | −10% |
| A | 30 天 | −8% |
| B | 15 天 | −5% |
| C | 不进入模拟盘 | — |

## II.5 数据模型

```python
class Portfolio(Base):
    __tablename__ = "portfolios"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)   # e.g. "S1_E1"
    name: Mapped[str]                       # S1 / S2 / S3 / E1 / E2 / E3
    axis: Mapped[str] = mapped_column(String(8))   # selection | exit
    initial_capital: Mapped[float] = 100000.0
    max_positions: Mapped[int] = 5
    position_fraction: Mapped[float] = 0.2
    entry_mode: Mapped[str] = mapped_column(default="immediate")
        # immediate | signal_confirmation | manual  （Phase4.8 Entry 引擎预留接口）
    exit_config_json: Mapped[str]           # ExitConfig 序列化（见下）
    picker: Mapped[str] = mapped_column(default="ai")   # ai | human | random

class SimulatedTrade(Base):
    __tablename__ = "simulated_trades"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id"))
    code: Mapped[str]
    name: Mapped[str | None]
    signal_date: Mapped[date]
    entry_date: Mapped[date]                # = T+1 收盘，无前视
    entry_price: Mapped[float]
    quantity: Mapped[float]
    entry_mode: Mapped[str] = mapped_column(default="immediate")  # 冗余存，便于回查
    score_type: Mapped[str | None]          # "proxy" | None（真实分在Phase5）
    entry_score: Mapped[float | None]       # 入选 AROS Score
    aros_score: Mapped[float]
    rating: Mapped[str]
    hit_strategies_json: Mapped[str | None]
    exit_date: Mapped[date | None]
    exit_price: Mapped[float | None]
    exit_reason: Mapped[str | None]         # stop_loss | take_profit | trailing | score_decay | time_stop | manual
    pnl: Mapped[float | None]
    pnl_pct: Mapped[float | None]
```

`ExitConfig`（可序列化，驱动 E1/E2/E3）：
```yaml
stop_loss:
  mode: fixed          # fixed | atr
  fixed_percent: 8
  atr: { period: 14, multiplier: 2 }
trailing:
  enabled: true
  trigger_profit: 0.15
  drawdown: 0.08
score_decay:
  enabled: true        # E3 开启
  window: 5
  threshold: 70
time_stop:
  from_rating: true    # 用 rating_cap（见 II.4 Layer4）
```

> **账户状态不单独建表**：每日净值 = `cash + Σ(持仓市价)`。现金由「初始资金 − 建仓成本 + 平仓回收」推导；持仓市价由 `PriceProvider` 当日收盘标记。状态可从成交完整重建，无双写漂移。

## II.6 引擎与 CLI

- `simulate_day(session, run_date, price_provider, cfg)`：开仓（受 `entry_mode`/`max_positions` 约束）→ 盯市 → 按 ExitConfig 平仓。
- `portfolio_metrics(session, as_of)` → 净值、累计收益、最大回撤、胜率、盈亏比、平均持仓周期 + **Alpha 指标**。
- `alpha papertrade init --id S1_E1 --axis exit --exit-config <yaml>` / `run --date` / `report [--as-of]`。
- 所有价格依赖 `PriceProvider`（扩展支持可选 `high/low` 供 ATR）；失败降级不编造。

## II.7 组合指标（含 Alpha 指标，Done 标准新增）

| 指标 | 说明 |
|---|---|
| 当前净值 / 累计收益 | 账户演化 |
| 最大回撤 | 峰值到谷值 |
| 胜率 | 盈利交易占比 |
| 盈亏比 | 平均盈利 / 平均亏损 |
| 平均持仓周期 | 已平仓 `(exit−entry)` 交易日均值 |
| **年化收益** | 按交易日折算 |
| **Sharpe** | 收益/波动（为跨策略比较预留） |
| **Calmar** | 年化收益 / 最大回撤 |
| **最大连续亏损次数** | 连续亏损交易计数 |

> 基线对比（推荐）：各组合 vs 同期沪深300 / 买入持有，验证"跟信号是否优于无脑持有"。

## II.8 因果分离（关键）

- 若 4.6 证明 S>A>B>C 单调显著，**但 4.7 的 S1 仍跑不赢 S3（基准）→ 问题在交易规则（退出/仓位），不是评分体系**。
- 若 S1 赢 S3 **但 S2（人工）不如 S1 → 人工干预拖后腿**。
- 这是专业量化系统的问题定位能力。

## II.9 Done 标准（Phase 4.7）

1. 6 组合 schema 就绪，第一阶段 S1+E1/E2/E3 可独立运行、数据隔离。
2. 退出框架三层 + 时间（min 优先级）均被单测覆盖，且**不引用未来价格**。
3. `entry_mode` 字段入 schema（接口预留，引擎不开发）。
4. Alpha 指标计算正确（手算小样例对照）。
5. Portfolio Performance Report 可生成；附带基线对比（样本不足标注）。

---

# Part III — Phase 4.8：执行智能架构占位（Execution Intelligence Design，不开发）

> 本阶段**只做架构设计，不写引擎代码**。目的：冻结接口契约，使 Phase 5 实现时不需大规模迁移（尤其 `entry_mode` 已在 4.7 入 schema）。

## III.1 路线图位置

```
Phase4.6 Calibration → Phase4.7 Paper Trading → Phase4.8 Execution Intelligence Design → Phase5 Execution Engine
```

## III.2 三大引擎冻结定义（来自本设计 §0）

1. **Alpha Selection Engine**（已完成，4.2 共识）：解决"不知道买什么"。
2. **Alpha Execution Engine**（Phase 5）：解决"不会买"。
   - Entry Signal（进场信号）
   - Entry Confidence Score（独立于 AROS Score）
   - Position Size / Timing
3. **Alpha Protection Engine**（4.7 起验证，Phase 5 成熟）：解决"不会卖"。
   - Stop Loss / Take Profit / Trailing / Score Decay
   - 输出 **Exit Signal（带等级）**，非二元"卖"。

## III.3 Entry Engine 设计（重点：合成层，非 follow 原始规则）

**原则（针对 StrategySpec.entry_rules 的澄清）**：
- 收集的策略自带 `entry_rules` 是**参考资料（inputs）**，不是 AROS 的进场指令。
- AROS Entry 引擎 = **合成层**，综合：
  1. **策略组合信号**：命中策略的 entry 语义（突破 / 回踩 / 情绪分歧转一致等）；
  2. **标的当期实况**：价格行为、成交量、相对位置、是否涨停附近（避免追高）；
  3. **市场判断**：regime（Trending/Oscillating/Bear）、板块资金、暗盘派发风险。
- 输出统一的 **Entry Signal + Entry Confidence Score**（"现在是不是适合买？"），与 AROS Score（"值不值得关注？"）解耦。

**Entry Confidence Score 示例**：
- 股票质量 AROS Score = 92（值得研究），但 Entry Score = 60（当前买点一般，等待）。
- 次日价格回踩、量能配合 → Entry Score = 88（条件满足，可模拟进入）。

**按策略族的 Entry Model（Phase 5 实现，4.8 仅占位）**：
- 趋势突破：突破有效 + 放量 + 板块支持 + 环境允许 → 突破确认日。
- 回调低吸：上涨趋势保持 + 回踩支撑 + 缩量 + 重新放量。
- 情绪龙头：分歧转一致（高开承接 + 换手充分 + 板块回流）。

## III.4 Exit Intelligence Engine 设计

- 从 4.7 实证升级为 **Daily Exit Intelligence**：每日重跑 Consensus Engine 得真实 AROS Score，替代 4.7 的 proxy。
- 输出 **Exit Alert（等级 High/Medium/Low）**，原因可解释（逻辑衰减 / 资金转弱 / 跌破趋势）。
- 与 4.7 ExitConfig 兼容：4.7 的 fixed/trailing/score_decay 成为 v1 基线，Phase 5 用真实分驱动 score_decay。

## III.5 Position Management 设计

- 仓位公式：`position_fraction × 当前净值`，留现金缓冲。
- Timing / Rebalancing / 100 股整数倍约束（A 股）—— Phase 5 实现。

## III.6 接口契约（已在 4.7 预留 / 待 Phase 5 落地）

- `Portfolio.entry_mode: immediate | signal_confirmation | manual`（4.7 已落）。
- `SimulatedTrade.entry_score / score_type`（4.7 已落，Phase 5 填真实分）。
- `ExitConfig`（4.7 已落，Phase 5 接真实 score_decay）。
- Phase 5 新增：`EntryEngine.evaluate(code, date, market_state) -> EntrySignal`。

## III.7 4.8 应交付内容（Backlog — 冻结契约，Phase 5 实现）

> **本表即 4.8 的"应含清单"**。4.8 本身只做架构占位、不写引擎代码；下表每一项都是 Phase 5 实现时必须落地、且本设计已冻结契约的内容。立项 Phase 5 时以此表为验收基线，避免遗漏 4.8 的设计意图。

| 模块 | 4.8 必须冻结 / Phase 5 必须交付 | 接口 / 字段（已预留） | 验收标准（不可妥协） |
|---|---|---|---|
| **Entry 合成层** | 综合「策略组合信号 + 标的当期实况 + 市场判断」产出统一 Entry Signal + Entry Confidence Score，与 AROS Score 解耦 | `EntryEngine.evaluate(code, date, market_state) -> EntrySignal` | ① 不复用任一原始策略 `entry_rules`（仅作 inputs）；② 输出含 confidence + 等级；③ 与 AROS Score（值不值得关注）明确分离 |
| **Entry 模型族** | 按策略族实现 Entry Model：趋势突破 / 回调低吸 / 情绪龙头 | — | 每族有可解释触发条件；单测覆盖各族触发/不触发 |
| **Exit Intelligence** | 4.7 proxy → 真实 Daily Exit Intelligence：每日重跑 Consensus Engine 得真实 AROS Score 驱动 score_decay；输出带等级 Exit Alert（High/Medium/Low） | `ExitConfig.score_decay` 接真实分 | ① 与 4.7 fixed/trailing 兼容；② 退出原因可解释（逻辑衰减 / 资金转弱 / 跌破趋势） |
| **Position Management** | 仓位公式 `position_fraction × 当前净值` + Timing / Rebalancing + 100 股整数倍（A 股） | `Portfolio.entry_mode`（immediate / signal_confirmation / manual）生效 | ① 留现金缓冲；② 满足 A 股手数约束；③ 回测可复现 |
| **接口契约落地** | `entry_mode` / `entry_score` / `score_type` / `ExitConfig` 全部填真实值，无 schema 迁移 | 全部已在 4.7 入 schema | Phase 5 不改动 4.7 已落字段结构 |
| **防前视 / 数据隔离** | 沿用 4.6–4.7 约束（无未来函数、配置驱动、离线可测、三个数据域不串） | — | 通过既有四道 CI 门（ruff/black/mypy/pytest） |

**4.8 自身 Done 标准（占位阶段即满足）**：
- 三大引擎定义冻结（§III.2）；
- Entry 合成层原则写清（§III.3，非 follow 原始规则）；
- Exit / Position 设计写清（§III.4 / §III.5）；
- 接口契约列清（§III.6）且字段已在 4.7 落地；
- 本 §III.7 Backlog 评审通过。
- 引擎代码**不在 4.8 写**，统一在 **Phase 5** 实现。

---

## 跨阶段约束（贯穿 4.6–4.8）

- **Anti-Lookahead（无前视）**：所有后验/退出只用决策时已发生的数据；价格取当日收盘，禁用未来高低点择时。
- **配置驱动**：阈值、退出模式、持有期优先级全部可配置，不写死。
- **离线可测**：所有网络（akshare）调用 lazy + guarded，测试注入 fake PriceProvider。
- **数据隔离**：4.6 全量复盘 / 4.7 六组合 / 4.8 不开发，各自数据域不串。

## 统一 Done 标准汇总

| 阶段 | 核心交付 | 硬性判定 |
|---|---|---|
| 4.6 | 评分有效性 + 校准 | CandidatePerformance≥95%；S>A>B>C 严格单调；p<0.05；首校≥60交易日 |
| 4.7 | 退出实验 | S1+E1/E2/E3 可跑且隔离；三层退出+min时间单测覆盖无未来函数；entry_mode 入 schema；Alpha 指标正确 |
| 4.8 | 架构占位 | 三大引擎冻结；Entry 合成层定义；接口契约写清；不写引擎代码 |

## 待拍板 / 已冻结假设

- ✅ 双轴分离、6 组合、第一阶段只跑 S1+E1/E2/E3。
- ✅ ATR 作为可选退出模式，v1 默认 fixed。
- ✅ 持有期优先级 Strategy > Rating > Portfolio（取 min）。
- ✅ Score Decay v1 用 proxy（标记 score_type），Phase 5 上真实分。
- ✅ entry_mode 预留（immediate/signal_confirmation/manual）。
- ✅ Alpha 指标（年化/Sharpe/Calmar/最大连亏）纳入 4.7。
- ✅ 4.8 仅架构占位，Entry 为合成层而非 follow 原始策略规则。
- 开发顺序：先 4.6 → 再 4.7 → 4.8 文档随 4.7 一并评审 → Phase 5 实现。
