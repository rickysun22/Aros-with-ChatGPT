# Changelog

All notable changes to AROS are documented by Sprint.

## Phase 4.9 — Daily Operational Loop (`run_daily` + disk cache) (2026-07-20)

> Closes the gap between "parts that run" and "a system that runs". Wires the
> already-built 4.2/4.4/4.5/4.6/4.7/4.8 engines into one idempotent, unattended
> daily pass so real out-of-sample evidence starts accruing (the constitution's
> anti-overfit / no-look-ahead guarantees only matter once data exists).

### Daily orchestrator (`src/research/run_daily.py`, new)
- `run_daily(session, run_date, deps)` runs one idempotent per-date pass:
  1. seed KB (4.0) → 2. incremental data sync → 3. consensus screen (4.2)
  → 4. daily report xlsx/html/md (4.4) → 5. calibration performance fill (4.6)
  → 6. human-decision post-hoc fill (4.5) → 7. optional paper-trading sim
  (4.7/4.8) → 8. checkpoint validation report at `auto_validate_at` trading days.
- `catch_up(session, since, until, deps)` backfills every missing trading day
  (self-heals missed scheduled runs). Both skip work already done for a date, so
  re-running is a safe refresh — no duplicate candidates.
- All network-bound deps are injected via `RunDeps` (money-flow / price /
  benchmark / score providers, `screen_fn`, `sync_fn`), so the loop is fully
  offline-testable; production builds cached, real AKShare-backed providers.

### Disk cache (`src/data/cache.py`, new)
- `DayCache` (TTL, pickle) + `CachedMoneyFlowProvider` / `CachedHiddenFlowProvider`
  / `cached_daily_price_provider` throttle the ~100 daily network calls the design
  flagged (money-flow providers + repeated price windows). Cache is best-effort:
  a write/parse failure never breaks a run; a TTL miss == a normal miss.

### Shared score provider
- `consensus_score_provider(session)` added to `research/exit.py`; returns the real
  AROS read for the 4.8 Exit Engine. Reused by `run_daily` and the `alpha exit eval`
  CLI (removed the duplicated local copy in `main.py`).

### CLI (`main.py`)
- `research alpha run [--date --universe --limit --regime --no-money-flow
  --no-papertrade --no-sync --auto-validate-at --cache-dir --report-dir]` runs the
  full loop for one date (idempotent). Schedule it daily via OS Task Scheduler /
  cron.
- `research alpha catch-up --since … [--until …]` backfills missing trading days.

### Full A-share universe (`all_a`)
- New universe type `all_a` = the **whole A-share market** (~5300 codes), resolved
  from the persisted `Stock` table (populated by `DataManager.sync_stock_list()`)
  rather than a curated index subset. Contrast with `csi800` (~688 constituents),
  which is a CSI 800 index subset, not the full market.
- `research/universe_provider.py`: new `AllAProvider` + `all_a` branch in
  `get_universe_provider`, so the 4.2 consensus screen can target the whole market.
- `universe/engine.py`: `UniverseEngine.get_codes("all_a")` special-cases to read the
  `Stock` table, keeping `report` / `portfolio` / `universe show` commands consistent.
- `research/run_daily.py`: `_sync_data` resolves the `all_a` sync list from the `Stock`
  table (not the empty `UniversePool` row) so the daily incremental sync covers the
  whole market.
- `scripts/sync_universe.py`: `all_a` first refreshes the `Stock` table, then backfills
  every code — the one-shot tool for the initial full-history load.
- Windows automation: `scripts/aros_daily.bat` (daily `alpha run --universe all_a`),
  `scripts/aros_backfill.bat` (one-time full history), `scripts/aros_install_task.bat`
  (registers a weekday-18:30 Scheduled Task), and `scripts/WINDOWS_TASK.md` (setup
  guide). Run on the user's own machine — the sandbox proxy blocks eastmoney, so the
  full sync only works off-sandbox.

### Tests (+12)
- `tests/test_cache.py` (6): DayCache round-trip / TTL / miss + cache throttles
  money-flow & price-provider calls.
- `tests/test_run_daily.py` (6): in-memory session + fakes prove the loop wires
  4.2/4.4/4.6/4.5, is idempotent per date, auto-fills decision post-hoc, emits the
  checkpoint validation report at `auto_validate_at=1`, and that `catch_up` backfills
  a skipped day.

## Phase 4 Completion — Entry Intelligence Engine (4.7) + Exit Intelligence Engine (4.8) (2026-07-20)

> Closes Phase 4. 4.6 (calibration) was already complete; this sprint builds the
> two remaining real engines so the Discovery → Entry → Exit loop is fully
> implemented (Paper Trading stays the validation environment, not a phase).

### 4.7 — Entry Intelligence (`src/research/entry.py`, new)
- The **Entry Score synthesis layer** ("when to buy"), independent of the AROS
  Score ("whether worth researching"). `EntryEngine.evaluate(code, date, price_provider,
  *, aros_score, rating, categories, market)` blends three evidence families:
  - **Strategy combo** — dominant hit category (trend / strong / emotion) selects
    the timing model (breakout / pullback-dip / emotion-leader), per design §III.3.
  - **Current stock reality** — price action, volume expansion, relative position,
    plus a **near-limit-up guard** so we never chase the 涨停.
  - **Market judgement** — regime friendliness + money-flow read.
- Output: `Entry Score` (0-100) + discrete `action` (strong_buy / buy / wait /
  avoid) + `confidence` + explainable `reason`. Hard guard rails cap the score in
  Bear regimes and downtrends.
- Wired into `simulate_day`: `entry_mode=signal_confirmation` gates auto-entry on
  the Entry Score (records `entry_score` on `SimulatedTrade`); `manual` never
  auto-enters; `immediate` is unchanged. `resolve_categories` maps hit strategies
  to categories via `research.kb`.

### 4.8 — Exit Intelligence (`src/research/exit.py`, new)
- The **real Daily Exit Intelligence** (design §III.5): upgrades the validation
  environment's proxy score-decay to drive off the **real AROS Score** via an
  injectable `ScoreProvider`.
- `ExitEngine.evaluate(...)` produces a **graded Exit Signal** (High / Medium /
  Low / None) with explainable reasons: **logic decay** (score dropped below
  threshold or materially vs entry), **money weakening** (public/hidden flow
  turned negative), **trend break** (price below key MA), **stop hit**.
- `ExitConfig.score_decay.score_source = "real"` (default `proxy`) makes
  `simulate_day` use the real score; closed trades are tagged `score_type="real"`.
- CLI: `alpha exit eval --trade-id …` reports the graded signal + reasons;
  `alpha entry eval --code …` reports the Entry Score + action.

### Quality gates
- 13 new offline tests (`tests/test_entry.py`, `tests/test_exit.py`) covering
  breakout / limit-up-guard / bear-guard / downtrend / no-data, every exit branch,
  and the `score_source="real"` wiring (records `score_type="real"`).
- All four CI gates green (ruff / black=100 / mypy / pytest). No behavioural
  regression to the 4.7 proxy baseline.

## Sprint 4.7 — Paper Trading Validation Environment + Entry Intelligence (2026-07-20)

> Under the 2026-07-20 roadmap restructure, this sprint's `research/papertrade.py` is
> now classified as the **Paper Trading validation environment** (not a phase), and 4.7
> is redefined as **Entry Intelligence** ("when to buy"). The engine below exercises
> both entry selection and the 4.8 exit framework.

Closes the loop opened by 4.6 (selection is valid) by building an attributable,
no-look-ahead harness: once we hold AROS picks, what is the best *way to enter and
exit*? The experiment is split into two orthogonal axes so the result is attributable
(no confounding).

- `src/research/papertrade.py` (new): `simulate_day` runs one trading day for every
  portfolio (T+1 entries then exits), strictly **no look-ahead**. Selection axis
  (S1 ai / S2 human / S3 random) × Exit axis (E1 fixed / E2 trailing / E3 dynamic)
  are data-isolated cells. Exit framework v1.0 four layers, all unit-tested:
  hard stop-loss (`fixed` default, `atr` adaptive with graceful fallback to fixed
  when `high`/`low` are absent), fixed take-profit (E1), trailing profit (E2/E3),
  score decay (lightweight **proxy** score, `score_type="proxy"`; when
  `score_decay.score_source="real"` a real AROS Score drives the decay — the
  Phase 4.8 Daily Exit Intelligence from `research/exit.py`), and time-stop =
  `min(strategy, rating, portfolio)` holding cap. `portfolio_metrics` reports
  equity / return / max drawdown / win rate / P&L ratio / avg holding + **Alpha
  indicators** (annualized, Sharpe, Calmar, max consecutive losses), all checked
  against hand-computed small examples.
  `generate_papertrade_report` renders Portfolio Performance Report (md/html/xlsx)
  with a buy-&-hold benchmark comparison and a sample-size caveat.
- `src/research/models.py`: new `Portfolio` + `SimulatedTrade` ORMs (account state is
  *rebuilt* from the blotter + `PriceProvider`, never stored — no dual-write drift);
  `StrategyRegistry.max_holding_days` supports the time-stop priority chain.
- `ExitConfig` dataclass with `E1/E2/E3` presets, serialized as JSON on `Portfolio`.
- `main.py`: `alpha papertrade init|run|report` sub-commands (reuses
  `_bench_price_provider` / `_kb_session`).
- 19 new offline tests (fake `PriceProvider`, in-memory sqlite) covering every exit
  layer, ATR fallback, data isolation, Alpha indicators, and report generation.
- All four CI gates green (ruff / black=100 / mypy / pytest).

## Roadmap Restructure — AROS → AI 辅助投资决策系统 (2026-07-20)

> 战略重定位（非代码 sprint）：把能力建设顺序对齐真实交易时间轴，AROS 从"选股系统"
> 重新定位为"AI 辅助投资决策系统"。无代码改动，四门 CI 不受影响。

**四大引擎（替代原三大引擎 Selection/Execution/Protection）**：
- **Alpha Discovery Engine**（买什么）— 已完成（4.0–4.6）。
- **Alpha Entry Engine**（何时买）— **Phase 4.7**：Entry Score 合成层。
- **Alpha Management Engine**（持有怎么办）— 4.7/4.8 引擎内实现，5.5 组合层成熟。
- **Alpha Exit Engine**（何时卖）— **Phase 4.8**：分级 Exit Signal。

**Phase 重命名（原 4.7/4.8 重新定义）**：
- 4.7 由"Paper Trading（退出实验）"改为 **Entry Intelligence（入场智能）**：主责"什么时候买"。
  已实现的 `research/papertrade.py` 重新归类为**模拟交易验证环境**（不占 Phase 编号，贯穿 4.6–4.8）。
- 4.8 由"Execution Intelligence 架构占位（不开发）"改为 **Exit Intelligence（真实交付）**：
  退出框架 v1.0（四层 + 评级联动上限）已在验证环境实现并单测覆盖，作为 Exit Engine 基线；
  剩余真实 Daily Exit Intelligence（proxy→真实 AROS Score + 分级 Exit Alert）。
- **模拟交易（Paper Trading）= 验证环境，非能力模块、不占 Phase 编号**。

**Phase 5 重新规划为 Intelligent Platform（5.1–5.5）**：Dashboard / AI Research Assistant /
Strategy Discovery / Adaptive Weighting / Risk Management。详见新增 `Phase5_Intelligent_Platform.md`。

**三大核心评分贯穿每日决策**：Alpha Score（值不值得研究）/ Entry Score（现在是否适合买）/
Exit Score（是否应该离场）。

