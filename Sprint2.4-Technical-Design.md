# Sprint 2.4 — Research Runner (Technical Design)

> Status: **Technical design** for ChatGPT review + freeze before code lands.
> Parent contract: `Phase2-Implementation-Plan.md` §4 "Sprint 2.4 — Research Runner (orchestration)".
> Foundation already on `main`: Sprints 2.0 (persistence ORM + index data + `BenchmarkConfig`),
> 2.1 (`research` CLI + `ExperimentConfig` + `ExperimentRegistry`), 2.2 (metric maths in
> `src/backtest/metrics.py`), 2.3 (`BenchmarkEngine.compare`). 2.4 wires them into one
> runnable, persistable experiment.
> Coding rule carried from Phase 1 / 2.0: **no new metric math outside `src/backtest/metrics.py`**.

## 1. Context

Phase 2 turns the Phase-1 *lab* into a *research engine*: define → run → compare → validate
strategies as reproducible experiments. The rails are in place, but nothing yet **runs** an
experiment end-to-end:

- `PortfolioBacktest` (1.16) can produce a `(equity, trades)` curve from a candidate set.
- `compute_metrics` (1.6 / 2.2) turns that into portfolio metrics.
- `BenchmarkEngine.compare` (2.3) compares it to an index benchmark.
- `ExperimentRegistry` + `ExperimentRun`/`ExperimentMetric`/`ExperimentEquity` (2.1) persist results.

What is **missing** is the orchestration that chains these and writes the result. `src/research/runner.py`
is still a `NotImplementedError` stub. Sprint 2.4 fills exactly that gap — it is a *thin
orchestration + persistence* layer (per plan §2 "Reuse, don't rebuild"), not a new engine.

## 2. Scope (strictly 2.4)

In scope:
- Replace the `ResearchRunner` stub in `src/research/runner.py` with a real `run(config)`.
- Full pipeline: resolve candidates → run portfolio → compute metrics → benchmark compare →
  persist → return `ExperimentResult`.
- Persist **portfolio metrics** + **benchmark metrics** into `ExperimentMetric`, and the equity
  curve into `ExperimentEquity`, via new `ExperimentRegistry` helpers.
- Add a `research run` CLI command (reusing the existing `research init` flag/helper surface).
- Unit tests with fakes + the mandatory no-look-ahead invariant (`tests/test_research.py`).

