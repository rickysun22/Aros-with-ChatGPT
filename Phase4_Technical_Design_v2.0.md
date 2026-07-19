# AROS Phase 4 — Alpha Intelligence System · Technical Design v2.0

> 设计依据：与 GPT 来回讨论形成的 `AROS_Phase4_Alpha_Intelligence_System_v2.md`（目标/原则/知识库/共振评分/资金流/Excel/路线）。
> 本文件是它的**技术落地设计**：把它映射到 AROS 现有架构（Phase 3 资产），补齐 v2 中缺失的执行层（"validated" 策略如何变成可运行的代码、每日筛选的成本与可追溯性），并明确本版**不做**什么。
>
> 红线（沿用 v2，不可突破）：**不接入自动交易、不做黑盒股价预测、不伪造暗盘资金金额**（暗盘只输出行为推断评分+解释）。

---

## 0. 本版范围与明确"不做"

| 项 | 本版 |
|---|---|
| 指标层复盘（OOS / walk-forward / 排名 / 报告） | ✅ 已在 3.3 具备 |
| 视觉层复盘（净值 / 回撤曲线） | ✅ 已在 3.2 复盘层具备 |
| 决策跟踪（系统补后验价、人工填判断/复盘） | ✅ 本版 Sprint 4.5 |
| **逐笔交易明细 / 信号时序 / 单笔归因（trade-blotter）** | ❌ **延后**：用户明确由"上线后自选标的、自行记录"沉淀到个人交易库（4.5）来充实，不在系统自动落库范围 |
| 自动交易 / 下单 | ❌ 永不（v2 红线） |
| 黑盒股价预测 | ❌ 永不（v2 红线 + 3.5 已确立"no AI prediction"） |
| 伪造暗盘资金金额 | ❌ 永不；仅行为推断评分 |

---

## 1. 目标与原则（沿用 v2 + 工程化补充）

闭环：

```text
策略收集 → 回测验证 → 正式策略库(可执行) → 每日多策略筛选
→ 市场/行业/资金验证 → 人工判断(Top 5–10) → 决策跟踪+后验 → 经验沉淀
```

工程化补充原则：
1. **正式库是每日运行的唯一真相源**，且必须是"可执行"的（不仅是文本）。原始池只存想法/规则文本，待实现。
2. **验证做一次，筛选每日做**：策略回测/OOS 验证在 4.1 完成并缓存证据；每日筛选只跑信号+评分，不重跑全样本回测。
3. **每日运行须有界**：在受限 Universe（csi800 / 自选 watchlist）上跑，受 `limit` 约束，复用 3.2 的限流/容错模式。
4. **全链路可追溯**：每个候选必须能回溯到"命中了哪些策略、当时 Regime、资金流快照、验证证据"，落库为 `DailyScreening` + `ScreeningHit`。
5. **共振不是计数**：评分必须加权质量/独立性/Regime 匹配，并对高相关策略去重（见 §4）。

---

## 2. 架构：Phase 4 如何挂到现有 AROS

```text
                         ┌─────────────────────────────────────────────┐
                         │              DataManager (唯一数据入口)       │
                         │  akshare(主) / a.stock-data(兜底) / 资金流 provider│
                         └───────────────┬─────────────────────────────┘
                                         │ get_daily / get_index_daily / get_fund_flow
                         ┌───────────────┴───────────────────────────────┐
        Phase 3 既有资产  │  BatchRunner(3.2) · Scorecard(3.3) ·           │
                         │  Combination(3.4) · MarketRegime(3.5)          │
                         └───────────────┬───────────────────────────────┘
                                         │ 验证证据(ExperimentRegistry)
                         ┌───────────────┴───────────────────────────────┐
        Phase 4 新增      │  4.0 StrategyRegistry(可执行正式库) + RawPool   │
                         │  4.1 ValidationEngine(包裹 BatchRunner+Score)  │
                         │  4.2 ConsensusEngine(命中归集+共振评分)          │
                         │  4.3 MarketContext + MoneyFlow(provider 接口)   │
                         │  4.4 DailyAlphaReport(Excel, openpyxl)          │
                         │  4.5 DecisionTracking + PersonalTradeDB         │
                         └───────────────┬───────────────────────────────┘
                                         │ research alpha daily (新增 CLI)
                         ┌───────────────┴───────────────────────────────┐
                         │  reports/daily_alpha_<date>.xlsx + DB 落库      │
                         └───────────────────────────────────────────────┘
```

