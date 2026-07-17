# AROS Phase 3 — Alpha Research / Strategy Discovery（技术设计冻结版）

> 状态：**🟢 Design Approved（设计已批准 · 冻结）** · ChatGPT PASS 于 2026-07-17
> 版本：v1.0 · 2026-07-17（基于 GPT 评审意见 v0.1 → v1.0）
> 输入文档：《AROS Phase 3: Alpha Research Strategy Plan》（用户提供）
> 本文档职责：把用户的路线图落到 **AROS 已实现的真实能力** 上，冻结三件事——
> **Strategy Contract（策略契约）/ Evaluation Standard（评价标准）/ Research Workflow（研究流程）**。
> 本阶段**不写任何策略代码**。

---

## 0. TL;DR（一页读懂）

- **目标**：把 AROS 从「研究平台」升级为「策略发现系统」，最终回答——
  *「若明天开始做 A 股短线，历史数据证明哪套（或哪组）策略最值得用？」*
- **交付**：《AROS A 股短线策略研究报告 V1.0》——10+ 策略的收益/胜率/回撤/持仓周期 + AROS Strategy Score 排名 + 最优（单/组合）方案。
- **纪律**：可解释、可回测、可复现、可比较、可实盘执行；**禁止** 深度学习预测、黑盒、过拟合、未来函数、数据泄露。
- **三条必须先冻结的红线约束**（见 §2）：
  1. **数据只有日线**——无分钟/tick。超短情绪类策略只能做「日线粒度事件研究」，不能建模分时打板。
  2. **回测是 Top-N 组合再平衡**——不是逐笔止盈止损的事件驱动引擎。短线策略需要新的执行抽象（Sprint 3.0 交付）。
  3. **无券商接口**——「可实盘执行」= 引擎能每日复现产出可执行信号清单，**不含真实下单**。

---

## 1. 现状盘点（已核实，非假设）

Phase 1 + Phase 2 已全部落地 `main`，四门禁全绿（ruff/black/mypy/pytest 229 passed）。下表是 Phase 3 **可直接复用、不重复造轮子** 的能力清单，每项均已在代码中核实。

| 层 | 模块 / 文件 | 可复用的公共入口 |
|----|-----------|------------------|
| 数据 | `src/data/manager.py` `DataManager` | `get_daily(code, start, end, as_of)`、`get_index_daily(...)`；provider = AKShare + astockdata 兜底；**仅日线** |
| 指标 | `src/indicators/` | MA/EMA/RSI/MACD/KDJ/BOLL/VOL_MA，配置驱动（`indicators.enabled`） |
| 因子 | `src/factors/impl.py` | 8 因子：`ma_distance / ma_cross / rsi_signal / macd_cross / kdj_cross / vol_ratio / boll_position / momentum`（`factors.enabled`） |
| 策略 | `src/strategies/impl.py` | `BaseStrategy` + 注册表；**仅 `weighted` / `rule` 两类**（截面打分 → `score_<name>` / `signal_<name>`） |
| 回测 | `src/backtest/` | `CostModel`（佣金/最低佣金/印花税/过户费/滑点全可配）、`compute_metrics(...)`、**`PortfolioBacktest`（Top-N 等权再平衡 vs 买入持有）** |
| 指标库 | `src/backtest/metrics.py` | `total_return, cagr, max_drawdown, sharpe, sortino, win_rate, num_trades, turnover, benchmark_return, profit_factor, calmar, avg_holding_days, max_consecutive_losses, exposure` |
| 实验 | `src/research/` | `ExperimentConfig`（冻结 schema）、`ResearchRunner.run(...)`、`WalkForwardRunner.run(...)`、`ExperimentRegistry`（create/record_metrics/record_equity/mark_done/**load_result**/list/get/delete）、`BenchmarkEngine.compare(...)` |
| 报告 | `src/research/report.py` | `ResearchReport.to_markdown/to_json/to_html`、`render_experiment_report`；`DailyReport`（`src/report/engine.py`）内联 CSS+SVG 风格 |
| 调度 | `src/scheduler/` | `Scheduler`（run_ntimes/run_loop）+ `Notifier`（console/file/webhook）；**当前只推报告，不出交易信号** |

**`ExperimentConfig` 冻结字段**（可复现单元，Phase 3 直接沿用）：
`name, strategy, start, end, universe | codes(互斥), benchmark(默认 csi300), metrics, walk_forward(train/test/step 年), seed`。

---

## 2. 三条红线约束与应对（设计核心）

