# AROS Phase 5 — Intelligent Platform（智能化平台阶段）设计 / 前瞻

> 状态：**设计占位（Backlog / 前瞻），不开发引擎代码**
> 关联：`Phase4.6-4.8_Technical_Design.md`（交易智能核心，4.6–4.8 已定稿）
> 文档性质：Phase 5 的范围契约与验收基线。Phase 5 在 Phase 4 完成后启动。

---

## 0. 为什么需要 Phase 5

Phase 4（4.0–4.8）已打通"从发现到退出的研究闭环"：

- **Discovery**（4.0–4.6）：策略库 → 验证 → 共识选股 → 市场/资金 → 每日候选 → 人工反馈 → 评分校准。
- **Entry**（4.7）：Entry Score 合成层（"什么时候买"），模拟交易验证环境支撑。
- **Exit**（4.8）：分级 Exit Signal（"什么时候卖"），退出框架 v1.0 已在验证环境实现。
- **Management**：仓位 / 移动止盈 / 100 股整数倍，在 4.7 验证环境落地，组合层待成熟。

Phase 5 **不再开发交易逻辑**——核心能力已在 Phase 4 完成。Phase 5 把能力**产品化 / 自动化 / 智能增强**，把 AROS 从"选股系统"真正做成 **AI 辅助投资决策系统**。

---

## 1. 三大核心评分（贯穿每日决策）

Phase 5 的日常产物是三个互相解耦的评分，对应交易生命周期的三次决策：

| 评分 | 回答的问题 | 来源 | 阶段 |
|---|---|---|---|
| **Alpha Score** | 值不值得研究？ | 现有 AROS Consensus Score（4.2） | 已完成 |
| **Entry Score** | 现在是否适合买？ | 4.7 Entry 合成层（策略组合 + 标的当期实况 + 市场判断） | 4.7 实现 |
| **Exit Score / Exit Risk** | 是否应该离场？ | 4.8 Daily Exit Intelligence（真实 AROS Score + 价格/资金流） | 4.8 实现 |

**最终每日形态示例**：
```
XX科技
  Alpha Score : 92  ⭐⭐⭐⭐⭐
  Entry Score : 86
  Exit Risk   : Low
  → 建议：关注买入

XX科技（持仓）
  Alpha Score : 95
  Exit Risk   : High
  → 建议：减仓 / 退出
```

---

## 2. Phase 5 范围（5.1 – 5.5）

### 5.1 Dashboard（Web 仪表盘）
把现有的 Excel / HTML 报告升级为 **Web Dashboard**：
- 每日：市场状态（regime）、候选股票、策略命中分布。
- Entry 状态：待买 / 已触发 / 观望（Entry Score 面板）。
- Exit 状态：持仓风险分级（High/Med/Low）、触发原因。
- 模拟盘（Paper Trading 验证环境）一览：净值曲线、Alpha 指标、基线对比。
- 技术：复用现有 `DailyAlphaReport` / `generate_papertrade_report` 的渲染层，前端自包含离线优先。

### 5.2 AI Research Assistant（AI 研究员）
让 AI 成为"研究员"，自然语言问答，基于 4.5 反馈库 + 4.6 校准库：
- 示例："近三个月 S 级股票表现如何？" → 出现次数 / 胜率 / 最大收益 / 失败原因归因。
- 输入：结构化数据库（候选、后验、决策、校准）+ 设计文档（RAG）。
- 输出：可解释的研究结论，引用具体标的与时间段，不编造数字。
- 复用 Phase 4 的 `post_hoc` / `calibration` / `feedback` 数据层。

### 5.3 Strategy Discovery Engine（自动策略发现）
- AI 主动扫描：研报 / 论坛 / 公开策略 / 学术论文。
- 提取结构化策略规则（映射回 `StrategySpec`）。
- 进入 4.1 验证（OOS Composite + 否决项）→ 4.2 共识 → 形成**自动进化策略库**。
- 与 4.0 `kb.py` 打通：新策略经验证后 seed 为 `active`。

### 5.4 Adaptive Weighting（自适应权重）
- 动态调策略权重，响应市场状态：
  - 例：趋势策略历史贡献 70%；市场进入震荡 → 降趋势权重、提套利 / 低波策略。
- 复用 3.4 `CombinationEngine` 的分环境配权，升级为"在线自适应"（按滚动 OOS 表现调整）。
- 约束：权重归一、可解释、可回测复现。

### 5.5 Risk Management（组合层风险管理）
- **Alpha Management Engine 的组合层成熟**：
  - 仓位（已有 `position_fraction` 基础）。
  - 行业集中度上限。
  - 风险预算（Risk Budgeting）。
  - 持仓相关性（降低同向暴露）。
- 与 4.8 退出框架协同：个股 Exit Signal + 组合层风控共同决定加减仓。

---

## 3. 接口与数据依赖（复用 Phase 4）

| Phase 5 能力 | 复用 Phase 4 |
|---|---|
| 5.1 Dashboard | `DailyAlphaReport` / `generate_papertrade_report`（md/html/xlsx）→ Web |
| 5.2 AI Assistant | `feedback.py`（决策/复盘）+ `calibration.py`（候选表现/校准）+ 设计文档 RAG |
| 5.3 Strategy Discovery | `kb.py` / `validate.py` / `consensus.py`（自动 seed + 验证 + 共识） |
| 5.4 Adaptive Weighting | `CombinationEngine`（分环境配权 → 在线自适应） |
| 5.5 Risk Management | `papertrade.py` 账户重建 + `ExitConfig`（组合层叠加） |

**无 schema 迁移**：Phase 4 已落的 `entry_mode` / `entry_score` / `score_type` / `ExitConfig` / `Portfolio` / `SimulatedTrade` 直接支撑 Phase 5。

---

## 4. Phase 5 Done 标准（前瞻）

- 5.1：Web Dashboard 可展示每日候选 / Entry / Exit / 模拟盘，离线可用。
- 5.2：自然语言问答可基于真实库回答，引用具体标的与时间段，不编造。
- 5.3：AI 提取的策略规则可经 4.1 验证并自动入库（端到端跑通至少一条）。
- 5.4：权重随市场状态自适应调整，且调整可解释、可回测复现。
- 5.5：组合层风控（行业集中 / 风险预算 / 相关性）上线并与个股 Exit 协同。
- 全部通过既有四道 CI 门（ruff / black / mypy / pytest）。

---

## 5. 与 Phase 4 的边界

- Phase 4 = **交易逻辑闭环**（发现→买入→持有→卖出）。
- Phase 5 = **平台与智能增强**（展示、问答、自动发现、自适应、组合风控）。
- 若 Phase 5 发现 Phase 4 某引擎能力不足（如 Entry Score 合成层需更强模型），回 Phase 4 对应阶段迭代，不在 Phase 5 重新发明交易引擎。