关键事实（已核对现有代码）：
- `src/research/strategy_library.py`：10 个策略，类别 `trend`(3) / `strong`(3) / `emotion`(4)，均通过 `register_strategy` 注册，可由名字取 `ResearchStrategySpec`。**这是"可执行策略"的天然注册表**——4.0 直接以它为种子。
- `src/research/batch.py`：`BatchRunner.run` 已支持多策略 × walk-forward × 落库。
- `src/research/scorecard.py`：`Scorecard.score(list[ScoreInput])` 产出 0–100 AROS 评分（截面归一化加权，含 OOS 衰减维度）。
- `src/research/registry.py`：`ExperimentRegistry` 已落库 `metrics` / `equity`；`ExperimentEquity` 存 `{日期:净值}`。
- `src/research/market_regime.py`：5 标签 `Regime` 枚举（`Bull/Neutral/Bear/EmotionHot/EmotionCold`）+ `REGIME_LABELS`；`REGIME_CATEGORY_FIT` 给出"某 Regime 下适配的策略类别"。
- `src/core/database.py`：`Base(DeclarativeBase)` + `get_engine(url)` + `get_sessionmaker(...)`——新表全部继承 `Base`。
- `config/settings.yaml`：已有 `data.start_date=2015-01-01` / `end_date=2026-06-30` / `benchmark.indices` / `research.market_regime`——验证区间与 v2 一致。

---

## 3. 数据模型（新增 ORM，全部继承 `Base`）

> 沿用 `registry.py` 的 ORM 风格（dataclass-like `Base` 子类 + JSON blob 存变长结构）。

### 3.1 Raw Strategy Pool — `raw_strategies`（4.0）
| 字段 | 类型 | 说明 |
|---|---|---|
| `strategy_id` | str, PK | 唯一编号（如 `RAW-2026-0720-001`） |
| `name` | str | 策略名 |
| `source_type` | enum | manual / web / book / paper / other |
| `source` | str | 来源描述/链接 |
| `original_description` | text | 原始描述 |
| `original_rules` | text | 可提取的买卖/过滤/持仓规则 |
| `collected_at` | date | 收集日期 |
| `status` | enum | raw / pending_validation / validated / active / degraded / retired |

> 缺失字段不拒绝入库（v2 原则 2）：`source`/`original_rules` 允许为空，先进 `raw`。

### 3.2 Strategy Registry（可执行正式库）— `strategy_registry`（4.0）
解决 v2 **缺口**：原始池是文本，"validated" 后必须能**运行**。本表把"已验证策略"映射到可执行实现。
| 字段 | 类型 | 说明 |
|---|---|---|
| `strategy_id` | str, PK | 与 `raw_strategies` 或系统内置 id 对齐 |
| `name` | str | |
| `category` | enum | trend / strong / emotion（复用 3.5 类别） |
| `executable_ref` | str | 运行入口：系统内置=`strategy_library` 注册名；外部=模块路径+函数 |
| `status` | enum | validated / active / degraded / retired |
| `validation_run_id` | str, FK→experiment_runs.id | 验证证据（4.1 写入） |
| `quality_star` | float | 验证后质量星级（0–5，由 Scorecard/OOS 派生） |
| `best_fit_regimes` | str(JSON) | 该策略历史表现最好的 Regime 列表（用于 4.2 匹配） |
| `added_at` | datetime | |

**种子**：安装/首次启动时，将 `strategy_library` 的 10 个策略以 `active` 写入本表，`executable_ref`=其注册名，`best_fit_regimes` 由 3.5 `REGIME_CATEGORY_FIT` 推导。

### 3.3 Validation — `strategy_validations`（4.1）
| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | str, PK | |
| `strategy_id` | str, FK | |
| `run_id` | str, FK→experiment_runs.id | 4.1 调 BatchRunner 产生的实验 |
| `metrics_json` | str(JSON) | 统一指标：年化/最大回撤/胜率/盈亏比/交易次数/平均持仓/各 Regime 表现 |
| `oos_json` | str(JSON) | walk-forward OOS 汇总 |
| `status_suggestion` | enum | active / degraded（由阈值规则给出，**仅建议**，不自动启用） |
| `created_at` | datetime | |