文档更新：`Roadmap.md`（四大引擎前言 + 4.7/4.8 改名 + 验证环境说明 + Phase 5 小节）、
`Phase4.6-4.8_Technical_Design.md`（§0 四大引擎 + 4.7=Entry / 4.8=Exit 重构 + 退出框架迁移至 4.8）、
新增 `Phase5_Intelligent_Platform.md`。


## Sprint 4.6 — Rating Validation & Calibration (2026-07-20)

Closes the loop opened by 4.2 (selection) + 4.5 (human feedback): proves the AROS
rating ladder actually ranks opportunity quality before any capital is risked.

- `src/research/calibration.py` (new): `fill_all_performances` auto-fills a
  `CandidatePerformance` row for *every* daily Alpha candidate (incremental,
  skips matured rows, never fabricates numbers). `rating_distribution` /
  `significance_test` answer "do higher ratings earn significantly higher forward
  returns (S>A>B>C)?" via a hand-rolled 95% bootstrap CI + Mann-Whitney U
  (no `scipy`). `baseline_excess` attributes edge to the market,
  `strategy_contribution` tallies each strategy's hit/success via
  `hit_strategies_json`, `human_vs_ai` compares AI Top-20 vs Human Top-5.
  `propose_calibration` is deliberately **two-stage** — it only *proposes*
  thresholds after ≥60 trading days; early runs stay observe-only (design §5.2).
  `generate_validation_reports` renders the four deliverables as md+html+xlsx.
- `src/research/models.py`: new `CandidatePerformance` ORM (1:1 with a candidate,
  T+1/3/5/10/20 + float excursion + `target_hit_date` + status).
- `src/research/feedback.py`: `post_hoc` extended with `target_pct` →
  `target_hit_date` and T+20 horizon (4.5 callers unaffected; `POSTHOC_DAYS` unchanged).
- Rating rename `A+ → S`: `consensus.rating_from_score` now returns `"S"`;
  `config.rating_a_plus` → `rating_s`; `migrate_rating_labels` migrates historical
  rows idempotently. `alpha validate migrate` runs it.
- `main.py`: `alpha validate` Typer sub-app (`migrate` / `fill` / `report` /
  `calibrate`).
- Design contract: `Phase4.6-4.8_Technical_Design.md` (supersedes the separate
  4.6/4.7 drafts). 14 new tests; all four CI gates green.

## Sprint 4.5 — Human Feedback Loop (2026-07-20)

Close the human loop opened by 4.2 (consensus) + 4.4 (report):

- `src/research/feedback.py`: `post_hoc(code, signal_date, price_provider)` — pure,
  fully offline-testable forward-return math (1/3/5/10d + max float pnl + final
  return; entry = T+1 trading day, no look-ahead; degrades to `None` on no data,
  never fabricates numbers). `record_decision` (human judgement 关注/买入/放弃/忽略
  + redundant `signal_date` anchor) → `review` (auto post-hoc via `DataManager.get_daily`
  + human `verified_system`/复盘总结). `record_trade`/`list_trades`/`list_decisions`/
  `query_decisions` for the personal blotter (schema + manual entry only; system
  never derives).
- `src/research/models.py`: new `DecisionTracking` + `PersonalTrade` ORM tables.
- `main.py`: `research alpha decide` / `review` / `trades-add` / `trades-list`.
- `src/report/daily_alpha.py`: Sheet2 now back-fills human columns from
  `decision_tracking` (via `query_decisions`) when the user has judged a candidate;
  returns render as percentages. Blank when undecided (4.4 behaviour preserved).
- 11 new tests; all four CI gates green (ruff/black/mypy/pytest 371 passed, 1 skip).

## Sprint 4.4 — Daily Alpha Report (2026-07-20)

Renders each day's ranked Alpha candidates (produced + persisted by the 4.2
`ConsensusEngine`) into three interchangeable, date-archived formats:

- `report/daily_alpha.py` — `DailyAlphaReport.generate(candidates, run_date, out_dir)`
  writes `reports/<date>/daily_alpha.{xlsx,html,md}`:
  - **xlsx** (data asset): Sheet1 = candidate table (design §7 / v2 Sheet1);
    Sheet2 = decision-tracking template with system columns pre-filled and the
    human columns left blank (the human loop lands in 4.5).
  - **html** (daily view): self-contained offline page + AROS SVG bar chart +
    per-candidate detail (advantages/risks/thesis/system_suggestion).
  - **md** (AI / knowledge-base friendly): mirrors the HTML content.
- `query_candidates(session, run_date)` joins `daily_alpha_candidates` to
  `daily_screenings` on `run_date` and returns rows ordered by AROS — keeping
  the full traceability chain.
- The renderer is pure: no network, no scoring math, fully offline-testable.
- `research alpha daily` now auto-emits the report after each screening.
- `openpyxl` added to `requirements.txt`; 6 new tests; all four CI gates green
  (ruff / black / mypy / pytest 358 passed, 1 network skip).

## Sprint 4.3 — Market Context & Money Flow (2026-07-20)

Replaces the 4.2 neutral money-flow defaults with real, akshare-backed
providers — while preserving the constitution ("暗盘永不淘汰候选") and the
offline-testable property. Public money flow feeds the Consensus `S` component
and the AROS `money_flow` weight; hidden flow is behavioural inference only
(never a fabricated amount).

### Added

- `src/data/providers/moneyflow.py` (new) — Sprint 4.3 providers:
  - `AkShareMoneyFlowProvider.get_stock_flow(code) -> MoneyFlowSignal`:
    `public_money_score` from the stock's recent main-net-inflow %
    (`stock_individual_fund_flow`, sigmoid around 50); `sector_score` from the
    stock's net-inflow % **minus** its industry's (`stock_board_industry_rank_em`
    via `stock_individual_info_em` industry lookup) so it is a *relative* strength.
  - `AkShareHiddenFlowProvider.infer(code) -> HiddenFlowSignal`: pure
    **behavioural inference** over recent OHLCV + fund flow — low-vol base +
    volume pickup with net inflow ⇒ quiet accumulation (higher score);
    up-on-rising-volume with net outflow ⇒ distribution (lower score). Returns
    `(score, explanation)`; the explanation always states "非金额" / 行为推断.
    No monetary amount is ever produced (v2 red line: 不伪造暗盘资金金额).
  - Pure, unit-tested scoring helpers: `public_money_score`, `sector_score`,
    `hidden_flow_infer`, `_recent_net_pct`, `_market_of` (sh/sz/bj mapping).
  - **Defensive degradation**: every external fetch is wrapped; on any network
    error / rate-limit / column drift the provider returns a **neutral** signal
    (50) instead of raising — the daily run never aborts. Column drift is
    handled by tolerant header resolution (`_col`), mirroring `data/provider.py`.
- `src/data/manager.py` — `DataManager.get_fund_flow(code)` and
  `get_sector_concept(code)` thin entry points (design §5 4.3), lazily
  delegating to the moneyflow provider and degrading to empty on failure.
- `main.py` — `research alpha daily` now wires `AkShareMoneyFlowProvider` /
  `AkShareHiddenFlowProvider` by default (they self-degrade offline). New
  `--no-money-flow` flag restores the 4.2 neutral behaviour.
- `tests/test_moneyflow.py` (13) — pure scoring anchors (public/sector/hidden,
  accumulation vs distribution, no-data neutral) + provider behaviour with
  injected fakes + degradation-to-neutral on exception + contract check.
- `tests/test_consensus.py` — +1 engine test (`test_daily_wires_43_providers`)
  proving provider outputs flow through to `ConsensusResult`.

### Notes

- **No look-ahead.** Hidden-flow inference uses only historical bars up to the
  signal date (price/volume fed from the same qfq history the engine already
  uses); no future bar is read.
- **Constitution preserved.** Hidden flow is a risk-enhancement factor only:
  it can add/subtract points and attach a risk note, never eliminate a
  candidate. On any failure it returns the neutral 50 (not a penalty).
- **Offline-safe.** All akshare calls are lazy and guarded; the suite injects
  fakes, so CI never needs network. Real fetches only happen on a live
  `research alpha daily` run.
- All four gates green: `ruff check .` / `black --check --line-length 100 .` /
  `mypy src tests main.py --ignore-missing-imports` / `pytest -q` (13 new tests;
  full suite 352 passed, 1 pre-existing network skip).

## Sprint 4.2 — Multi-Strategy Consensus Engine (2026-07-17)

Turns the validated strategy pool (4.1) into a daily, ranked **alpha candidate**
list. Aggregates each strategy's T-day signal across the universe, de-duplicates
correlated strategies by OOS behaviour, then scores every candidate with the
Consensus Score and the AROS Final Score, persisting the whole evidence chain.

### Added

- `src/research/consensus.py` (new) — the Multi-Strategy Consensus Engine:
  - Pure, unit-tested math: `regime_match_fraction(current, best_fit_regimes)`
    (fraction of hitting strategies whose best-fit regimes contain `current`;
    full → 1.0, none → `regime_base`); `independence_score(survivors,
    fold_by_strategy, cfg)` (uses `abs(avg_corr)` over |corr| ≥ `corr_dedup_threshold`
    pairs so negatively-correlated ≠ independent); `consensus_score(...)` (H20+Q30+I20+R15+S15,
    breakdown + survivors); `aros_score(...)` (0.35·consensus + 0.20·env +
    0.30·money + 0.15·risk, breakdown); `rating_from_score(aros, cfg)` (A+≥85 / A≥70 / B≥55 / C<55).
  - `_dedup_survivors` — union-find over `(category, correlation-cluster)`: within a
    category, strategies whose OOS fold-return series correlate above
    `corr_dedup_threshold` form a cluster; only the highest-`quality_star` member
    survives into Q/I. Non-survivors still count toward hit count H.
  - `ConsensusEngine.__init__(data_manager, universe_engine, config, price_provider,
    benchmark_provider, money_flow_provider, hidden_flow_provider)`. `daily(universe=,
    signal_date=, *, session, limit=, regime=, notes=)` → `list[ConsensusResult]`:
    resolves the active strategy pool → fetches T-day prices → aggregates per-code
    signals → scores → ranks by AROS → persists `DailyScreening` → `ScreeningHit`s →
    `DailyAlphaCandidate`s. `_infer_regime` derives the regime from the benchmark's
    `MarketRegimeEngine` (falls back to `NEUTRAL`); `_fetch_prices` / `_load_validations`
    read `StrategyValidation.oos_json.fold_returns` + `metrics_json.max_drawdown`.
  - `MoneyFlowProvider` / `HiddenFlowProvider` Protocols + neutral defaults
    (`sector_score=50`, hidden-flow `score=50`, "无暗盘数据源(4.3 接入)，取中性分；不淘汰候选").
    Keeps 4.2 offline/self-contained and honours the constitution's "暗盘永不淘汰候选".
- `src/research/models.py` — 3 Phase 4.2 ORM tables: `DailyScreening`
  (`daily_screenings`: run_date/index, universe, regime_label, regime_detail_json),
  `ScreeningHit` (`screening_hits`: screening_id FK, strategy_id, code, signal_date,
  quality_star_snapshot), `DailyAlphaCandidate` (`daily_alpha_candidates`: code/name/
  industry/sector/concepts_json, hit_count, hit_strategies_json, avg/max_quality_star,
  consensus_score, aros_score, public_money_score, hidden_flow_score, sector_score,
  rating, consensus_breakdown_json, aros_breakdown_json, advantages/risks/thesis/
  system_suggestion, all fully traceable back to the screening + hits).
- `core/config.py` — `ConsensusConfig` (w_hit/w_quality/w_independence/w_regime/
  w_sector_money, hit_cap, regime_full, regime_base, corr_dedup_threshold,
  default_star_when_unvalidated, w_aros_*, regime_friendliness, money_visible/hidden
  weights, risk_dd_penalty/threshold, rating_a_plus/a/b, top_n) wired into
  `AppConfig.consensus` and `settings.yaml consensus`.