Phase 3 的成败取决于是否诚实处理下面三个 gap。**每个 gap 都有对应的应对方案，不回避、不假装。**

### 约束 A — 数据只有日线（无分钟/tick）

- **影响**：用户 10 套里的「首板 / 二板接力 / 连板博弈 / 情绪冰点」本质是情绪+分时驱动，真实打板需要分时数据。
- **应对**：
  - **可做**：涨停/连板/新高/放量 等事件 **完全可从日线判定**（`close ≥ prev_close × (1+涨停幅)`，主板 10% / 创业科创 20% / ST 5%）。因此这些策略以「**日线粒度事件研究**」形式落地——信号在 T 日收盘确认，**T+1 开盘买入**、按持仓周期或止盈止损在收盘平仓。度量的是「事件后的次日/多日溢价」，这是可复现、可回测的。
  - **不可做（明确排除，不做假动作）**：分时打板时点、集合竞价撬板、盘中止损。这些标注为 *needs intraday data*，留到未来「数据能力 Sprint」（Phase 3+ 或 Phase 4），不纳入 V1.0。
  - **交付物如实标注**每套策略的「数据粒度可信度」：日线可完整建模 / 日线近似 / 需分时（暂缺）。

### 约束 B — 回测是组合再平衡，不是事件驱动

- **影响**：现有 `PortfolioBacktest` 是「每期取 Top-N 等权持有」，无法表达「单标的入场→持有 1–5 日→触发止盈/止损/到期离场」这种短线逐笔逻辑。
- **应对**：**Sprint 3.0 交付一个事件驱动回测适配层**（不推翻现有组合回测，二者并存）：
  - 新增 `EventBacktest`（工作名）：输入 = 每标的的 **入场信号序列 + 出场规则（stop_loss / take_profit / max_holding_days）**，输出 = 逐笔 trades + equity，**复用现有 `CostModel` 与 `compute_metrics`**（不新增指标数学）。
  - 通过 `ResearchRunner` 的注入缝（现有 `portfolio_fn` 注入模式）接入，使 `ExperimentConfig` 既能跑组合回测、也能跑事件回测。
  - 这样趋势/强势类（偏组合）走 `PortfolioBacktest`，情绪/超短类（偏逐笔）走 `EventBacktest`，**但二者产出同一套 metrics，可公平比较**。

### 约束 C — 无券商 / 实盘接口

- **影响**：用户要求「可实盘执行」。
- **应对**：Phase 3 把「可实盘执行」定义为 **信号可复现产出**——
  - 引擎能对「今天」跑出每套策略的 **可执行信号清单**（买入代码 / 建议仓位 / 出场规则），并经 `Scheduler + Notifier` 每日推送。
  - **真实下单（券商 API 对接）显式排除在 Phase 3 之外**，作为独立的 Phase 4「Execution」工作流。V1.0 报告只回答「该用哪套策略」，不接管账户。

---

## 3. Strategy Contract（策略契约 · 待冻结）

所有策略必须实现同一契约，才能被 **批量回测 + 公平比较**。契约同时兼容现有 `weighted`/`rule` 与新增的事件型策略。

```yaml
Strategy:
  name:            str          # 唯一标识，如 "longtou_shouyin"
  display_name:    str          # 中文名，如 "龙头首阴"
  category:        enum         # trend | strong | emotion   （趋势 / 强势 / 超短情绪）
  engine:          enum         # portfolio | event          （决定走哪套回测）
  universe:        enum         # csi800 | all_a | custom     （绑定的股票池，D7 在 3.0 冻结）
  description:     str          # 一句话逻辑
  holding_period:  {min:int, max:int}   # 持仓天数区间（日线）
  entry_rules:     [rule...]    # 入场条件（引用因子/指标列 + 事件判定）
  exit_rules:                   # 出场规则（事件型必填）
    stop_loss:     float        # 例 -0.05
    take_profit:   float        # 例 0.10
    max_holding_days: int
  parameters:      {k: v}       # 全部可调参数（含默认值），供 3.x 敏感性分析
  risk_control:                 # 硬性风控
    max_position_per_name: float
    max_positions:         int
  data_fidelity:   enum         # daily_full | daily_approx | needs_intraday（如实标注，见约束A）
```

**冻结要点：**
- **D1** — `category` 三分类固定为 `trend / strong / emotion`（对应用户三大类）。
- **D2** — `engine` 二选一 `portfolio / event`，由策略性质决定，二者产出统一 metrics。
- **D3** — 每套策略必须声明 `data_fidelity`，`needs_intraday` 的策略在 V1.0 中标注「结论仅供参考」。
- **D4** — 策略参数与 `ExperimentConfig` 一一映射，保证 config 可完整 round-trip、可复现（沿用 2.0 冻结 schema）。
- **D5** — 契约以 Pydantic 模型落地于 `src/research/strategy_spec.py`（新增，Sprint 3.0），不改动 2.0 的 `ExperimentConfig`。