### 3.4 Daily Screening — `daily_screenings` / `screening_hits`（4.2）
`daily_screenings`：
| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | str, PK | |
| `run_date` | date | |
| `universe` | str | csi800 / watchlist / … |
| `regime_label` | enum | 当日 Regime |
| `regime_detail_json` | str(JSON) | 分类依据（动量/波动率/宽度），可追溯 |
| `created_at` | datetime | |

`screening_hits`（可追溯核心）：
| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | str, PK | |
| `screening_id` | str, FK | |
| `strategy_id` | str, FK | 命中策略 |
| `code` | str | 候选标的 |
| `signal_date` | date | |
| `quality_star_snapshot` | float | 命中时的质量快照（去重/评分用） |

### 3.5 Daily Alpha Candidate — `daily_alpha_candidates`（4.2/4.4）
每行一只候选，字段对齐 v2 Sheet1：
`screening_id, code, name, industry, sector, concepts(JSON), regime_label,
hit_count, hit_strategies(JSON), avg_quality_star, max_quality_star,
consensus_score, public_money_score, hidden_flow_score, sector_score,
aros_score, rating, advantages, risks, thesis, system_suggestion`。

### 3.6 Decision Tracking + Personal Trade — `decision_tracking` / `personal_trades`（4.5）
`decision_tracking`（对齐 v2 Sheet2）：
`candidate_id(FK), human_decision(关注/买入/放弃/忽略), human_reason,
plan_entry/actual_entry, plan_position/actual_position,
review_date, result_1d/3d/5d/10d, max_float_profit, max_float_loss,
final_return, verified_system(bool), review_summary`。
系统自动补后验价格（按 `code`+日期从 `DataManager` 取），人工只填判断与复盘。

`personal_trades`（**延后的深度复盘落点**）：上线后用户自选标的、自行记录的交易明细
（买卖日期/价/量/持仓/盈亏/备注）。本表是"充实数据库"的载体，**初版仅定义 schema + 录入接口，不做自动撮合/推导**。
字段：`trade_id, code, name, entry_date, entry_price, exit_date, exit_price,
quantity, direction, pnl, pnl_pct, note, source(人工录入), created_at`。

---

## 4. 评分公式（4.2，明确数学 + 去重）

### 4.1 Consensus Score（0–100，候选级）
分量（权重沿用 v2）：命中数量 20 / 策略质量 30 / 策略独立性 20 / Regime 匹配 15 / 板块资金 15。

- **命中数量 `H`**（20）：`20 * min(hit_count, 5) / 5`。
- **策略质量 `Q`**（30）：命中策略 `quality_star` 的均值（0–5）→ `30 * mean_star/5`。
- **独立性 `I`**（20）：先按"相关性去重簇"归并——同一 `(category, 历史收益相关性簇)` 内只保留质量最高者计入质量/独立性，其余仅计入命中数量（防高相关放大）。`I = 20 * (1 - avg_pairwise_corr_among_survivors)`，其中相关性用各策略验证期 OOS 收益序列的 Pearson 相关。`avg_corr` 越低→独立性越高。
- **Regime 匹配 `R`**（15）：当前 `regime_label` 落在命中策略 `best_fit_regimes` 并集 → 15；部分命中 → 按比例；完全不命中 → `15 * 0.3`（仍给基础分，避免硬拒）。
- **板块/资金 `S`**（15）：`sector_score`（个股相对所属板块强弱百分位，0–100）×0.6 + `public_money_score`（板块资金流百分位）×0.4。

`consensus = H + Q + I + R + S`（封顶 100）。

### 4.2 AROS Final Score（0–100，候选最终优先级）
`aros = 0.35*consensus + 0.20*market_sector_env + 0.30*money_flow + 0.15*risk_filter`
- `market_sector_env`：Regime 友好度（Bull=100 / Neutral=70 / Bear=40 / EmotionHot=55 / EmotionCold=30）×0.5 + `sector_score`×0.5。
- `money_flow`：`public_money_score`×0.6 + `hidden_flow_score`×0.4（行为推断，非金额）。
- `risk_filter`：流动性/黑名单/高回撤惩罚后的 0–100（例如 `max_drawdown>40%` 扣 30 分）。