- `main.py` — `research alpha` Typer sub-app (`alpha daily` with --universe/--date/
  --limit/--regime); auto-seeds the 10 built-in strategies if no active registry row
  exists; prints the ranked candidates and reports the persisted Top-N count.
- `tests/test_consensus.py` (9) — 4 engine integration cases (produces+persists
  candidates / no-hits→no-candidate / respects `top_n` / persists AROS ranking) + 5
  pure-math cases (components sum to score / dedup drops a correlated strategy /
  independence penalises correlation / regime-match fraction / AROS weights+rating).

### Notes

- **No look-ahead.** Strategy signals are T-day booleans (T+1 fill handled by the
  backtester); the consensus daily run never reads future bars. The benchmark regime
  is inferred from bars `<= signal_date` only.
- **Neutral money-flow by design.** Real money-flow / hidden-flow providers are 4.3's
  responsibility; 4.2 ships neutral defaults (score 50) so the pipeline is fully
  testable offline and the constitution ("暗盘永不淘汰候选") is preserved.
- All four gates green: `ruff check .` / `black --check --line-length 100 src tests main.py` /
  `mypy src tests main.py --ignore-missing-imports` / `pytest -q` (9 new tests; full suite 339 passed, 1 skipped).

## Sprint 4.1 — Research Integrity Framework (2026-07-17)

The research-integrity gate (AROS 宪法): turns a walk-forward OOS run into a
defensible **quality star**, a **reliability score**, and a pass/fail **Strategy
Validation Gate**, and persists the whole evidence chain. This is the trust layer
that 4.2–4.5 (combination glue, scheduling, live signals) build on.

### Added

- `src/research/validate.py` (new) — the Research Integrity Framework:
  - Pure, unit-tested math: `compute_oos_composite(oos, fold_returns, qcfg)`
    (return 30% / sharpe 25% / drawdown 25% / stability 20% → composite + breakdown);
    `quality_star_from_composite(composite, max_dd_abs, num_trades, qcfg)` → 1–5 with
    vetoes (drawdown > 40% ⇒ cap 2; trades < 100 ⇒ cap 3);
    `compute_reliability(oos, fold_returns, num_params, avg_decay, vcfg)` (OOS 40% /
    param 20% / period 20% / trades 20% → score + breakdown); `evaluate_gate(...)`
    → (passed, detail) over the six gate conditions.
  - `_perturbations` steps every numeric `spec.parameters` by ±1 (int) or ±0.1 (float);
    `_clone_with_params` deep-clones a strategy with the override (used by the
    parameter-sensitivity test). `_sharpe_decay` measures OOS sharpe loss under
    perturbation.
  - `ValidationEngine.__init__(batch_runner=None, config=None)` converts the local
    `WalkForwardConfig` → `WalkForwardSpec` at runtime (no research import in
    `core.config`, so no circular import). `run_strategy(name, session, *, start,
    end, benchmark, notes)` runs the frozen walk-forward OOS → param-perturbation
    loop → composite/star → reliability → gate → persists a `StrategyValidation` row
    and auto-adds/updates the `strategy_registry` row (status = `active` if the gate
    passed, else `degraded`); returns a `ValidationResult`. `_json` coerces numpy /
    non-finite values to JSON-safe; `_evidence_ranges` drives IS/OOS windows via
    `WalkForwardSplitter`.
- `src/research/models.py` — `StrategyValidation` ORM (`strategy_validations`):
  `id` (PK), `strategy_id` (FK index), `run_id`, `metrics_json`, `oos_json`,
  `status_suggestion`, `is_range`, `oos_range`, `optimization`, `walk_forward_passed`,
  `reliability_json`, `gate_result_json`, `created_at`.
- `core/config.py` — `ValidationGateConfig` (`oos_return_gt` / `oos_sharpe_gt` /
  `max_drawdown_lt` / `min_trades` / `param_stable` + `param_decay_threshold`),
  `QualityStarConfig` (scales + vetoes), `ReliabilityConfig` (weights),
  `ValidationConfig` (walk_forward / gate / quality_star / reliability); wired into
  `AppConfig.validation` (and `settings.yaml` `validation`).
- `main.py` — `research validate` Typer sub-app (`run <strategy>` / `all`) plus a
  `_print_validation` renderer (star / composite / reliability / gate).
- `tests/test_validate.py` (6) — 4 pure-math cases (composite / star / reliability /
  gate anchors) + 2 integration cases on synthetic `ma_bull` (injected `BatchRunner`,
  `min_trades=0`, 1/1/1 walk-forward).

### Notes

- **Circular-import avoidance.** `core.config` deliberately defines a *local*
  `WalkForwardConfig` instead of importing `research.experiment.WalkForwardSpec`
  (which would pull `research.batch` ← `core.config` into a loop). `validate.py`
  maps config → Spec just before the run.
- All four gates green: `ruff check .` / `black --check --line-length 100 .` /
  `mypy src` / `pytest -q` (6 new tests; full suite green, 1 network skip).

## Sprint 4.0 — Strategy Knowledge Base (2026-07-17)

Phase 4 地基（设计 🟢 Design Approved, `Phase4_Technical_Design_v2.1.md` §9 建议首切）：
策略知识库 + 自选股池 Provider 抽象，是 4.1 诚信框架与 4.2–4.5 的依赖根。把「原始想法」
(raw) 与「可执行正式库」(registry) 分开，正式库从 `strategy_library` 的 10 套内置策略
幂等 seed 为 `active`。

### Added

- `src/research/models.py` — `RawStrategy` (`raw_strategies`): `strategy_id` (PK),
  `name`, `source_type`, `source`, `original_description`, `original_rules`,
  `collected_at`, `status` (raw/pending_validation/validated/active/degraded/retired);
  `StrategyRegistry` (`strategy_registry`): `strategy_id` (PK), `name`, `category`,
  `executable_ref`, `status`, `validation_run_id`, `quality_star`, `reliability_score`,
  `gate_passed`, `best_fit_regimes`, `added_at` (seeded from `strategy_library` at
  `active`).
- `src/research/kb.py` (new) — `RawPool` (add / get / list / set_status over
  `raw_strategies`); `StrategyRegistry` (seed_builtins idempotent via `session.merge`,
  derives `best_fit_regimes` from `REGIME_CATEGORY_FIT`; get / list_active /
  list_by_status / add / update_validation / retire); `_new_raw_id` / `_new_validation_id`
  helpers; `ensure_kb_tables`.
- `src/research/universe_provider.py` (new) — `UniverseProvider` ABC
  (`codes(as_of=None) -> list[str]`); `CSI800Provider` (via `UniverseEngine().get_codes("csi800")`),
  `WatchlistProvider` (inline codes or one-per-line file, `#` ignored), `CustomProvider`
  (fixed list, rejects empty); `get_universe_provider(type=None, *, config,
  watchlist_path, codes)` factory resolving CSI800 / Watchlist / Custom **without any
  hard-coded code list**.
- `core/config.py` — `UniverseConfig` (`type: Literal["csi800","watchlist","custom"]`
  default `csi800`, `watchlist_path`, `custom_codes`); wired into `AppConfig.universe`
  (and `settings.yaml` `universe`).
- `main.py` — `research kb` Typer sub-app (`seed` / `list` / `add-raw` / `retire`).
- `tests/test_kb.py` (11) — raw pool add/list/status; seed_builtins seeds 10 active;
  seed is idempotent (second run returns 0); registry update_validation / retire / add;
  CSI800 / Watchlist / Custom + `get_universe_provider` factory.

### Notes

- The KB decouples "idea capture" from "executable library" so validation evidence
  (4.1) attaches to a stable `strategy_id` rather than a strategy name.
- All four gates green: `ruff check .` / `black --check --line-length 100 .` /
  `mypy src` / `pytest -q` (11 new tests; full suite green, 1 network skip).

## Sprint 3.2 — Real A-share Data Bridge (2026-07-19)

The Phase 3 research pipeline now runs end-to-end on **real A-share data**
(AKShare primary, a-stock-data fallback). The synthetic-data-only era of 3.2 is
over: real daily bars flow through `DataManager` → `BatchRunner` →
`EventBacktest` and produce non-zero out-of-sample metrics.

### Fixed

- **Critical no-trade bug (real data only).** `run_strategy` now normalises each
  OHLCV frame to a `DatetimeIndex` on `date`. `DataManager.get_daily` returns a
  plain `RangeIndex` (its documented storage contract — `date` is a *column*), but
  `EventBacktest._common_index` does `pd.DatetimeIndex(df.index)`, which turned the
  RangeIndex into 1970-epoch timestamps. Every signal Series then `reindex`-ed to
  `NaN` → all signals dropped to zero → **0 trades → +0.0% OOS for every strategy
  on real data**. Synthetic tests never caught this because their frames were
  already DatetimeIndex'd. The fix lives at the single funnel into `EventBacktest`
  so it covers both the `event` and `portfolio` engines (and any future real-data
  single-strategy run) without disturbing `DataManager`'s column contract.
- **Re-run collision.** `research batch` default run name now carries a wall-clock
  stamp, so repeating a run the same day no longer violates the `UNIQUE
  experiment_runs.name` constraint.

### Added

- `main.py` — `research batch` command: real-data batch backtest with
  `--strategies` (comma-separated) / `--start` / `--end` / `--benchmark` /
  `--limit` (feasibility cap) / `--walk-forward TRAIN TEST STEP` / `--no-sync` /
  `--seed-csi800` / `--emit-report`. Syncs the stock list, each strategy's universe
  codes (csi800 seeded from AKShare `index_stock_cons` 000906; all_a from the stock
  list), and the benchmark index, then runs `BatchRunner` and prints an OOS summary
  (optionally writing a ranking report to `reports/`).
- `src/data/provider.py` — `normalize_*` helpers accept **both Chinese and English**
  AKShare column headers, defending against akshare version drift (newer releases
  return `code`/`name`; daily/index still return Chinese headers).
- `tests/test_batch_realdata_bridge.py` — offline bridge test: a `DataManager`
  subclass returning deterministic OHLCV, proving the default `BatchRunner` price/
  benchmark providers read through `DataManager` (no network) and that at least one
  strategy yields a non-`None` OOS return.
- `tests/test_data.py` — English-header normalisation tests (lock the akshare >=
  1.18 fix); `test_manager_selects_astockdata_source` now pins `cfg.database.url` so
  it is hermetically isolated from the shared `data/aros.db` (previously a real-data
  sync elsewhere could leak into its 3-row expectation).

### Added (follow-up: strategy 复盘 — equity/drawdown curves)

- `src/research/report.py` — `research report --format html` now plots **净值曲线
  (equity) + 回撤曲线 (drawdown)** for every window that has a stored equity blob
  (the runner already persists `equity` via `ExperimentRegistry.record_equity` since
  2.4). Inline self-contained SVG (offline, no external JS/CSS), one equity + one
  drawdown panel per window (IS/OOS labelled). `to_markdown` gains a "三、净值与回撤"
  summary (期末净值 / 峰值 / 最大回撤). This is the lightweight 复盘 layer requested:
  visualise the equity the framework already records, without persisting trade
  blotters or signal timelines.
- `tests/test_report_equity_chart.py` — render asserts `<svg` equity + drawdown present
  and the markdown max-drawdown summary is correct; empty-equity report renders without
  charts. `tests/test_research.py` updated: a single-run report has no IS/OOS chart but
  now DOES carry the equity/drawdown curves.

### Verified