---

## 4. Evaluation Standard —— AROS Strategy Score（待冻结）

不能只看收益。综合评分把用户给的权重映射到 **已实现的 metric keys**（无新增指标数学，仅做归一化与加权）。

| 维度 | 权重 | 映射到 metric key | 归一化方向 |
|------|-----:|-------------------|-----------|
| 收益率 | 20% | `total_return` | 越大越好 |
| 年化收益 | 15% | `cagr` | 越大越好 |
| 胜率 | 20% | `win_rate` | 越大越好 |
| 最大回撤 | 20% | `max_drawdown` | 越小越好（取绝对值反向） |
| 盈亏比 | 10% | `profit_factor` | 越大越好 |
| 稳定性 | 10% | `sharpe`（辅以 walk-forward IS/OOS 衰减） | 越大越好 |
| 持仓体验 | 5% | `avg_holding_days` + `max_consecutive_losses` | 越小越好 |

**评分算法（冻结）：**
- **E1 — 截面归一化**：对参与比较的策略集合，每个维度做 min-max 归一到 [0,1]（反向指标先取相反数）。避免量纲不可比。
- **E2 — 加权求和**：`score = Σ (weight_i × normalized_i) × 100`，输出 0–100。
- **E3 — 稳定性加惩罚**：利用 2.5 的 walk-forward `is_agg`/`oos_agg`，若 OOS 相对 IS 衰减过大（如 sharpe 衰减 > 50%），对稳定性维度打折——**这是防过拟合的关键**。
- **E4 — 评分可复现**：评分器是 `ExperimentResult` 列表的纯函数，落地于 `src/research/scorecard.py`（新增），有单测锚定手算值。
- **E5 — 权重可配**：权重写入 `config/settings.yaml` 的 `research.scorecard`，改配置不改码。

**输出样例（格式冻结，数字为示意）：**

| 策略 | 收益 | 胜率 | 回撤 | 持仓 | OOS衰减 | 评分 |
|------|-----:|-----:|-----:|-----:|--------:|-----:|
| 龙头首阴 | 220% | 63% | 15% | 3天 | 低 | 92 |
| 趋势突破 | 180% | 58% | 20% | 10天 | 中 | 85 |
| 首板 | 350% | 48% | 40% | 1天 | 高 | 78 |

---

## 5. Research Workflow（研究流程 · 可复现管道）

Phase 3 全程复用 Phase 2 引擎，**不新建平行流程**：

```
Strategy Contract (yaml)                     ← 3.0 冻结
        ↓  build
Strategy Library (10+)                       ← 3.1，注册进 StrategyEngine / EventBacktest
        ↓  ExperimentConfig（统一池/区间/资金/费率/benchmark）
Batch Runner                                 ← 3.2，遍历策略 × 市场区间
        ↓  ResearchRunner.run / WalkForwardRunner.run
ExperimentRegistry（落库，每策略一 run_id）   ← 复用 2.4/2.5
        ↓  registry.load_result
Scorecard（AROS Strategy Score）             ← 3.3，纯函数评分 + 排名
        ↓
Strategy Combination（分市场环境配权）        ← 3.4
        ↓
Market Regime Engine（动态选策略，高级）      ← 3.5
        ↓  ResearchReport.to_html/md
《AROS A股短线策略研究报告 V1.0》
```

**统一实验基准（冻结，保证公平比较）：**
- 区间 `2015-01-01 ~ 2026-06-30`（覆盖牛/熊/震荡/极端）。
- 统一股票池规范于 **Sprint 3.0 冻结**（见 D7）：每套策略在其 `StrategySpec` 中绑定 `universe`（如 `csi800` / `all_a` / 显式代码池），趋势/强势类默认中证 800，情绪/首板类用全 A；**禁止未来成分**（见 D6 幸存者偏差防护）。统一初始资金 `1,000,000`、统一 `CostModel`（万 2.5 佣金 / 万 5 印花 / 万 0.1 过户 / 滑点可配）、统一 benchmark `csi300`。
- 所有策略走 walk-forward（IS/OOS）验证，**排名以 OOS 表现为主**，杜绝样本内过拟合。

---

## 6. Sprint 分解（3.0 → 3.5）