### 4.3 评级（可配置阈值，示例）
`A+ ≥ 85` / `A ≥ 70` / `B ≥ 55` / `C < 55`。系统建议用语：强关注 / 重点观察 / 有研究价值 / 不优先。

> **可解释性**：`daily_alpha_candidates` 同时落库各分量，报告里逐项展示，避免"黑盒分数"。

---

## 5. Sprint 技术设计

### Sprint 4.0 — Strategy Knowledge Base
- **新增**：`src/research/kb.py`（RawPool + StrategyRegistry 管理）、ORM 表 3.1/3.2、`main.py` 下 `research kb` 子命令（`add-raw` / `list` / `promote` / `retire`）。
- **复用**：`strategy_library.list_strategies()` 作为 `active` 种子来源；`REGIME_CATEGORY_FIT` 推 `best_fit_regimes`。
- **验收**：可 `add-raw` 入库；启动时 10 策略自动 seed 为 `active`；`promote` 将 raw→validated 并写入 `strategy_registry`（需先有 `strategy_validations` 记录，故与 4.1 联动）。

### Sprint 4.1 — Validation Engine
- **新增**：`src/research/validate.py`：`ValidationEngine.run(strategy_id)` 调 `BatchRunner`（统一 `2015-01-01~2026-06-30`、统一成本/基准、walk-forward），写 `strategy_validations` + `strategy_registry.validation_run_id` + `quality_star` + `best_fit_regimes` + `status_suggestion`。
- **原则映射**：验证给证据，**不自动决定启用**（v2 §3.2）。`status_suggestion` 仅建议。
- **验收**：一键验证任一策略，产出统一指标+OOS+状态建议，落库可追溯。

### Sprint 4.2 — Multi-Strategy Consensus Engine
- **新增**：`src/research/consensus.py`：`ConsensusEngine.daily(universe, date)` 加载 `active` 策略 → 对每个 `code` 跑当日信号（复用 `run_strategy` 单码信号，不重跑全样本）→ 归集 `screening_hits` → 算 `consensus` + `aros` → 写 `daily_alpha_candidates`（Top 5–10）。
- **复用**：`Scorecard`（质量）、`MarketRegime`（Regime 匹配）、`BatchRunner` 信号产出、`DataManager`（数据）。
- **关键**：相关性去重（§4.1 `I`）用验证期 OOS 收益序列；当日信号计算受 `limit` 限流，复用 3.2 容错。
- **验收**：给定日期+Universe 产出候选排名，每个候选可回溯命中策略与评分分量。

### Sprint 4.3 — Market Context & Money Flow
- **新增**：`src/data/providers/moneyflow.py`（公开资金流：`stock_individual_fund_flow` / `stock_sector_fund_flow` / 行业·概念·板块接口）+ `HiddenFlowProvider` / `SmartMoneyProvider` **接口桩**（仅行为推断，返回评分+解释，绝无金额）。
- **健壮性**：akshare 列名漂移已在 3.2 踩过——本 sprint 的归一化统一走 `provider.py` 的 `_canon_columns` 中英文兼容模式；任何单标的/单板块异常 `except` 跳过并降级评分（不中断整轮）。
- **复用**：`DataManager` 作为入口（新增 `get_fund_flow` / `get_sector_concept` 方法）。
- **验收**：能取个股/板块资金流与行业·概念映射；暗盘 provider 返回"行为推断评分+文字解释"，不出现伪造金额。

### Sprint 4.4 — Daily Alpha Report（Excel）
- **新增**：`src/report/daily_alpha.py`，输出 `reports/daily_alpha_<date>.xlsx`（openpyxl，加入 `requirements.txt`）。
- **Sheet1 Daily Alpha Candidate**：字段见 §3.5（v2 Sheet1）。
- **Sheet2 Decision Tracking**：见 §3.6（v2 Sheet2），系统预填评分/评级/候选快照，人工列留空。
- **验收**：每日运行产出 Excel，两表字段完整、可读性达 v2 要求。

