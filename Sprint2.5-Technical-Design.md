# Sprint 2.5 — Walk-forward / Out-of-sample (Technical Design)

> Status: **Technical design** for ChatGPT review + freeze before code lands.
> Parent contract: `Phase2-Implementation-Plan.md` §4 "Sprint 2.5 — Walk-forward / Out-of-sample".
> Foundation already on `main`: Sprints 2.0 (persistence ORM + index data + `BenchmarkConfig`,
> `ExperimentConfig.walk_forward`, `ExperimentResult` window dict), 2.1 (`research` CLI + registry),
> 2.2 (metric maths), 2.3 (`BenchmarkEngine.compare`), 2.4 (`ResearchRunner.run` with `window="full"`).
> 2.5 turns the single-range runner into a **rolling train/test** validator and tags the OOS folds.
> Coding rule carried from Phase 1 / 2.0: **no new metric math outside `src/backtest/metrics.py`**.

## 1. Context

Phase 2 answers "which strategy is actually best?" — not by eyeballing one backtest, but by
**out-of-sample proof**. Sprints 2.0–2.4 give us a reproducible single-range experiment
(`ResearchRunner.run` → one `window="full"` result). What is **missing** is the walk-forward frame
that splits a date range into rolling train/test windows, runs the experiment per window, and
reports **IS vs OOS** degradation.

`src/research/walk_forward.py` is still the `NotImplementedError` stub. The persistence schema
already supports it: `ExperimentMetric`/`ExperimentEquity` carry `window` + `is_oos` columns, and
`ExperimentResult.metrics/equity` are keyed by window tag. 2.5 only has to **fill the splitter +
runner** and reuse `ResearchRunner`'s single-window logic.

## 2. Scope (strictly 2.5)

In scope:
- Replace the `WalkForwardSplitter` stub in `src/research/walk_forward.py` with a real `split()`.
- Add `WalkForwardRunner.run(...)` that orchestrates rolling windows and tags OOS folds.
- Refactor `ResearchRunner` to expose a single-window execution seam (internal `_execute_window`)
  so walk-forward reuses it **without duplicating** the backtest/metric/benchmark/persist logic.
  The public `ResearchRunner.run()` signature + full-range behaviour is **unchanged**.
- Aggregate IS vs OOS metric means and persist them as two summary windows (`is_agg` / `oos_agg`).
- Transparently dispatch `research run` to walk-forward when `config.walk_forward` is set.
- Unit tests incl. the mandatory no-look-ahead invariant (`tests/test_research.py`).