- On real csi800 data (40 names, 105k bars, 2019–2023, 3/1/1 walk-forward) price/
  volume strategies produce non-zero OOS, e.g. `volume_breakout` +13.0%,
  `leader_first_down` +7.5%, `high_breakout` +6.7%. The emotion/limit-up strategies
  (`first_board`, `second_board_relay`, `high_board`) legitimately stay ~0% because
  limit-up detection on **qfq-adjusted** closes is unreliable — documented as
  `daily_approx` / `needs_intraday` in their specs.
- CI four gates green: `ruff check .` / `black --check .` / `mypy src tests main.py`
  / `pytest -q` (full suite).

## Sprint 3.5 — Market Regime Engine + V1.0 Report (2026-07-19)

Transparent 5-label market-regime classifier and dynamic strategy selection, plus
the project's single deliverable: the AROS A 股短线策略研究报告 V1.0 (Phase 3 §9).

### Added

- `core/config.py` — `MarketRegimeConfig` (E5): momentum/vol/drawdown windows,
  `bull_mom` / `bear_mom` / `high_vol_cap`, `sentiment_window`,
  `emotion_hot_threshold` / `emotion_cold_threshold`; wired into
  `ResearchConfig.market_regime` (and `settings.yaml` `research.market_regime`).
- `src/research/market_regime.py` (new) — explainable, no-look-ahead 5-label
  classifier `classify_market_regime(close, breadth=None, config)`:
  * `Bull` / `Neutral` / `Bear` from index momentum + realised volatility;
  * `EmotionHot` / `EmotionCold` from an optional net limit-up breadth series
    (never fire without breadth, so the function stays deterministic on price-only
    data). `MarketRegimeEngine` maps the live regime to the best-fit strategy via
  an explainable category-fit rule (`REGIME_CATEGORY_FIT`) refined by the empirical
  per-regime walk-forward OOS return the 3.2 batch already produced
  (`SelectionResult` carries the rationale).
- `src/research/final_report.py` (new) — `FinalReport.from_batch(...)` composes the
  whole pipeline (strategy library + 3.3 AROS ranking + 3.4 combination + 3.5 regime
  engine) into the V1.0 deliverable, rendered to markdown / json / html; the verdict
  answers *"若明天开始做 A 股短线，哪套（或哪组）策略最值得使用"*.
- `report.py` / `__init__.py` re-export the new symbols (engine, classifier,
  `FinalReport`, `SelectionResult`, 5-label constants).

### Tests

- `tests/test_market_regime.py` (11) — deterministic classification, no look-ahead,
  trend/vol → Bull/Bear/Neutral, breadth → EmotionHot/Cold, category-fit mapping,
  `select_strategy` empirical pick + determinism, `recommendations` covers all 5.
- `tests/test_final_report.py` (9) — all five sections present, json round-trips,
  market-data regime inference, determinism, self-contained html, entry point.

## Sprint 3.4 — Strategy Combination (2026-07-19)

Regime-conditioned combination of the Top-N AROS strategies (Phase 3 design §3.4).

### Added

- `core/config.py` — `CombinationConfig` (E5): `top_n`, trending/oscillating regime
  lists, category-bias lists, `category_bias` / `perf_weight` / `perf_cap`,
  `equal_weight_floor`; wired into `ResearchConfig.combination` (and `settings.yaml`
  `research.combination`).
- `src/research/combination.py` (new) — `CombinationEngine.combine(batch, ranking,
  scorecard, config)` builds a per-environment (`trending` / `oscillating`) allocation:
  * selection = Top-N by the 3.3 AROS Strategy Score (passed-in `RankingReport` or
    recomputed);
  * weights = base + category-fit bonus + regime-performance tilt, floored then
    normalised to 1.0 per environment;
  * combined metrics = weighted blend of the selected strategies' **already-computed
    OOS metrics** (reuses `compute_metrics` output; `None`/non-finite dropped);
  * an illustrative synthetic equity curve per environment for visualisation only
    (clearly labelled, never used to derive a metric).
  `env_for_regime()` maps a 3.2 regime label to an environment bucket (the seam 3.5's
  Market Regime Engine consumes). `CombinedResult` carries `weights` / `combined_metrics`
  / `combined_equity` + `to_dict` / `to_json` / `to_markdown`; `render_combination_report`
  is the markdown entry point.
- `report.py` re-exports the combination symbols; `__init__.py` exports them too.

### Tests

- `tests/test_combination.py` (8): weights normalise per environment + respect floor,
  combined metrics reproducible, Top-N respected, category-bias direction
  (trend beats emotion in trending / opposite in oscillating), regime-performance tilt,
  hand-checked weighted blend (`total_return`/`win_rate`/`max_drawdown`), `env_for_regime`
  mapping, reporting renders both buckets.

### CI

- All four gates green: `ruff check .`, `black --check .`, `mypy src tests main.py`,
  `pytest -q` (8 new tests; full suite green).

## Sprint 3.3 — Strategy Evaluation & Ranking (2026-07-19)

Completes the AROS Strategy Score (§4): bridges a `BatchResult` into the
`Scorecard` and renders the cross-strategy ranking table in markdown / json /
html, plugged into the research reporting family beside `ResearchReport`.

### Added

- `src/research/scorecard.py` — `SCORECARD_METRIC_KEYS` constant listing the 8
  realised metric keys the 7-dimension score consumes (so the batch runner can
  guarantee they are computed).
- `src/research/ranking.py` (new) — `build_score_inputs(batch)` bridges a
  `BatchResult` into `ScoreInput` (scored metrics = **OOS** walk-forward values,
  IS/OOS carried for the E3 OOS-decay penalty; `None`/non-finite values dropped
  so `inf`/`nan` can never poison the min-max normalisation). `RankingReport`
  renders the §4-frozen ranking table (排名 / 策略 / 类别 / 评分 / 收益(OOS) /
  胜率(OOS) / 回撤(OOS) / 持仓(天) / OOS衰减 / 数据可信度) as `to_markdown` /
  `to_json` / `to_html`; `from_batch(batch, scorecard=None)` and a
  `render_ranking_report(...)` entry point mirror `render_experiment_report`.
- `src/research/report.py` — re-exports `RankingReport` / `build_score_inputs`
  (接入 ResearchReport — ranking is part of the reporting family).
- `src/research/batch.py` — `BatchRunner` now augments its requested metric list
  with the scorecard keys (`profit_factor` / `avg_holding_days` /
  `max_consecutive_losses`, which are *not* in the default `BacktestConfig.metrics`
  but are produced by `compute_metrics`) so a `BatchResult` always carries
  everything the scorer needs. Additive, no removal → no 3.2 regression.
- `tests/test_scorecard.py` — hand-anchored scoring/ranking math, reverse
  indicator direction (smaller drawdown scores higher), E3 OOS-decay penalty,
  neutral (all-equal) case, configurable weights/threshold (E5).
- `tests/test_ranking.py` — `build_score_inputs` bridge (OOS + None-drop),
  `RankingReport` md/json/html structure, OOS-decay 低/中/高 tagging, single-window
  (no decay) case, config-driven `Scorecard` passthrough.

### Changed

- `config/settings.yaml` — `research.scorecard` weights + `oos_decay_*` were
  already present (E5); 3.3 exercises them end-to-end via `Scorecard.from_config`.

## Sprint 3.2 — Batch Strategy Experiment (2026-07-18)

Traverses **策略 × 冻结 ExperimentConfig × walk-forward** and persists every
strategy as its own reproducible :class:`ExperimentRun`. Reuses the 2.5
walk-forward machinery and the 3.1 uniform `EventBacktest` path so all 10
strategies land in one comparable metric set (portfolio metrics +
``bench_*`` relative metrics via :class:`BenchmarkEngine`).

### Added

- `src/research/batch.py` — `BatchRunner` (per-strategy walk-forward over the
  frozen `ExperimentConfig`), `BatchResult` / `StrategyBatchOutcome` dataclasses.
  Injectable `price_provider` / `benchmark_provider` / `benchmark_engine` so the
  runner is exercisable end-to-end on synthetic data (no DB / no network).
  One `ExperimentRun` per strategy (``{config.name}:{strategy}``) →
  :meth:`ExperimentRegistry.load_result` reproduces it exactly. D7 universe
  binding: codes come from `UniverseResolver` reading each strategy's own
  `universe` (csi800 / all_a / custom), never a global pool. No look-ahead: the
  benchmark is capped at the strategy's own last equity date (mirrors
  `ResearchRunner`); the event engine also reindexes the benchmark to traded
  dates. Optional regime robustness: each trade is tagged by the market regime
  on its entry date (`regime.py`) and aggregated per regime without re-running.
- `src/research/regime.py` — `classify_regime(benchmark_close)` returns an
  explainable Bull / Neutral / Bear / Extreme label per date from momentum,
  realised volatility and drawdown (no model, no look-ahead). Used for the
  batch sub-period stability read.
- `src/research/__init__.py` — exports `BatchRunner`, `BatchResult`,
  `classify_regime`, `REGIMES`, `NEUTRAL`.
- Tests: `tests/test_batch.py` (8 — batch run + persistence + `load_result`
  reproducibility + regime breakdown + single-window + all_a resolution via
  `data_manager` + `run_all` 10 strategies + bench_* merge via injected engine +
  unknown-strategy guard), `tests/test_regime.py` (9 — Bull/Bear/Extreme labels,
  no-look-ahead, empty input, warmup default). Four gates green.

### Notes

- `EventBacktest` reindexes the benchmark to the traded dates, so passing the
  full fold benchmark to `run_strategy` never leaks future data.
- D6 point-in-time constituents: still resolved through `UniverseResolver`; a
  real historical-constituent feed is wired when the data layer exposes it
  (the runner already passes `as_of` = fold end to the resolver).

## Sprint 3.1 — Strategy Library (2026-07-17)

Implements the 10 research strategies from Phase 3 design §7, each as a
:class:`ResearchStrategy` pairing the frozen `ResearchStrategySpec` contract
(D1–D5, D7) with a *pure, explainable* entry-signal generator. Per design
invariant: every signal at day T uses only data <= T (no look-ahead, no
leakage); logic is a small explicit rule set (no ML); output is a per-code,
per-date boolean `entry` signal feeding `EventBacktest` (T-day signal → T+1
open fill). The 3.1 `run_strategy` helper runs **every** strategy through
`EventBacktest` so all 10 share one comparable metric set (uniform V1.0
research); `portfolio`-engine strategies additionally expose `score()` for the
3.2 cross-sectional Top-N BatchRunner.

### Added

- `src/research/strategy_library.py` — the 10-strategy library, split by the
  D8 data-trust batches:
  - **Batch 1 (daily_full, high-confidence):** `ma_bull` 均线多头 (portfolio
    engine, MA cross + volume filter + Top-N), `high_breakout` 新高突破,
    `volume_breakout` 放量突破, `strong_pullback` 强势回踩, `leader_first_down`
    龙头首阴.
  - **Batch 2 (daily_approx):** `shrink_reversal` 缩量反包, `first_board` 首板,
    `second_board_relay` 二板接力 (board-specific limit rates land in 3.2).
  - **Batch 3 (needs_intraday, daily-approx research only — flagged as
    reference):** `high_board` 连板博弈, `sentiment_rebound` 情绪冰点修复 (uses
    an optional market-breadth index gate; intraday behaviour is out of scope
    and clearly marked).
  - Shared indicator helpers (`sma`, `is_limit_up` proxy at 9.5% close-to-prev
    close, `vol_ratio`); a module-level `STRATEGIES` registry; `get_strategy` /
    `list_strategies` / `run_strategy` entry points. Limit-up detection is a
    9.5% main-board proxy (board-specific 10%/20%/5% rates refined in 3.2).