> 每个 Sprint 沿用既有纪律：**设计 → 冻结 → 实现 → 四门禁全绿 → 提交推送 → 更新 CHANGELOG/Roadmap**。

**Sprint 编号约定（避免 GitHub Roadmap 混淆）**：Phase 2 = 2.0–2.6（已完结），Phase 3 自 3.0 起，**`3.0 = Strategy Research Framework（研究框架）`、`3.1 = Strategy Library（策略库）`**，其后 3.2–3.5 顺延；Roadmap / CHANGELOG 一律以 `Phase N.M` 命名。

### Sprint 3.0 — Strategy Research Framework（基础，最关键）
- **交付**：`StrategySpec`（§3 契约 Pydantic 模型，`src/research/strategy_spec.py`）——含每策略绑定的 `universe` 字段（D7）；`EventBacktest` 事件驱动回测（`src/backtest/event.py`，复用 `CostModel`+`compute_metrics`）；`Scorecard` 骨架（`src/research/scorecard.py`）；**统一股票池规范冻结**（D7：历史时点成分、禁未来成分）与评分权重写入 `settings.yaml`。
- **不含**：任何具体策略。只建标准与地基。
- **测试**：契约校验、事件回测逐笔正确性 + 无未来函数（T 日信号 T+1 执行）、评分手算锚定。

### Sprint 3.1 — Strategy Library（10+ 策略）
- 按 §7 目录、以**数据可信度分批**实现共 10 套，每套一个 `StrategySpec` + 注册。
- 开发顺序（**D8，可信度降序**）：批次 1（日线完整建模 均线多头/新高突破/放量突破/强势回踩/龙头首阴）→ 批次 2（日线近似 缩量反包/首板/二板接力）→ 批次 3（可信度最低 连板博弈[needs_intraday，仅供参考] / 情绪冰点修复）。
- 测试：每套至少 1 个信号正确性用例 + 1 个无泄漏用例。

### Sprint 3.2 — Batch Strategy Experiment
- `BatchRunner`：遍历 策略 × 已在 3.0 冻结的 `ExperimentConfig`（池/区间/资金/费率/benchmark），全部走 walk-forward，落库。
- 切分市场子区间（牛/熊/震荡/极端）做分段稳健性分析。
- 测试：批量跑通、结果可 `load_result` 复现。

### Sprint 3.3 — Strategy Evaluation & Ranking
- `Scorecard` 完整实现 §4 评分 + 排名，含 OOS 衰减惩罚。
- 输出排名表（md/json/html），接入 `ResearchReport`。
- 测试：评分/排名手算锚定、反向指标方向正确。

### Sprint 3.4 — Strategy Combination
- 分市场环境的策略配权研究（趋势市 vs 震荡市）；组合 equity 聚合复用现有指标。
- 测试：组合权重归一、组合 metrics 可复现。

### Sprint 3.5 — Market Regime Engine（高级）
- 市场环境分类器：`Bull / Neutral / Bear / EmotionHot / EmotionCold`，**基于可解释规则**（指数均线结构、涨停家数、波动率），非黑盒模型。
- 按环境动态选策略；输出最终《V1.0 报告》。
- 测试：分类规则确定性、无未来函数。

---

## 7. Strategy Library 目录（10 套 · 按数据可信度分批 · 可行性已标注）

> **开发批次（D8，可信度降序）**：批次 1 = 日线完整建模；批次 2 = 日线近似；批次 3 = 可信度最低（含 `needs_intraday` 仅供参考）。批次 1/2 优先于 3.1 主体实现，批次 3 中的 `needs_intraday` 策略结论仅作参考。

| 批次 | # | 策略 | category | engine | universe | 数据可信度 | Phase3 建模方式 |
|------|---|------|----------|--------|---------|-----------|----------------|
| **1** | 1 | 均线多头 | trend | portfolio | csi800 | daily_full | MA 多头排列 + 趋势确认 + 量能过滤 |
| **1** | 2 | 新高突破 | trend | event | csi800 | daily_full | N 日新高 + 放量，T+1 入场，止盈止损离场 |
| **1** | 3 | 放量突破 | trend | event | csi800 | daily_full | 突破 + `vol_ratio` 阈值，研究资金持续性 |
| **1** | 4 | 强势回踩 | strong | event | csi800 | daily_approx | 强涨→缩量调整→再启动（回踩均线低吸） |
| **1** | 5 | 龙头首阴 | strong | event | csi800 | daily_approx | 强趋势后首个阴线低吸（日线近似，无分时） |
| **2** | 6 | 缩量反包 | strong | event | csi800 | daily_approx | 洗盘缩量后反包阳线介入 |
| **2** | 7 | 首板 | emotion | event | all_a | daily_approx | 涨停日判定（日线可判），研究**次日开盘溢价** |
| **2** | 8 | 二板接力 | emotion | event | all_a | daily_approx | 连板判定，次日接力收益（日线粒度） |
| **3** | 9 | 连板博弈 | emotion | event | all_a | needs_intraday | 高度板生命周期——**分时缺失，V1.0 标注仅供参考** |
| **3** | 10 | 情绪冰点修复 | emotion | event | all_a | daily_approx | 极端情绪（跌停家数/指数超跌）后反弹 |