Out of scope: report rendering (2.6) — no Markdown/HTML; a real risk-free series (open Q #3);
any new metric math; configurable aggregation beyond simple per-metric mean; parameter retraining
(see §4 note — AROS strategies are rule-based, so IS/OOS here is time-segment validation, not
train→test parameter transfer).

## 3. Interface

```python
# src/research/walk_forward.py
from dataclasses import dataclass

@dataclass(frozen=True)
class WalkForwardFold:
    index: int
    train_start: str      # "YYYY-MM-DD"
    train_end: str
    test_start: str
    test_end: str


class WalkForwardSplitter:
    def split(self, spec: WalkForwardSpec, start: str, end: str) -> list[WalkForwardFold]: ...


class WalkForwardRunner:
    def __init__(
        self,
        data_manager: Any | None = None,
        portfolio_fn: PortfolioFn | None = None,
        benchmark_engine: BenchmarkEngine | None = None,
        config: AppConfig | None = None,
    ) -> None: ...

    def run(self, config: ExperimentConfig, session: Any = None, notes: str | None = None) -> ExperimentResult: ...
```

Notes:
- `WalkForwardRunner` takes the **same seam signature** as `ResearchRunner` (`data_manager` /
  `portfolio_fn` / `benchmark_engine` / `config`) so it can delegate the single-window work to
  `ResearchRunner._execute_window` and be unit-tested with the same fakes.
- `WalkForwardSpec` (frozen in 2.0) carries `train_years` / `test_years` / `step_years` (all int,
  in years). `None` on `ExperimentConfig.walk_forward` ⇒ single full-range run (delegated to
  `ResearchRunner.run`).
- `split()` returns folds in chronological order; the list is empty only when the range is too
  short for even one train+test window (caller raises `DataError`).

## 4. Splitting logic (`WalkForwardSplitter.split`)

Year offsets use `pd.Timestamp(start) + pd.DateOffset(years=N)` (handles 29-Feb roll-over safely;
not `date.replace(year=...)` which would crash on leap-day inputs).

```
cursor = start
folds = []
i = 0
while True:
    train_start = cursor
    train_end   = train_start + DateOffset(years=spec.train_years)
    test_start  = train_end                       # test begins exactly where train ends
    test_end    = test_start + DateOffset(years=spec.test_years)
    if test_end > end:                           # never extend past the experiment range
        break
    folds.append(WalkForwardFold(i, train_start, train_end, test_start, test_end))
    cursor = cursor + DateOffset(years=spec.step_years)   # roll forward by step
    i += 1
return folds
```

- `test_start == train_end` (inclusive start / exclusive end convention per A-share daily bars):
  the OOS window sees data **strictly after** the train window — the core no-look-ahead guarantee.
- A fold is included only when **its whole test window fits inside** `[start, end]`. Partial trailing
  windows are dropped (no short, non-comparable fold).
- Overlapping vs gapped windows are both supported by `step_years` (step < train+test ⇒ overlap;
  step > train+test ⇒ gap). The splitter does not special-case either.

> **Note on retraining:** AROS strategies are rule-based (a `strategy` name + fixed config in
> `ExperimentConfig`); there are no trainable parameters to fit on the train window. So each fold
> runs the **same configured strategy** on its train vs test slice — IS shows in-sample fit quality,
> OOS shows genuine out-of-sample behaviour. This is precisely the §2 "report IS vs OOS" contract and
> matches the frozen `ExperimentConfig` (no trainable-params field). If future sprints add learnable
> strategies, the train slice would feed parameter fitting; 2.5 does not need it.

## 5. Orchestration (`WalkForwardRunner.run`)

### 5.1 Refactor: `ResearchRunner._execute_window` (internal seam)
Extract the body of today's `run()` (resolve candidates → portfolio → metrics → benchmark → persist
that one window) into:

```python
def _execute_window(self, config: ExperimentConfig, session, *, window: str, run_id: str, is_oos: bool) -> ExperimentResult:
    # identical to today's run() steps 1-6, EXCEPT:
    #  - does NOT call reg.create() (run_id is passed in)
    #  - does NOT call mark_done()
    #  - record_metrics/record_equity use the passed `window` + `is_oos`
    #  - returns ExperimentResult keyed by `window`
```

`ResearchRunner.run()` becomes: `run_id = reg.create(...)` → `_execute_window(config, session,
window="full", run_id=run_id, is_oos=False)` → `mark_done(run_id)` → return the result. **Public
behaviour identical to 2.4** — no caller-visible change.