Out of scope (later sprints): walk-forward / OOS (2.5) — this sprint does a **single full-range**
run with `window="full"` only; the research report (2.6) — no rendering; a real risk-free series
(open Q #3 — keep the configurable constant); any new metric math.

## 3. Interface

```python
# src/research/runner.py
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable


PortfolioFn = Callable[[list[str], Any, date, date], "PortfolioResult"]


class ResearchRunner:
    def __init__(
        self,
        data_manager: Any | None = None,          # None => DataManager() from get_config()
        portfolio_fn: PortfolioFn | None = None,   # None => default PortfolioBacktest path
        benchmark_engine: BenchmarkEngine | None = None,  # None => BenchmarkEngine(dm)
        config: AppConfig | None = None,           # None => get_config()
    ) -> None: ...

    def run(self, config: ExperimentConfig, session: Any = None) -> ExperimentResult: ...
```

Notes:
- `portfolio_fn(codes, data_manager, start, end) -> PortfolioResult` is the single injected seam
  for the heavy backtest step, mirroring `PortfolioBacktest`'s own `rank_fn`/`equity_fn` seam.
  Tests inject a `FakePortfolioFn`; the real path builds `PortfolioBacktest.from_config(...)`.
- `data_manager` flows to **both** the portfolio step and `BenchmarkEngine` (single data entry).
- `session` is threaded to `ExperimentRegistry` so tests run against an in-memory sqlite session;
  when `None`, the registry opens its own default session.
- The return type is the existing `ExperimentResult` dataclass (frozen in 2.0), keyed by window
  `"full"` so 2.5 walk-forward results slot in without a schema change.

## 4. Pipeline (`run`)

1. **Resolve candidates.** If `config.universe` is set, `codes = UniverseEngine(session).get_codes(universe)`;
   else `codes = config.codes`. If the result is empty → `DataError` (never run on nothing).
2. **Portfolio.** `result = portfolio_fn(codes, self._dm, start, end)` → `PortfolioResult(equity, trades, ...)`.
   If `len(equity) < 2` → `DataError`.
3. **Benchmark close (for `benchmark_return`).** If `config.benchmark` is a known key in
   `BenchmarkConfig.indices`, fetch `bench_df = dm.get_index_daily(raw_code, start, end, as_of=end)`
   and build `bench_close = pd.Series(bench_df["close"], index=pd.to_datetime(bench_df["date"]))`.
   Else `bench_close = pd.Series(dtype=float)` (and benchmark comparison is skipped).
4. **Portfolio metrics.** Build a `BacktestConfig` copy with `metrics = config.metrics or cfg.backtest.metrics`
   and `benchmark = True`; then `metrics = compute_metrics(equity, trades, bench_close, bt_config)`.
5. **Benchmark compare.** If the benchmark key is valid:
   `bench = BenchmarkEngine(self._dm).compare(equity, config.benchmark, (start, end), risk_free=cfg.backtest.risk_free, as_of=end)`.
   Else `bench = None`.
6. **Persist** (see §5).
7. **Return** `ExperimentResult(run_id, metrics={"full": {**metrics, **bench_prefixed}}, equity={"full": equity_dict}, windows=["full"])`.

## 5. Persistence schema & naming

Three new `ExperimentRegistry` helpers keep all ORM writes inside the registry (2.1 owns the schema):

```python
def record_metrics(self, run_id, metrics: dict[str, float | None], window="full", is_oos=False) -> None
def record_equity(self, run_id, equity: dict[str, float], window="full", is_oos=False) -> None
def mark_done(self, run_id, status="done") -> None
```

- `run()` calls `registry.create(name, config_json, notes)` → `run_id` (status `"created"`), then
  `record_metrics(run_id, metrics, "full", False)`, `record_metrics(run_id, bench.to_dict() prefixed, "full", False)`,
  `record_equity(run_id, equity_dict, "full", False)`, and finally `mark_done(run_id)`.
- **Benchmark metrics are stored with the prefix `"bench_"`** (`bench_excess_return`, `bench_alpha`,
  `bench_beta`, `bench_tracking_error`, `bench_information_ratio`) so they are distinguishable from
  portfolio metrics in the long-form table and queryable by prefix in 2.6. (No name collision occurs
  today — portfolio `compute_metrics` names and benchmark names are disjoint — but the prefix makes
  the semantics explicit and future-proofs against 2.2-style metric additions.)
- **Non-finite values → `None`.** `profit_factor` can be `inf` when there are no losing days; a value
  of `inf`/`nan` is coerced to `None` on persist (matches the `ExperimentMetric.value` "nullable for
  uncomputable" contract). `BenchmarkComparison.to_dict()` is already all-finite, so only portfolio
  metrics are affected.
- Equity is serialized as `{iso_date_str: float}` into `ExperimentEquity.equity_json`.

## 6. No-look-ahead invariant (mandatory per plan §5)

The benchmark must never see data past the experiment window. The runner enforces this twice:

- The benchmark-close fetch in step 3 uses `as_of=end` (the experiment's last date).
- `BenchmarkEngine.compare` is called with `as_of=end`, and (per its own frozen D7) caps its own
  internal `get_index_daily` at that ceiling — so even if the data source holds later bars, they are
  never read.

A 2.4 unit test feeds a `FakeDataManager` whose `get_index_daily` returns bars **beyond** `end` and
asserts the persisted benchmark metrics equal a reference computed only on the in-window slice
(proving no leakage), exactly as the 2.3 invariant does at the engine level.

## 7. CLI (`research run`)

Reuses the `research init` flag set + `_build_experiment_config` / `_load_config_file` helpers so the
CLI surface stays consistent:

```
research run --name X --universe POOL [--codes C1,C2] --strategy S --start D --end D
             [--benchmark KEY] [--metrics m1,m2] [--config FILE] [--seed N] [--dry-run]
```

- `--name` is required; `--universe`/`--codes` are XOR (validated by `ExperimentConfig`).
- The plan's `--backtest` flag is **subsumed**: the runner always runs the backtest+metrics step, so
  no separate flag is needed (documented, not a silent no-op).
- Builds an `ExperimentConfig`, then `ResearchRunner().run(config)`. With real data this hits the
  network (the user's environment); tests use injected fakes and never touch the network.
- On success, echoes `run_id` + a short metric summary (total_return, sharpe, bench_excess_return, bench_beta).
- `--dry-run` builds and prints the config without executing (parity with `research init --dry-run`).

## 8. Reuse map

| Need | Reuse |
|---|---|
| Candidate resolution | `UniverseEngine.get_codes` (1.13) |
| Portfolio equity/trades | `PortfolioBacktest.from_config(...).run` (1.16) — `rank_fn`/`equity_fn` injectable |
| Portfolio metrics | `compute_metrics` (1.6 / 2.2) — no new math |
| Benchmark relative metrics | `BenchmarkEngine.compare` (2.3) |
| Persistence | `ExperimentRegistry` + `ExperimentRun`/`Metric`/`Equity` ORM (2.1) |
| Config | `get_config()` (`AppConfig.backtest/ranking/benchmark/research`) |
| CLI | `research_app` Typer subapp + `_build_experiment_config` (2.1) |

No new module beyond `runner.py`; no edits to `metrics.py`, `benchmark.py`, or the ORM models.

## 9. Tests (`tests/test_research.py`)

Add `FakeDataManager` (exposes `get_daily` + `get_index_daily` returning synthetic frames) and
`FakePortfolioFn` (returns a synthetic `PortfolioResult`), plus:

- `test_runner_full_run_persists`: full `run()` with fakes → registry re-readable: metrics rows
  present (portfolio + `bench_*`), equity JSON round-trips, `ExperimentRun.status == "done"`.
- `test_runner_metrics_values`: synthetic equity with a known return → `total_return` and
  `bench_excess_return`/`bench_beta` match hand-computed values within `1e-9`.
- `test_runner_no_lookahead`: `FakeDataManager.get_index_daily` returns bars beyond `end` →
  persisted `bench_*` equal the reference computed on the in-window slice only.
- `test_runner_missing_benchmark`: unknown `config.benchmark` key → `ConfigError` surfaces (no silent skip).
- `test_runner_empty_codes`: neither `universe` nor `codes` resolves to anything → `DataError`.
- `test_runner_equity_roundtrip`: `ExperimentEquity.equity_json` decodes back to the original series
  (dates + values within `1e-9`).

Acceptance (per plan §5): full run on fakes; result persisted and re-readable; at least one
no-look-ahead invariant test; four gates green.

## 10. Frozen decisions (D1–D9)

| # | Decision | Recommended default |
|---|---|---|
| D1 | Runner class name | **`ResearchRunner`** (replaces the stub; nothing imports the old body). |
| D2 | Heavy backtest seam | Injectable `portfolio_fn(codes, dm, start, end) -> PortfolioResult`; `None` ⇒ default `PortfolioBacktest.from_config`. Tests inject a fake. |
| D3 | `data_manager` dependency | Injectable (single data entry); `None` ⇒ `DataManager()`. Flows to both portfolio + benchmark. |
| D4 | Return type | Existing `ExperimentResult` dataclass, window key `"full"` (2.5 slots OOS windows in). |
| D5 | Benchmark metric naming | Stored with prefix **`bench_`** (explicit, future-proof). Portfolio metrics keep their own names. |
| D6 | Non-finite metric values | Coerced to `None` on persist (avoids sqlite `inf` issues; matches `value` nullable contract). |
| D7 | No-look-ahead | Benchmark fetch + `BenchmarkEngine.compare` both capped at `as_of=end`; invariant test required. |
| D8 | Metrics list source | `config.metrics or cfg.backtest.metrics` (no parallel list — frozen in `ResearchConfig`). |
| D9 | `research run --backtest` | Subsumed (runner always backtests); no redundant flag. `--dry-run` supported for parity. |

## 11. Risks / notes

- The **real** path (CLI against live data) needs network + a populated universe pool; it is exercised
  only in the user's environment, never in the four gates. The four gates use fakes.
- No ORM / model change — only three additive `ExperimentRegistry` helpers and the runner body.
- `BenchmarkEngine.compare` is consumed as-is (2.3 frozen interface untouched); the runner reuses it.
- Fully additive: nothing currently calls the `ResearchRunner` stub, so filling it is risk-free.