- `tests/test_strategy_library.py` — 13 tests: every strategy's rule fires on
  crafted data; a no-look-ahead test pins "no entry before data exists"; the
  registry + `run_strategy` are wired; `ma_bull` runs the cross-sectional
  Top-N path. Two rules hardened during review: `strong_pullback` now requires
  a *recent shrinking-volume pullback* (not a low-volume relaunch day), and
  `shrink_reversal` uses the standard bullish-engulfing definition (close >=
  prior open, open <= prior close) instead of a gap-required one.

### Changed

- `src/research/__init__.py` — import `strategy_library` to trigger registration
  and export `ResearchStrategy`, `STRATEGIES`, `get_strategy`, `list_strategies`,
  `run_strategy` (the 3.1 strategy-instance API; the 3.0 contract-level
  `get_strategy` remains reachable via `research.strategy_spec`).

## Sprint 3.0 — Strategy Research Framework (2026-07-17)

Phase 3 foundation (the "地基" everything else builds on). Implements the
frozen Phase 3 design (🟢 Design Approved, `docs/Phase3-Technical-Design.md`):
the **Strategy Contract**, an **event-driven backtest engine** that coexists
with the 1.16 portfolio engine, and the **AROS Strategy Score** skeleton. No
strategy code yet — only standards + substrate. Three red-line gaps from the
design are honestly addressed: daily-only data, portfolio-only backtest, and
no broker interface.

### Added

- `src/research/strategy_spec.py` — the Phase 3 **Strategy Contract**
  (`ResearchStrategySpec`, alias `StrategySpec`): `category` (trend/strong/emotion),
  `engine` (portfolio/event), `universe` (csi800/all_a/custom, D7), holding
  period, entry/exit rules, `risk_control`, and `data_fidelity` (daily_full /
  daily_approx / needs_intraday, D3). Ships an in-process strategy registry
  (`register_strategy` / `get_strategy` / `list_strategies`) and a
  `UniverseResolver` whose `csi800` path **refuses an empty/undefined pool** to
  block the survivor-ship bias D6 forbids (the point-in-time constituent fetch
  itself lands in 3.2). Does not touch the 2.0 frozen `ExperimentConfig`.
- `src/backtest/event.py` — `EventBacktest` (constraint B answer): T-day close
  signal → **T+1 open entry**, position held until stop-loss / take-profit /
  max-holding-days expiry → **close exit** (daily approximation). Reuses the
  existing `CostModel` and `compute_metrics` exactly (no new metric math), so
  `event`-engine strategies emit the same metric set as `portfolio`-engine ones
  and are directly comparable. Equity is a cost-aware cash + mark-to-market book
  capped at `max_positions`; a no-look-ahead test pins "no position on day 0".
- `src/research/scorecard.py` — `Scorecard` (§4, E1–E5): 7-dimension weighted
  score (0–100) over the realised metric keys via cross-sectional min-max
  normalisation; `max_drawdown` is abs-then-reversed, `holding_experience`
  averages `avg_holding_days` + `max_consecutive_losses`. The E3 anti-overfit
  guard discounts the Sharpe dimension when walk-forward OOS decays > 50% vs IS.
  Pure function of `ScoreInput` list, hand-anchor tested.
- `src/core/config.py` — `ScorecardConfig` (weights + `oos_decay_*`); wired into
  `ResearchConfig.scorecard` (E5 — weights configurable, no code change needed).
- `config/settings.yaml` — `research.scorecard` block with the frozen 7 weights.
- Exports: `EventBacktest`/`EventResult` in `backtest`, and `Scorecard`/
  `ScoreInput`/`ScoreRow`/`StrategySpec`/`UniverseResolver`/registry helpers in
  `research`.
- Tests — 18 new cases: strategy contract enum guards + custom-universe guard +
  `UniverseResolver` D6 path; event backtest take-profit / stop-loss /
  max-holding-days / no-signal / no-look-ahead; scorecard hand-anchor (A=100,
  B≈52.67, C=0) + reverse-direction + holding-experience composite + OOS-decay
  penalty.

### Scope / non-goals

- No concrete strategy (those are Sprint 3.1). No point-in-time constituent
  fetch (Sprint 3.2). The runner injection of `EventBacktest` lands in 3.2.

## Sprint 2.6 — Research Report (2026-07-17)

Sprint 2.6 fills the `src/research/report.py` stub with `ResearchReport`, which
aggregates an experiment's metrics + benchmark comparison + walk-forward IS/OOS
into a shareable report (markdown / json / html). Rendering reuses the 1.8 / 1.14
`DailyReport` style — inline CSS and inline SVG bars — so the HTML is fully
self-contained and renders offline (no external JS/CSS). No new metric math: the
report only *presents* data the runner (2.4) and walk-forward runner (2.5) already
produced and persisted. A new `ExperimentRegistry.load_result(run_id)` reconstructs
an `ExperimentResult` from the DB (`ExperimentMetric` + `ExperimentEquity` rows,
windows ordered, IS/OOS flag derived) so a report can be rendered from a persisted run.

### Added

- `src/research/report.py`
  - `ResearchReport` dataclass with builders `from_run(run, result)` (DB row + reconstructed result; carries name / strategy / start / end / benchmark / status) and `from_result(result)` (stub fallback when only an in-memory result exists).
  - `to_dict` / `to_json` (UTF-8, indented) / `to_markdown` / `to_html`. Markdown shows each metric as `中文标签 \`raw_key\`` (raw key + Chinese label, machine-referenceable). HTML is self-contained: metadata header, IS-vs-OOS diverging-bar SVG (walk-forward runs only; single-run reports have no chart), and per-window detail tables — no `http(s)://` references.
  - `render_experiment_report(result)` stub entry point delegates to `ResearchReport.from_result(result).to_markdown()`.
- `src/research/registry.py` — `load_result(run_id) -> ExperimentResult | None` reads `ExperimentMetric` + `ExperimentEquity` grouped by window; returns `None` when the run is missing.
- `src/research/__init__.py` — export `ResearchReport` / `render_experiment_report`.
- `main.py` — `research report <id> [--format markdown|json|html]` (default markdown) loads the run + result via the registry and prints the report; the `research show` command is unchanged.
- `tests/test_research.py` — eight new 2.6 cases: markdown carries id + OOS flag + raw/bench keys; `render_experiment_report` stub; json round-trip; html self-contained + offline (no `<svg>` for single run); walk-forward report has IS/OOS section + SVG + IS-OOS decay; `load_result` DB round-trip (in-memory DB) feeding `from_run`; CLI `research report` for markdown / json / html (tmp DB).

### Scope / non-goals

- No ORM schema change, no new metric functions — only presentation + DB reconstruction.

## Sprint 2.5 — Walk-Forward / Out-of-Sample (2026-07-17)

Sprint 2.5 fills the `src/research/walk_forward.py` stub with `WalkForwardSplitter`
(date-only rolling-window arithmetic) and `WalkForwardRunner` (rolling OOS
orchestration). The runner reuses the entire 2.4 pipeline through a new
`ResearchRunner._execute_window` seam, so the backtest / metric / benchmark /
persist logic is written exactly once. No new metric math, no ORM schema change.

### Added

- `src/research/walk_forward.py`
  - `WalkForwardFold` dataclass (`index`, `train_start`, `train_end`, `test_start`, `test_end`; all `YYYY-MM-DD` strings).
  - `WalkForwardSplitter.split(spec, start, end) -> list[WalkForwardFold]` — pure `pd.DateOffset(years=N)` arithmetic (leap-day safe, never `date.replace`). A fold is included only when its *whole* test window fits inside `[start, end]`; the OOS window starts exactly where training ends (`test_start == train_end`) — the core no-look-ahead boundary. Returns `[]` when the range is shorter than `train + test`.
  - `WalkForwardRunner(config, session, notes)` — builds one `run_id`, computes IS (`is_<i>`) and OOS (`oos_<i>`) folds, then aggregates `is_agg` / `oos_agg` (per-metric mean over IS folds / OOS folds; `None`/`non-finite` skipped). `walk_forward=None` transparently delegates to `ResearchRunner` (single `"full"` window).
- `src/research/runner.py` — extract `ResearchRunner._execute_window(config, session, *, window, run_id, is_oos) -> ExperimentResult` from `run()`. `run()` now creates the run and delegates the single `"full"` window to it; the public signature is unchanged.
- `src/research/__init__.py` — export `WalkForwardSplitter` / `WalkForwardRunner` / `WalkForwardFold`.
- `main.py` — `research run` transparently dispatches to `WalkForwardRunner` when `--walk-forward TRAIN TEST STEP` is supplied; prints IS vs OOS aggregates side by side. Single-range runs are unchanged.
- `tests/test_research.py` — eight new walk-forward cases: splitter correctness + `test_start == train_end` boundary; too-short range ⇒ no folds; leap-year start (`2020-02-29` → `2021-02-28`); e2e produces the 6 windows and persists aggregates (`oos_agg` with `is_oos=True`); aggregation is the per-metric mean; range too short ⇒ `DataError`; `walk_forward=None` delegates to the single runner; CLI dispatch routes `--walk-forward` to `WalkForwardRunner`.

### No-look-ahead (double guarantee)

1. **Window isolation** — each fold runs on a `config.model_copy` bounded to that fold's `[start, end]`; the OOS fold's `start == train_end`, so it can never consume train-window data.
2. **Within-window ceiling** — `_execute_window` keeps the 2.4 `as_of` ceiling: the benchmark is capped at the portfolio's *own* last date inside the fold, so a later benchmark bar never leaks into the fold's metrics.

### Scope / non-goals

- Report rendering (2.6) is still untouched.
- No ORM schema change, no new metric functions — only splitting + orchestration + persistence.

## Sprint 2.4 — Research Runner (2026-07-17)

Sprint 2.4 fills the `src/research/runner.py` stub with `ResearchRunner`, the
orchestration + persistence layer that chains the engines shipped in 1.16 / 2.2 /
2.3 into one runnable, persistable experiment — and adds the `research run` CLI
that drives it. No new metric math: it reuses `PortfolioBacktest.from_config`,
`compute_metrics`, `BenchmarkEngine.compare`, and `ExperimentRegistry` exactly as
they are.

### Added

- `src/research/runner.py` — `ResearchRunner(data_manager=None, portfolio_fn=None, benchmark_engine=None, config=None).run(config, session=None, notes=None) -> ExperimentResult`. Pipeline: resolve candidates (universe XOR codes via `UniverseEngine`) → portfolio backtest (injected `portfolio_fn` seam, default `PortfolioBacktest.from_config`) → `compute_metrics` → `BenchmarkEngine.compare` → persist → return `ExperimentResult` keyed by window `"full"`.
- `src/research/registry.py` — three persistence helpers (`record_metrics` / `record_equity` / `mark_done`); all ORM writes stay in the registry. `record_metrics` coerces non-finite values (`inf`/`nan`) to `None` (sqlite-safe); `record_equity` serialises the curve as `{iso_date: value}` JSON; `mark_done` sets `status="done"` + `finished_at` (tz-aware UTC, naive column).
- `research run` CLI — `research run --name/--universe/--codes/--strategy/--start/--end/--benchmark/--metrics [--config] [--dry-run]`; reuses the 2.1 `_resolve_cli_experiment_config` helper. Dry-run prints the resolved config and never calls the runner.
- `research/__init__.py` — export `ResearchRunner`.
- `tests/test_research.py` — six new cases: end-to-end run persists metrics + equity and matches the independent benchmark reference; no-look-ahead (extra later benchmark bar never leaks); missing benchmark ⇒ `DataError`; unknown benchmark key ⇒ `ConfigError`; empty candidate set ⇒ `DataError`; `research run --dry-run` persists nothing.

### Changed