### Sprint 4.5 — Human Feedback Loop
- **新增**：`src/research/feedback.py` + `decision_tracking` / `personal_trades` 表；`research alpha decide` / `research alpha review` 子命令。
- **自动后验**：`review` 时按 `code`+日期从 `DataManager` 自动补 `result_1d/3d/5d/10d`、浮盈浮亏、最终收益。
- **个人交易库**：`personal_trades` 提供录入接口（CLI/导入），**初版仅 schema + 录入，不自动推导**——对应"上线后自选标的自行记录充实数据库"。
- **验收**：可记录人工决定；系统自动补后验；个人交易可录入并查询。

---

## 6. Provider 接口（4.3 预留）

```python
class MoneyFlowProvider(Protocol):
    def get_stock_flow(self, code: str, start, end) -> pd.DataFrame: ...
    def get_sector_flow(self, sector: str, start, end) -> pd.DataFrame: ...
    def get_industry_concept(self, code: str) -> tuple[str, str, list[str]]: ...

class HiddenFlowProvider(Protocol):  # 行为推断，绝不返回金额
    def infer(self, code: str, prices: pd.DataFrame, flows: pd.DataFrame) -> HiddenFlowSignal:
        """返回 HiddenFlowSignal(score: float, explanation: str)，纯行为推断。"""
```

`HiddenFlowSignal` 仅含 `score`(0–100) 与 `explanation`（如"低波横盘放量抗跌→潜在承接"），无金额字段——守住 v2 红线。

---

## 7. Excel Schema（4.4，对齐 v2）

- **Sheet1**：日期/代码/名称/行业/板块/概念/Regime/命中套数/命中策略/平均星级/最高星级/共振评分/公开资金/隐性行为/板块强度/AROS/评级/优势/风险/Thesis/系统建议/人工判断/跟踪状态。
- **Sheet2**：候选日期/代码·名称/系统评分·评级/人工决定/人工理由/计划·实际入场价/计划·实际仓位/复盘日期/1·3·5·10日结果/最大浮盈·浮亏/最终收益/是否验证系统/复盘总结。

---

## 8. 可追溯性与延后项

- **可追溯**：`DailyScreening` → `ScreeningHit`（命中策略+质量快照）→ `strategy_validations`（证据）→ `daily_alpha_candidates`（评分分量）→ `decision_tracking`（人工+后验）。任一候选可完整还原"为何入选"。
- **延后（用户决策）**：逐笔交易明细 / 信号时序 / 单笔归因（trade-blotter）不在初版；上线后由用户经 `personal_trades` 自行记录，反向充实数据库。初版系统"复盘"= 指标层 + 净值/回撤曲线 + 决策跟踪后验。

---

## 9. 质量、风险与首切建议

- **CI**：沿用四门禁（ruff / black / mypy / pytest）；每个 Sprint 配套单测（含离线 fake DataManager，不触网）。
- **风险**：
  1. akshare 资金流/板块接口偶发限流或列漂移 → 全链路 `except` 降级 + 复用 `_canon_columns`。
  2. 每日全 Universe 成本 → 限 Universe + `limit` + 信号级（非回测级）计算。
  3. 共振分数可解释性 → 各分量落库，报告逐项展示。
- **建议首切**：**先做 4.0 + 4.1**（数据模型 + 验证引擎），因为它是 4.2–4.5 的依赖根；4.0 把现有 10 策略 seed 为 `active` 后可立刻用 4.1 产出验证证据，形成"知识库可用"的最小闭环，再逐 sprint 向上叠。
- **调度**：`research alpha daily` CLI 提供完整单次运行；cron/任务计划程序调度属运维范畴，本设计不内置，但输出与落库均为幂等可重跑。

---

## 10. 开放问题（待你/后续确认）

1. 每日筛选的默认 Universe：`csi800` 还是固定 watchlist？是否允许用户维护自选池？
2. `quality_star` 由 OOS Sharpe 还是 `Scorecard` 总分派生？阈值如何定？
3. 暗盘行为推断的代理信号权重是否要可配置？
4. Excel 之外是否需要同样内容的 Markdown/HTML 报告（复用现有 report 引擎）？