### 5.2 `WalkForwardRunner.run`
```
spec = config.walk_forward
if spec is None:
    return ResearchRunner(self._dm, self._portfolio_fn, self._benchmark_engine, self._config).run(config, session, notes)

folds = WalkForwardSplitter().split(spec, config.start, config.end)
if not folds:
    raise DataError("Range too short for walk_forward spec (need >= train+test years)")

reg = ExperimentRegistry(session)
run_id = reg.create(name=config.name, config_json=config.model_dump_json(), notes=notes)

results: dict[str, Mapping[str, float | None]] = {}
equity: dict[str, dict[str, float]] = {}
windows: list[str] = []

for f in folds:
    is_cfg  = config.model_copy(update={"start": f.train_start, "end": f.train_end})
    oos_cfg = config.model_copy(update={"start": f.test_start,  "end": f.test_end})
    is_res  = ResearchRunner(self._dm, self._portfolio_fn, self._benchmark_engine, self._config)._execute_window(
                  is_cfg, session, window=f"is_{f.index}", run_id=run_id, is_oos=False)
    oos_res = ResearchRunner(...)._execute_window(
                  oos_cfg, session, window=f"oos_{f.index}", run_id=run_id, is_oos=True)
    results[f"is_{f.index}"]  = is_res.metrics[f"is_{f.index}"]
    results[f"oos_{f.index}"] = oos_res.metrics[f"oos_{f.index}"]
    equity[f"is_{f.index}"]   = is_res.equity[f"is_{f.index}"]
    equity[f"oos_{f.index}"]  = oos_res.equity[f"oos_{f.index}"]
    windows += [f"is_{f.index}", f"oos_{f.index}"]

# 5.3 aggregation into two summary windows
results["is_agg"],  results["oos_agg"]  = _aggregate(results, windows, is_oos=True_side)
equity["is_agg"] = {}   # no meaningful aggregated curve; metrics-only summary
windows += ["is_agg", "oos_agg"]

reg.record_metrics(run_id, results["is_agg"], "is_agg", False)
reg.record_metrics(run_id, results["oos_agg"], "oos_agg", True)
reg.mark_done(run_id)
return ExperimentResult(run_id=run_id, metrics=results, equity=equity, windows=windows)
```

### 5.3 Aggregation (`is_agg` / `oos_agg`)
For every metric name present across folds, compute the **simple mean** of the IS (resp. OOS) values,
skipping `None` / non-finite entries (mirrors the `record_metrics` coercion contract). The aggregate
windows are persisted with `is_oos=True`/`False` accordingly so 2.6 can read them. Equity has no
aggregated curve (windows cover disjoint date ranges), so `is_agg`/`oos_agg` carry metrics only.

## 6. No-look-ahead invariant (mandatory per plan §5)

Two independent guarantees:

1. **Window isolation:** each fold runs `ResearchRunner._execute_window` on a `config.model_copy`
   bounded to that fold's `[start, end]`. The OOS fold's `start == train_end`, so its backtest reads
   only data **at or after** the train window's end — it can never consume train-window data.