- Benchmark-relative metrics are stored under a `bench_` prefix (`bench_excess_return` / `bench_alpha` / `bench_beta` / `bench_tracking_error` / `bench_information_ratio`) alongside the portfolio metrics in `ExperimentMetric`.
- No-look-ahead ceiling is the **portfolio's own last date** (not the calendar experiment end), so a later benchmark bar cannot leak into `benchmark_return` during the metrics step.

### Scope / non-goals

- Single full-range window (`"full"`); walk-forward / OOS (2.5) and report rendering (2.6) are untouched.
- No ORM schema change, no new metric functions — only wiring + persistence.

## Sprint 2.3 — Benchmark Comparison (2026-07-16)

Sprint 2.3 fills the `src/research/benchmark.py` stub with a real
`BenchmarkEngine` that compares an experiment's equity curve against a benchmark
index pulled through `DataManager.get_index_daily` (the single data entry point,
with a no-look-ahead `as_of` ceiling). No new metric math leaves
`src/backtest/metrics.py`; the benchmark-relative maths (alpha/beta/TE/IR) lives
in `benchmark.py` and reuses the promoted `daily_returns` helper. No ORM/CLI
change — `BenchmarkConfig` (2.0), `ExperimentConfig.benchmark` (2.0) and the
`research init --benchmark` flag (2.1) already exist; the engine is consumed by
the 2.4 runner.

### Added

- `src/research/benchmark.py` — `BenchmarkEngine.compare(portfolio_equity, benchmark_code, range, risk_free=None, as_of=None)` returning a typed `BenchmarkComparison` dataclass (`+ to_dict()`), with five metrics computed on the inner-joined date window:
  - `excess_return` — portfolio period return minus benchmark period return (scale-invariant).
  - `beta` — `Cov(r_p, r_b) / Var(r_b)`; flat benchmark (`Var==0`) ⇒ `0.0`.
  - `alpha` — annualised CAPM alpha `(mean(excess_p) − beta·mean(excess_b)) × 252`.
  - `tracking_error` — annualised std of active returns `std(r_p − r_b) × √252`.
  - `information_ratio` — `mean(r_p − r_b) × 252 / tracking_error`; `TE==0` ⇒ `0.0`.
- `IndexDataSource` Protocol (mirrors `DataProvider`) so the data dependency is structurally injectable/testable.
- `research/__init__.py` — export `BenchmarkEngine` + `BenchmarkComparison`.
- `tests/test_research.py` — six cases: β=1 (equal), β=0 (flat portfolio), hand-checked five-metric values, no-look-ahead (default cap + explicit `as_of`), missing benchmark ⇒ `DataError`, unknown key ⇒ `ConfigError`.

### Changed

- `src/backtest/metrics.py` — promote private `_daily_returns` → public `daily_returns` (visibility-only; `compute_metrics` signature unchanged) so return math lives in one place and `benchmark.py` reuses it.

### No-look-ahead

- `as_of` defaults to `max(portfolio_equity.index)` and is passed straight to `get_index_daily`, so the benchmark fetch can never include data the portfolio could not have seen; an invariant test enforces this.

## Maintenance — CI gate hardening (2026-07-16)