> 涨停/连板判定在日线上可实现（收盘价对比 + 板制幅度规则）；**分时打板时点不可建模**，第 9 套明确标注数据受限。
> `universe` 随策略绑定（D7）：趋势/强势类用 `csi800`，情绪/首板类用 `all_a`（全 A 才有完整涨停样本），均在 Sprint 3.0 冻结。

---

## 8. 必须遵守的原则（不可协商）

**禁止**：❌ 深度学习预测股价 · ❌ 黑盒模型 · ❌ 过度参数优化（以 walk-forward OOS 为准绳） · ❌ 未来函数 · ❌ 数据泄露。
**必须**：✅ 可解释 · ✅ 可回测 · ✅ 可复现 · ✅ 可比较 · ✅ 可实盘执行（= 信号可复现产出）。
**量化风险防护（新增 · D6）**：✅ **禁止幸存者偏差**——股票池必须取**历史时点成分**（回测当日实际可交易标的），**严禁使用「未来成分 / 当前指数成分回看历史」**；A 股 2015–2026 须显式处理 ST、退市、成分调整，否则回测收益会被幸存标的系统性高估。
**工程纪律**：所有参数配置化；每模块四门禁（ruff/black/mypy/pytest）；无未来函数由自动化截断测试保证；Sprint 仅在 ChatGPT PASS 后推进。

---

## 9. 最终交付物与成功标准

- **交付物**：《AROS A 股短线策略研究报告 V1.0》——10+ 策略的收益/胜率/回撤/持仓周期、AROS Strategy Score 排名、每套策略的适用市场/优势/风险、最优单策略或组合方案。
- **成功标准**：AROS 能给出有历史数据支撑、可复现、可解释的答案——
  *「若明天开始做 A 股短线，哪套（或哪组）策略最值得使用」*。

---

## 10. 冻结决策汇总（D1–D8 + E1–E5 · 全部通过 🟢）

| 编号 | 决策 | 建议默认 / 结论 |
|------|------|---------|
| D1 | category 三分类 | trend / strong / emotion |
| D2 | engine 二类 | portfolio / event，产出统一 metrics |
| D3 | 数据受限策略处理 | 声明 `data_fidelity`，`needs_intraday` 标注仅供参考 |
| D4 | 策略参数 ↔ ExperimentConfig 映射 | 沿用 2.0 冻结 schema，不改动 |
| D5 | 契约落地位置 | 新增 `src/research/strategy_spec.py` |
| **D6** | **幸存者偏差防护** | 股票池取**历史时点成分**，禁未来成分；显式处理 ST/退市/成分调整 |
| **D7** | **统一股票池规范冻结于 3.0** | 每策略 `universe` 绑定 `StrategySpec`（csi800 / all_a / custom）；趋势·强势=csi800，情绪·首板=all_a |
| **D8** | **策略开发顺序按数据可信度** | 批次 1（均线/突破/放量突破/强势回踩/龙头首阴）→ 批次 2（缩量反包/首板/二板）→ 批次 3（连板博弈[参考]/情绪冰点） |
| E1–E5 | 评分归一化/加权/OOS 惩罚/可配/纯函数 | 见 §4 |
| — | 市场区间切分 | 牛/熊/震荡/极端子区间（3.2 执行） |
| — | 事件回测 T+1 执行 & 止盈止损语义 | T 日收盘信号，T+1 开盘入场；止损/止盈/到期收盘离场 |

> **🟢 AROS Phase 3 Technical Design — PASS（ChatGPT 评审通过，2026-07-17）。**
> D1–D5 原提案全部通过；新增 **D6（幸存者偏差防护）、D7（3.0 冻结股票池规范）、D8（按数据可信度排序开发）**。
> 方向正确，可开工：**先 Sprint 3.0（StrategySpec + EventBacktest + Scorecard 骨架 + 股票池规范冻结），再进 3.1 写第一批策略。**