2. **Within-window ceiling:** `_execute_window` reuses the 2.4 `as_of` ceiling (benchmark capped at
   the portfolio's own last date inside the fold), so no later benchmark bar leaks into the fold.

A 2.5 invariant test builds a `FakeDataManager` whose `get_index_daily` returns bars **beyond the
test window end** and asserts (a) the persisted `oos_*` benchmark metrics equal a reference computed
only on the in-window slice, and (b) the OOS fold's `start` equals the train fold's `end` (proving
the boundary is never crossed).

## 7. CLI (`research run` — transparent dispatch)

`research run` already builds an `ExperimentConfig` (2.1 `_resolve_cli_experiment_config` honours
`--walk-forward train,test,step`). After building it:

```
if exp_cfg.walk_forward is not None:
    result = WalkForwardRunner(...).run(exp_cfg, notes=notes)
else:
    result = ResearchRunner(...).run(exp_cfg, notes=notes)
```

On success, echo `run_id` + a short summary: IS vs OOS `total_return`, `sharpe`, `bench_excess_return`,
`bench_beta` (for the first fold + the aggregates). `--dry-run` prints the config without executing
(unchanged). No new flags.

## 8. Reuse map

| Need | Reuse |
|---|---|
| Candidate resolution | `UniverseEngine.get_codes` (1.13) — via `_execute_window` |
| Portfolio equity/trades | `PortfolioBacktest.from_config(...).run` (1.16) — via `ResearchRunner` seam |
| Portfolio metrics | `compute_metrics` (1.6 / 2.2) — no new math |
| Benchmark relative metrics | `BenchmarkEngine.compare` (2.3) |
| Persistence | `ExperimentRegistry` helpers `record_metrics`/`record_equity`/`mark_done` + `create` (2.1/2.4) |
| Window container | `ExperimentResult` dataclass (2.0 frozen) — keyed by window |
| CLI | `research_app` Typer subapp + `_resolve_cli_experiment_config` (2.1) |

No new metric math; no ORM/model change; `metrics.py`/`benchmark.py` untouched.

## 9. Tests (`tests/test_research.py`)

Reuse `FakeDataManager` / `FakePortfolioFn` from 2.4. Add:

- `test_wf_split_basic`: `train=3,test=1,step=1` over a 2015–2024 range → expected fold count +
  each `test_start == train_end` + last `test_end <= end`.
- `test_wf_split_too_short`: range shorter than `train+test` ⇒ empty list.
- `test_wf_run_is_oos_tagged`: full `WalkForwardRunner.run` with fakes → ORM re-readable:
  `is_*` rows have `is_oos=False`, `oos_*` rows `is_oos=True`; `is_agg`/`oos_agg` present;
  `ExperimentRun.status == "done"`.
- `test_wf_aggregate_values`: synthetic folds with known per-fold returns → `is_agg`/`oos_agg`
  equal the hand-computed means (skip `None`).
- `test_wf_no_lookahead`: `FakeDataManager` returns bars beyond the OOS test end → persisted
  `oos_*` benchmark metrics match the in-window-only reference (no leakage).
- `test_wf_empty_range_raises`: `DataError` when `split()` yields no folds.
- `test_cli_research_run_walk_forward`: `--walk-forward 3,1,1` builds a config whose
  `walk_forward` is set and dispatches to `WalkForwardRunner` (dry-run asserts config only).

Acceptance (per plan §5): split correctness; an OOS-metric test proves the test window sees no
train data; determinism; at least one no-look-ahead invariant test; four gates green.

## 10. Frozen decisions (D1–D9)

| # | Decision | Recommended default |
|---|---|---|
| D1 | Splitter class name | **`WalkForwardSplitter`** (replaces the stub). |
| D2 | Runner class name | **`WalkForwardRunner`** (new; dispatches to `ResearchRunner._execute_window`). |
| D3 | Fold container | `dataclass WalkForwardFold(index, train_start, train_end, test_start, test_end)`, all `str` ISO dates. |
| D4 | Single-window reuse | Extract `ResearchRunner._execute_window(config, session, *, window, run_id, is_oos)`; public `run()` keeps full-range behaviour unchanged. |
| D5 | No-look-ahead | `test_start == train_end`; each fold runs on a `config.model_copy` bounded to its slice; `_execute_window` keeps the 2.4 `as_of` ceiling. Invariant test required. |
| D6 | Window tags | `is_{i}` / `oos_{i}` per fold; `is_agg` / `oos_agg` for the summary means. |
| D7 | Aggregation | Simple per-metric mean over folds, skipping `None`/non-finite; summary windows persist with the matching `is_oos` flag. No aggregated equity curve. |
| D8 | No `walk_forward` ⇒ delegate | `config.walk_forward is None` ⇒ `WalkForwardRunner.run` calls `ResearchRunner.run` (same single `full` result as 2.4). |
| D9 | CLI dispatch | `research run` transparently routes to `WalkForwardRunner` when `config.walk_forward` is set; no new flags; `--dry-run` unchanged. |

## 11. Risks / notes

- Year arithmetic via `pd.DateOffset(years=N)` (leap-day safe), not `date.replace`.
- The **real** path (CLI against live data) needs network + a populated universe; it is exercised
  only in the user's environment, never in the four gates (fakes only).
- Fully additive at the ORM/config level — `ExperimentResult`, `ExperimentConfig.walk_forward`, and
  the `window`/`is_oos` columns already exist; 2.5 only fills `walk_forward.py` and adds an internal
  seam to `ResearchRunner`.
- 2.6 will consume the `is_agg`/`oos_agg` + per-fold windows to render the IS-vs-OOS report.