The GitHub Actions CI ran `ruff` / `black` / `mypy` / `pytest` against
**unpinned** dev dependencies. Every time a new black/ruff/mypy release shipped,
the floating install diverged from the local venv and the `black --check .` gate
failed on otherwise-correct code (the 2.1 run #24 failure was this exact case).

### Changed

- `requirements.txt` — pin the gate toolchain to the versions already used in the
  local venv so CI reproduces local results:
  - `black==26.5.1`
  - `ruff==0.15.21`
  - `mypy==2.3.0`
  - `pytest==9.1.1`
- No source changes; `black .` is a no-op at the pinned version (68 files unchanged).

### Notes

- This also unblocks the three Sprint 2.0/2.1/2.2 commits that were authored
  locally but never pushed — remote `main` was still pre-2.0, so CI kept running
  against stale code. Pushing them together with the pin makes the gate stable.

## Sprint 2.2 — Metrics Extension (2026-07-16)

Sprint 2.2 adds the five performance metrics GPT's Phase 2 plan wanted — but
**into the existing `src/backtest/metrics.py` dispatcher**, not a new
`research/metrics.py` (forbidden by the 2.0 frozen decision). Pure functions
only; no signature change to `compute_metrics`, no ORM/CLI change, no network.

### Added

- `src/backtest/metrics.py` — five new scalar metrics:
  - `profit_factor` — gross profit / gross loss over daily equity returns (blotter carries no per-trade PnL); `inf` when no losing day, `0.0` when flat.
  - `calmar` — `cagr / abs(max_drawdown)`; `0.0` when `max_drawdown == 0`.
  - `avg_holding_days` — mean calendar-day gap between consecutive rebalances (from `trades["date"]`); `0.0` when `< 2` trades.
  - `max_consecutive_losses` — longest run of consecutive down days.
  - `exposure` — fraction of bars holding a non-zero weight, reconstructed from cumulative `weight_change` over the equity index.
  - All five registered in `compute_metrics`'s `available` dict (now selectable via `BacktestConfig.metrics`).
- `tests/test_backtest.py` — 10 hand-checked unit tests (each metric + edge cases: flat equity, no-drawdown, `< 2` trades, no trades).

### Frozen decisions (carried from 2.2 design, §6)

- D1 The five metrics are **not** added to the default `BacktestConfig.metrics` list — registered only in the dispatcher, so they are selectable without changing existing backtest outputs / snapshots.
- D2 `profit_factor` uses daily-return gross profit / gross loss (not per-trade PnL).
- D3 `exposure` reconstructs the held weight from cumulative `weight_change` over `equity.index`.
- D4 Edge values: `profit_factor` `inf` (no loss) / `0.0` (flat); `calmar` `0.0` (mdd==0); `avg_holding_days` `0.0` (`< 2` trades); `max_consecutive_losses` `0` (none).

### Notes

- Fully backward compatible: `compute_metrics` signature unchanged; the 2.1 `research` CLI and all existing callers unaffected. These metrics become the vocabulary for benchmark (2.3) / runner (2.4) / walk-forward (2.5) / report (2.6).
- All four gates green: ruff / black / mypy (68 files) / pytest 201 passed, 1 skipped.

## Sprint 2.1 — Research CLI Surface (2026-07-16)

Sprint 2.0 shipped the `ExperimentConfig` / `ExperimentRun` / `ExperimentRegistry`
classes and config wiring. Sprint 2.1 adds the command-line surface that the
Phase 2 plan owed under "2.1 — Registry & Config": a `research` Typer sub-app
(`init | list | show | delete`) plus a complete delete cascade that also clears
an experiment's `ExperimentMetric` / `ExperimentEquity` child rows.

### Added

- `main.py` — `research` Typer sub-app mounted on the root app (`app.add_typer(research_app, name="research")`).
  - `research init` — accepts either CLI flags (`--name --strategy --start --end --universe|--codes --benchmark --metrics --walk-forward --seed --notes`) **or** `--config <file.json|yaml>`; conflicts resolved with `--dry-run` (prints config, persists nothing). `--codes` and `--metrics` take comma-separated values. `--universe` and `--codes` are mutually exclusive; `--universe` is resolved against `UniverseEngine` and rejected (exit 1) if empty/unknown; `--strategy` is validated against `cfg.strategies.enabled` (exit 2 if absent).
  - `research list` — newest-first table of `RUN_ID | NAME | STATUS | CREATED_AT`.
  - `research show <run_id>` — full run metadata + validated `ExperimentConfig` JSON.
  - `research delete <run_id>` — cascades to `ExperimentMetric` / `ExperimentEquity`, then removes the run.
- `src/research/registry.py` — `delete` now deletes child `ExperimentMetric` / `ExperimentEquity` rows before the `ExperimentRun` (explicit cascade; no FK `ondelete`, per frozen decision D4).
- `tests/test_research.py` — 7 new CLI + cascade tests: init via flags / config file / both-sources reject / unknown-universe reject / dry-run / list-show-delete lifecycle / registry delete cascade.

### Frozen decisions (carried from 2.0 design, §10)

- D1 Typer sub-app `research init|list|show|delete`.
- D2 `universe` column stores the pool **name** only; code resolution deferred to the runner (2.4).
- D3 `--config` accepts both JSON and YAML.
- D4 Delete uses an explicit child-row cascade (no FK `ondelete`).
- D5 `WalkForwardSpec` is persisted now via `--walk-forward TRAIN TEST STEP`.
- D6 `init` includes `--dry-run`.
- D7 `init` validates `--strategy` against enabled strategies.

### Notes

- `ExperimentRegistry` still carries no run logic; the CLI only persists the
  frozen `ExperimentConfig`. Execution (runner) lands in Sprint 2.x.
- All four gates green: ruff / black / mypy (68 files) / pytest 191 passed, 1 skipped.

## Sprint 2.0 — Research Foundation (2026-07-16)

Phase 2 foundation: index/benchmark data + experiment persistence + `src/research/` skeleton. No forward-looking (2.1–2.6) logic — future modules are stubs that raise `NotImplementedError` with their target sprint.

### Added

- `src/data/models.py` — `IndexBar` ORM (separate table from `DailyBar`, `UniqueConstraint(code, date)`; nullable `volume`/`amount`).
- `src/data/provider.py` — `DataProvider.get_index_daily` added to the Protocol; `normalize_index_daily`; `AkShareProvider.get_index_daily` via `ak.index_zh_a_hist` (daily).
- `src/data/providers/astockdata.py` — `AStockDataProvider.get_index_daily` (deferred, raises `NotImplementedError`).
- `src/data/manager.py` — `sync_index` + `get_index_daily(..., as_of=...)` through the single `DataManager` entry; missing benchmark raises `DataError` (never silent).
- `src/core/config.py` — `BenchmarkConfig` (default `csi300`; csi300/csi500/csi1000/sh_composite index map) and `ResearchConfig` (experiment id prefix, metrics); wired into `AppConfig`.
- `config/settings.yaml` — `benchmark` and `research` sections.
- `src/research/models.py` — `ExperimentRun` (short-UUID string PK), `ExperimentMetric` (long-table form), `ExperimentEquity`.
- `src/research/experiment.py` — `WalkForwardSpec`, `ExperimentConfig` (frozen Phase 2 protocol; `universe`/`codes` mutually exclusive), `ExperimentResult`.
- `src/research/registry.py` — `ExperimentRegistry` CRUD (session-injected); no run logic.
- `src/research/{benchmark,runner,walk_forward,report}.py` — stubs only (Sprint 2.x pointers).
- `src/research/__init__.py` — public exports; explicit guard note: **no** `research/metrics.py` (metrics live in `src/backtest/metrics.py`).
- `tests/test_research.py` — 12 tests: index normalize/roundtrip, `as_of` no-look-ahead, missing-benchmark `DataError`, registry CRUD, metric uniqueness, config validation, UUID PK uniqueness, config wiring, network-gated real-index smoke.

### Frozen decisions

- `IndexBar` is a separate table from `DailyBar`.
- AKShare index interface: `index_zh_a_hist`.
- Experiment primary key: UUID (short-uuid string).
- `ExperimentMetric`: long-table design.
- No `research/metrics.py`; reuse `src/backtest/metrics.py`.
- `DataManager` remains the sole data entry point.
- `ExperimentConfig` is the frozen Phase 2 experiment protocol.

### Notes

- No look-ahead: `get_index_daily` honours an `as_of` ceiling identical to the equity path.
- Scope strictly limited to Sprint 2.0; walk-forward / runner / benchmark-alignment / report land in 2.1–2.6.

## Sprint 1.16 — Portfolio Backtest (2026-07-15)

### Added

- `src/backtest/portfolio.py` — `PortfolioBacktest` + `PortfolioResult`: selects Top-N candidates by composite score and builds an equal-weight rebalanced portfolio; reuses single-code equity curves from `BacktestEngine`; benchmark = buy & hold across the full candidate set. `rank_fn` / `equity_fn` are injectable for testing.
- `src/backtest/__init__.py` — public exports `PortfolioBacktest`, `PortfolioResult`.
- `main.py` — new `portfolio` command.
- `tests/test_portfolio.py` — selection, equal-weight combination, benchmark, no-data zeros, injectable stubs.
- `Sprint1.16-Portfolio-Backtest-Design.md` — design doc.

### Notes

- No future functions: the selection window and rebalance both converge on the per-candidate `as_of` ceiling.
- This is the equal-weight Top-N baseline; richer weighting / risk-based rebalancing is deferred.

## Sprint 1.15 — Scheduler + Notifier (2026-07-15)

### Added

- `src/scheduler/notify.py` — `Notifier` abstraction + three implementations: `ConsoleNotifier`, `FileNotifier`, `WebhookNotifier` (best-effort HTTP POST; no-op when URL is `None`); `build_notifier(SchedulerConfig)`.
- `src/scheduler/engine.py` — `Scheduler` with `run_ntimes(task, interval, n)` and `run_loop(task, interval, stop_event)`; task exceptions are caught so the loop never dies.
- `src/scheduler/__init__.py` — public exports.
- `core/config.py` — `SchedulerConfig` (notifier_type / webhook_url / file_path), wired into `AppConfig.scheduler`.
- `config/settings.yaml` — `scheduler` section.
- `main.py` — new `schedule` command: `--report [CODES...] [--universe POOL] [--backtest]`, `--watchlist [--backtest]`, `--every N` (minutes) / `--once`.
- `tests/test_scheduler.py` — offline tests (console/file, no-op webhook, interval ticking, error isolation).
- `Sprint1.15-Scheduler-Design.md` — design doc.

### Notes

- Runs without any external credentials; the webhook is a no-op when `webhook_url` is unset.
- Reuses existing report/watchlist generation; only repeats it on an interval, so the `as_of` window stays look-ahead free.

## Sprint 1.14 — Report HTML (2026-07-15)

### Added

- `src/report/engine.py` — `DailyReport.to_html(include_detail=True)`: self-contained HTML with inline CSS and inline SVG horizontal bar charts (bars normalised on composite score), full table (incl. 1.10 backtest columns), and a detail card grid. Text is HTML-escaped.
- `core/config.py` — `ReportConfig.format: Literal["markdown","json","html"]`.
- `main.py` — `report ... --format html` (optionally `--out report.html`).
- `tests/test_report.py` — HTML output assertions (doctype, svg, bars, codes, 综合分, backtest columns when enabled).
- `Sprint1.14-Report-HTML-Design.md` — design doc.

### Notes

- Zero-dependency and offline-openable; the render layer introduces no new data or window, so no future functions are introduced.

## Sprint 1.13 — Universe / Stock-pool (2026-07-15)

### Added

- `src/universe/models.py` — `UniversePool` ORM (`name` PK, `description`, `codes_json`, `created_at`, `updated_at`).
- `src/universe/engine.py` — `UniverseEngine` (session-bound, shared DB): `add_codes` (dedupe + lexical sort), `remove_codes`, `get_codes`, `exists`, `list_pools`, `delete`.
- `src/universe/__init__.py` — public exports.
- `main.py` — new `universe` command (`add|remove|list|show|delete`) and `report --universe POOL` (mutually exclusive with positional codes).
- `tests/test_universe.py` — 6 isolated in-memory SQLite tests.
- `Sprint1.13-Universe-Design.md` — design doc.

### Notes

- `Universe` only answers "where do the codes come from"; it does not change ranking/backtest semantics. Watchlist keeps its own membership table and does not depend on universe.

## Sprint 1.12 — Backtest Cache (2026-07-15)

### Added

- `src/backtest/cache.py` — `BacktestCache` ORM (`code`, `params_hash`, `start`, `end`, `signal_col`, `metrics_json`, `equity_json`, `created_at`; unique on `(code, params_hash)`) + `get_cached()` / `store()` (best-effort).
- `src/backtest/engine.py` — `run_code` now does get-or-compute against the cache; `BacktestEngine.run_code(use_cache=True)`.
- `core/config.py` — `BacktestConfig.cache_enabled` (default `True`).
- `config/settings.yaml` — `backtest.cache_enabled`.
- `tests/test_backtest.py` — cache hit skips recompute / distinct codes / hash determinism.
- `Sprint1.12-Backtest-Cache-Design.md` — design doc.

### Notes

- `params_hash` folds every input that changes the simulation (signal column, cost, initial cash, max position, benchmark flag, start/end), so a new `as_of` naturally misses.
- All cache access is best-effort: any DB error is caught and degrades to live computation, so caching never blocks a backtest.

## Sprint 1.11 — Watchlist Backtest Persistence (2026-07-15)

### Added

- `src/watchlist/models.py` — `BacktestPoint` ORM (`as_of`, `code`, `total_return`, `max_drawdown`, `sharpe`, `benchmark_return`, `created_at`; unique on `(as_of, code)`; fields nullable so no-data codes do not get a point).
- `src/watchlist/engine.py` — `BacktestSummary` dataclass; `WatchlistMember.backtest` / `prev_backtest`; `WatchlistDigest.backtest_included`; lazy `_get_bt_engine` + `_backtest_snapshot` / `_upsert_backtest_point` / `_backtest_point_map`; snapshot persists points and computes return deltas vs the previous point.
- `src/watchlist/__init__.py` — export `BacktestPoint` / `BacktestSummary`.
- `core/config.py` — `WatchlistConfig.include_backtest` (default `False`).
- `main.py` — `watchlist snapshot --backtest`.
- `tests/test_watchlist.py` — backtest coverage incl. `test_snapshot_backtest_no_lookahead`.
- `Sprint1.11-Watchlist-Backtest-Design.md` — design doc.

### Notes

- No future functions: same `as_of` ceiling as 1.10; deltas are a pure read of stored history. Backtest result rendering appends a "## 回测表现" section with return deltas.

## Sprint 1.10 — Report Backtest Enrichment (2026-07-15)

### Added

- `src/report/engine.py` — `ReportRow` gains `bt_total_return` / `bt_max_drawdown` / `bt_sharpe` / `bt_benchmark_return`; `DailyReport` gains `backtest_included`; `ReportEngine` gains a lazy `_get_bt_engine()` and `_backtest_snapshot`, and renders backtest columns in markdown/json.
- `core/config.py` — `ReportConfig.include_backtest` (default `False`).
- `config/settings.yaml` — `report.include_backtest`.
- `main.py` — `report ... --backtest`.
- `tests/test_report.py` — backtest coverage (injectable `backtest_fn` stub).
- `Sprint1.10-Report-Backtest-Design.md` — design doc.

### Notes

- Per-candidate backtest (one backtest per Top-N candidate), not portfolio backtest (deferred to 1.16).
- No future functions: backtest window `[start_date, as_of]` reuses the report's `as_of` ceiling. Only Top-N candidates are backtested to bound cost.

## Sprint 1.9 — Watchlist Tracker (2026-07-15)

### Added

- `src/watchlist/models.py` — two ORM models on `core.database.Base`: `WatchlistItem` (membership, soft-delete via `removed_at`) and `RankingPoint` (daily snapshot: as_of, code, full cross-sectional rank, composite_score, scores_json; unique on (as_of, code)).
- `src/watchlist/engine.py` — `WatchlistEngine` (add/remove/list_active/is_member, `snapshot` ranks the whole watchlist and persists every member including those that fall out of the Top-N, `history`, `deltas`) plus `WatchlistDigest` / `WatchlistMember` with `to_markdown()` / `to_json()`. `deltas` is a pure read of stored history (no network, no look-ahead).
- `src/watchlist/__init__.py` — public exports.
- `Sprint1.9-Watchlist-Design.md` — design doc.
- `core/config.py` — `WatchlistConfig` (alert_rank_jump) wired into `AppConfig.watchlist`.
- `config/settings.yaml` — `watchlist` section (alert_rank_jump=5).
- `main.py` — new `watchlist` command: `add/remove/list/snapshot/history/digest`.
- `tests/test_watchlist.py` — 12 tests (FakeSE + FakeDM + isolated temp SQLite): membership, full-rank snapshot incl. no-data codes, the six-state delta machine (new/dropped/up/down/steady/no_data), history ordering, as_of no-look-ahead, markdown/json rendering, real-config wiring, CLI smoke.

### Notes

- Reuses RankingEngine's full cross-section (`scored`) to compute a full cross-sectional rank so a watched code that drops out of the Top-N is still tracked; no new metric math is introduced.
- No future functions: `snapshot` drives RankingEngine with the same `as_of` ceiling; `deltas` only reads already-stored history.
- Rank relativity is internal to the watchlist (self-relative ranking), matching the "track my watched set" semantics.
- A code with no data at the cross-section is intentionally left without a point, so the next `deltas` reports it as `dropped` (not a null `no_data` row). The `no_data` state is reserved for a present-but-unrankable point (e.g. NaN composite score).

## Sprint 1.8 — Daily Report Engine (2026-07-15)

### Added

- `src/report/engine.py` — `ReportEngine` + `DailyReport` + `ReportRow`: a presentation/aggregation layer over the ranking output. It drives `RankingEngine` with its own `top_n`/`as_of`, takes the Top-N candidates, and enriches each with a latest price snapshot (close, daily change %, trade date, data-freshness flag) fetched from the `DataManager`. Renders to markdown (`to_markdown`) or json (`to_json`). No new metric math is introduced.
- `src/report/__init__.py` — public exports `ReportEngine`, `DailyReport`, `ReportRow`.
- `src/report` package + `Sprint1.8-Daily-Report-Design.md` (design doc).
- `core/config.py` — `ReportConfig` (top_n, as_of, format, freshness_days, include_detail), wired into `AppConfig.report`.
- `config/settings.yaml` — `report` section (top_n=20, as_of=null, format=markdown, freshness_days=5, include_detail=true).
- `main.py` — new `report` command: `report --list`, `report CODE [CODE ...] [--top-n N] [--as-of YYYY-MM-DD] [--start ...] [--end ...] [--format markdown|json] [--out FILE]`; prints (or writes) the daily research report.
- `tests/test_report.py` — sorted/scored output, price snapshot + daily change, Top-N cutoff, `as_of` cross-section with no-look-ahead snapshot, data-freshness (stale) flag, empty result, markdown table/detail toggles, json round-trip, dataclass helpers, real-config wiring, and a CLI smoke test.

### Notes

- No look-ahead is preserved end-to-end: the price snapshot ceiling follows the same `as_of` the ranking layer uses, so a candidate's close / daily change never sees a bar dated after the cross-section. A dedicated test asserts the snapshot uses only bars at/before `as_of`.
- The report is an aggregation/rendering layer only; it reuses the ranking composite score and adds no factor/indicator/metric computation.
- Daily change is computed only when at least two bars are visible; with a single visible bar it is reported as `None` rather than fabricated.

## Sprint 1.7 — Ranking Engine (2026-07-15)

### Added

- `src/ranking/engine.py` — `RankingEngine`: cross-sectional composite-score ranking over candidate stocks. Reuses `StrategyEngine` to produce `score_<name>` columns, then combines them (configured weights, normalised by sum of absolute weights) into a composite score per stock at a chosen cross-section (latest bar, or `as_of`), sorts descending, and returns the Top-N watch-list plus the full scored cross-section.
- `src/ranking/__init__.py` — public export `RankingEngine`.
- `src/ranking` package + `Sprint1.7-Ranking-Design.md` (design doc).
- `core/config.py` — `DimensionSpec` (strategy + weight, weight may be negative) and `RankingConfig` (top_n, as_of, dimensions), wired into `AppConfig.ranking`.
- `config/settings.yaml` — `ranking` section (top_n=20, as_of=null, dimensions=null => all enabled strategies equal weight).
- `main.py` — new `ranking` command: `ranking --list`, `ranking CODE [CODE ...] [--top-n N] [--as-of YYYY-MM-DD] [--start ...] [--end ...]`; prints a ranked Top-N table with composite + per-strategy score columns.
- `tests/test_ranking.py` — composite score correctness (equal / explicit / negative weights), Top-N cutoff, `as_of` cross-section selection, no-look-ahead guard, missing `code` column `DataError`, missing score column `DataError`, real-config wiring, and a CLI smoke test.

### Notes

- Sorting semantics (user-confirmed): each candidate keeps its strategy `score_<name>` at the cross-section; those scores are combined into a composite and sorted descending. This is a thin layer over the strategy engine and inherits the no-look-ahead guarantee from Sprint 1.5.
- `as_of` filters on the `date` column (get_daily returns an integer-indexed frame with a `date` column), so no future bar is ever visible at the cross-section.
- Cross-instrument allocation beyond ranking is out of scope; this sprint produces a ranked candidate list, not a portfolio.

## Sprint 1.6 — Backtest Engine (2026-07-15)

### Added

- `src/backtest/cost.py` — `CostModel`: A-share transaction cost model. Per-side commission (wan 2.5, min RMB 5), stamp tax (wan 5, sell-only), transfer fee (wan 0.1, both sides), and slippage (configurable, default 0). Pure, unit-testable `charge(notional, is_sell)`.
- `src/backtest/metrics.py` — pure performance-metric functions: `total_return`, `cagr`, `max_drawdown`, `sharpe`, `sortino`, `win_rate`, `num_trades`, `turnover`, `benchmark_return`, plus a `compute_metrics` dispatcher that selects metrics from `BacktestConfig.metrics` and raises `ConfigError` on unknown names.
- `src/backtest/engine.py` — `BacktestEngine`: composes `StrategyEngine` + `CostModel` + metrics. Reuses `Portfolio.positions` for target weights, then layers A-share costs on top of the no-cost mark-to-market primitive. Produces a cost-aware equity curve, a trade blotter, and a metrics dict. Supports single-code and per-code grouped (multi-code) backtests.
- `src/backtest/__init__.py` — public exports.
- `core/config.py` — `CostConfig` / `BacktestConfig` models, wired into `AppConfig.backtest` (strategy, initial_cash, max_position, risk_free, metrics list, benchmark flag, cost).
- `config/settings.yaml` — `backtest` section with `weighted_momentum` as the default strategy and 2024 A-share default rates.
- `main.py` — new `backtest` command: `backtest --list`, `backtest CODE [--strategy ...] [--start ...] [--end ...]`; prints metric summary + benchmark + last 10 equity rows.
- `tests/test_backtest.py` — cost model, metric correctness, cost-aware <= no-cost, trade blotter, `max_position` clamp, no-look-ahead truncation invariant, missing-signal `DataError`, unknown-metric `ConfigError`, full-pipeline integration on synthetic data, and a CLI smoke test.

### Notes

- No look-ahead is preserved: the position held at bar t is decided at t-1 close and earns the t-1 to t return; rebalance costs are charged at t-1 close using only data known by then. A truncation test guards this.
- Single instrument only (or per-code grouped); cross-instrument allocation is deferred to Sprint 1.7. Shorting (-1) is reserved and treated as FLAT with a warning.
- The cost notional is the traded dollar amount (absolute delta weight times equity); the design note literal price times equity product was a typo and is not used.

## Sprint 1.5 — Strategy Engine (2026-07-14)

### Added

- `src/strategies/signal.py` — `SignalType` enum (SHORT=-1 / FLAT=0 / LONG=1) plus `to_position` / `coerce` helpers mapping a signal to a target position weight. A-share first: long and flat are fully supported, short is reserved for future extension.
- `src/strategies/base.py` — `BaseStrategy` base class + registry (`register`, `build`, `available`). Strategies read factor columns and emit a `signal_<name>` (and optional `score_<name>`) column; causal and future-leak free.
- `src/strategies/impl.py` — two strategy types: `weighted` (normalise each factor to [-1,1], form a weighted composite score, map to a signal via buy/sell thresholds) and `rule` (boolean AND/OR of factor conditions -> long/flat). A missing factor column raises `DataError`; malformed params raise `ConfigError`.
- `src/strategies/engine.py` — `StrategyEngine`: composes `FactorEngine` (indicators -> factors -> strategies), builds from `IndicatorConfig` + `FactorConfig` + `StrategyConfig`, computes per-stock, and reads bars through `DataManager` via `compute_code`.
- `src/strategies/portfolio.py` — `Portfolio`: turns signals into positions and marks the book to market with close-to-close returns, using only data known at bar *t* (the position held at t-1 earns the t->t+1 return) — no look-ahead.
- `src/strategies/__init__.py` — public exports.
- `core/config.py` — `WeightSpec` / `WeightedParams` / `ConditionSpec` / `RuleParams` / `StrategySpec` / `StrategyConfig` models, wired into `AppConfig.strategies`.
- `config/settings.yaml` — `strategies.enabled` default set: `weighted_momentum` (8-factor weighted composite) and `golden_cross_rule` (MA cross AND MACD cross AND RSI not overbought).
- `main.py` — new `strategies` command: `strategies --list` and `strategies CODE [--name ...] [--start ...] [--end ...]`.
- `tests/test_strategies.py` — strategy correctness, engine orchestration, missing-column `DataError`, malformed-param `ConfigError`, `Portfolio` position and equity behaviour, and a **no-future-leak** invariant test at the engine level (the signal at bar *t* computed on the full pipeline equals the value computed on bars `0..t`).

### Notes

- Strategies reference the factor **output columns** (for example `ma_dist_20`, `macd_cross`, `rsi_signal_14`) produced by the factor layer, not the factor registry names — keeping the factor/strategy wiring fully config-driven.
- The whole indicators -> factors -> strategies pipeline inherits the *禁止未来函数* guarantee: a signal at bar *t* depends only on data at bars `<= t`.
- `Portfolio` is the bridge to the backtest engine (Sprint 1.6): it derives positions from signals but does not yet apply costs, slippage, or sizing.

## Sprint 1.4 — Factor Engine (2025-07-14)

### Added

- `src/factors/base.py` — `BaseFactor` base class + registry (`register`, `build`, `available`). Factors are pure, causal functions built on top of indicator columns.
- `src/factors/impl.py` — eight factors, all config-driven and **future-leak free**: `ma_distance`, `ma_cross`, `rsi_signal`, `macd_cross`, `kdj_cross`, `vol_ratio`, `boll_position`, `momentum`.
- `src/factors/engine.py` — `FactorEngine`: composes the `IndicatorEngine` (indicators first, then factors), builds from `IndicatorConfig` + `FactorConfig`, computes per-stock, and reads bars through `DataManager` via `compute_code`.
- `src/factors/__init__.py` — public exports.
- `core/config.py` — `FactorSpec` / `FactorConfig` models, wired into `AppConfig.factors`.
- `config/settings.yaml` — `factors.enabled` default set (each factor references the indicator windows produced by the indicator layer).
- `main.py` — new `factors` command: `factors --list` and `factors CODE [--name ...]`.
- `tests/test_factors.py` — factor correctness, engine orchestration, missing-column `DataError`, and a **no-future-leak** invariant test (indicators + factor at bar *t* computed on the full series equals the value computed on bars `0..t`).

### Notes

- Factors only read columns already present in the frame (indicator outputs + raw `close`/`volume`), so the indicator + factor pipeline inherits the *禁止未来函数* guarantee.
- A factor whose required indicator column is missing (misconfigured `factors` vs `indicators`) raises `DataError` immediately.
- `Roadmap.md` added to track sprint status across the development workflow.

## Sprint 1.3 — Indicator Engine (2025-07-13)

### Added

- `src/indicators/base.py` — `BaseIndicator` base class + registry (`register`, `build`, `available`). Indicators are pure, causal functions of historical bars.
- `src/indicators/impl.py` — seven indicators, all config-driven and **future-leak free**: `ma`, `ema`, `rsi`, `macd`, `kdj`, `boll`, `vol_ma`.
- `src/indicators/engine.py` — `IndicatorEngine`: builds from `IndicatorConfig`, computes per-stock (`compute`), and reads bars through the single data entry via `compute_code(data_manager, ...)`.
- `src/indicators/__init__.py` — public exports.
- `core/config.py` — `IndicatorSpec` / `IndicatorConfig` models, wired into `AppConfig.indicators`.
- `config/settings.yaml` — `indicators.enabled` default set (multi-window `ma` demonstrates parameterization).
- `main.py` — new `indicators` command: `indicators --list` and `indicators CODE [--name ...]`.
- `tests/test_indicators.py` — indicator correctness, engine orchestration, and a **no-future-leak** invariant test (value at bar *t* computed on the full series equals the value computed on bars `0..t`).

### Notes

- Every indicator value at bar *t* depends only on data at bars `<= t` (rolling windows / EMA recursions / trailing min-max). The test-suite enforces this automatically.
- Indicators obtain prices exclusively through `DataManager`, preserving the single-data-entry principle.

## Sprint 1.2 — Database Layer (2025-07-13)

### Added

- `src/data/models.py` — SQLAlchemy ORM models: `Stock`, `DailyBar` (unique `(code, date)`), `SyncState`.
- `src/data/provider.py` — `DataProvider` protocol + `AkShareProvider` with AKShare column normalization.
- `src/data/manager.py` — `DataManager`, the single data entry point: `sync_stock_list`, `sync_daily`, `get_daily`, `get_stock_list`, `last_sync_date`.
- `src/data/providers/astockdata.py` — alternative `AStockDataProvider` (akshare-free, direct HTTP via Baidu K-line + Eastmoney stock list) selectable through `data.source`.
- `main.py` — new CLI commands: `sync --list`, `sync --code`, `bars`.
- `tests/test_data.py` + `tests/conftest.py` — data-layer tests using `FakeProvider` and mocked HTTP endpoints.
- `.github/workflows/ci.yml` — GitHub Actions CI running `pytest`, `ruff`, `black --check`, `mypy`.

### Changed

- `config/settings.yaml` — added `data.source` (`akshare`/`astockdata`) and `data.adjust` (`qfq`/`hfq`).
- `src/core/database.py` — `get_engine` / `get_sessionmaker` now accept an explicit URL/engine so `DataManager` can use its own config.
- `pyproject.toml` / `requirements.txt` — added `requests` for the a-stock-data HTTP path.

### Notes

- `AkShareProvider` remains the **default** and supports forward-adjusted bars via `data.adjust`.
- `AStockDataProvider` is a direct-HTTP fallback that returns raw (unadjusted) Baidu prices; useful when AKShare is unstable.

## Sprint 1.1 — Project Foundation (2025-07-13)

### Added

- Project scaffold: `pyproject.toml`, `config/settings.yaml`, `.env.example`, updated `.gitignore`.
- `src/core/` — `config` (Pydantic + YAML/.env), `logging` (Loguru), `database` (SQLAlchemy 2.x), `exceptions` (hierarchy).
- `main.py` — Typer CLI entry point (`version`, `info`).
- `tests/test_core.py` — smoke tests for config, logging, database, CLI.
- `README.md` — setup, quality gates, project layout, and planned modules.
