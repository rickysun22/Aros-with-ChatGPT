# Sprint 2.3 — Benchmark Comparison (Technical Design)

> Status: **Technical design** for ChatGPT review + freeze before code lands.
> Parent contract: `Phase2-Implementation-Plan.md` §4 "Sprint 2.3 — Benchmark Comparison".
> Foundation already on `main`: Sprints 2.0 (persistence + index data + `BenchmarkConfig`),
> 2.1 (`research` CLI incl. `--benchmark`), 2.2 (metric maths in `src/backtest/metrics.py`).
> Coding rule carried from Phase 1 / 2.0: **no new metric math outside `src/backtest/metrics.py`**.

## 1. Context

Phase 2 needs to compare a strategy's equity curve against a benchmark index so
every experiment can report *relative* performance (did the strategy beat the
index, and by how much, after risk?). The rails are already in place:

- `DataManager.get_index_daily(code, start, end, as_of)` (2.0) fetches benchmark
  bars through the single data entry point and raises `DataError` when no data
  exists — so a missing benchmark can never be silently ignored.
- `BenchmarkConfig` (2.0) maps human keys (`csi300`, `csi500`, `csi1000`,
  `sh_composite`) to raw index codes.
- `ExperimentConfig.benchmark: str = "csi300"` (2.0) and the `research init
  --benchmark` CLI flag (2.1) already capture the *choice* of benchmark.
- `src/backtest/metrics.py` (2.2) holds all generic return/math helpers.

What is **missing** is the comparison engine itself: `src/research/benchmark.py`
is still a `NotImplementedError` stub. Sprint 2.3 fills exactly that gap.

## 2. Scope (strictly 2.3)

In scope:
- Replace the `BenchmarkComparator` stub in `src/research/benchmark.py` with a
  real `BenchmarkEngine` that implements `compare(...)`.
- Compute five benchmark-relative metrics: `excess_return`, `alpha`, `beta`,
  `tracking_error`, `information_ratio`.
- Export `BenchmarkEngine` (and the result type) from `research/__init__.py`.
- Unit tests with hand-checked values + the no-look-ahead invariant
  (`tests/test_research.py`).

Out of scope (later sprints): persisting the comparison into the ORM
(`ExperimentMetric`) — that is the 2.4 runner's job; any new CLI command — the
`--benchmark` plumbing already exists and is consumed by the 2.4 runner; real
risk-free series (open question #3 — keep the configurable constant for now).

## 3. Interface

```python
# src/research/benchmark.py
from dataclasses import dataclass


@dataclass
class BenchmarkComparison:
    benchmark_code: str          # resolved key actually used, e.g. "csi300"
    excess_return: float
    alpha: float                 # annualised CAPM alpha
    beta: float
    tracking_error: float        # annualised
    information_ratio: float     # annualised
    n_points: int                # aligned overlapping bars used

    def to_dict(self) -> dict[str, float]: ...


class BenchmarkEngine:
    def __init__(self, data_manager: DataManager | None = None) -> None:
        # None => DataManager() built from get_config(); injectable for tests.

    def compare(
        self,
        portfolio_equity: pd.Series,         # indexed by date, any positive scale
        benchmark_code: str,                 # key into BenchmarkConfig.indices
        range: tuple[str, str],              # (start "YYYY-MM-DD", end "YYYY-MM-DD")
        risk_free: float | None = None,      # None => cfg.backtest.risk_free (0.0)
        as_of: str | None = None,            # no-look-ahead ceiling; see §5
    ) -> BenchmarkComparison: ...
```

Notes:
- `benchmark_code` is the **key** (e.g. `"csi300"`), resolved through
  `BenchmarkConfig.indices`. A raw 6-digit code not present in the map raises
  `ConfigError` (consistent with how `ExperimentConfig.benchmark` is documented).
- `range` mirrors the `(start, end)` style already used by `DataManager`; the
  plan's signature `compare(portfolio_equity, benchmark_code, range)` is honoured.
- The return type is a typed `BenchmarkComparison` dataclass (easy to persist in
  2.4 and to render in 2.6), with a `to_dict()` for callers that want a plain dict.

## 4. Metric definitions

All five metrics are computed on the **inner-joined** date range of the portfolio
equity and the benchmark equity (only dates present in *both* series). Daily
returns use `daily_returns()` — a public helper promoted from the existing private
`_daily_returns` in `src/backtest/metrics.py` (see D4), so the return math lives in
exactly one place.

Let `r_p` = portfolio daily returns, `r_b` = benchmark daily returns,
`rf_d = (1 + risk_free) ** (1/252) - 1` (daily risk-free), and
`excess_p = r_p - rf_d`, `excess_b = r_b - rf_d`.

### 4.1 `excess_return`
- Portfolio period return minus benchmark period return:
  `excess_return = (pe[-1]/pe[0] - 1) - (be[-1]/be[0] - 1)` where `pe`/`be` are the
  two equity curves over the aligned window. Scale-invariant (ratio of endpoints).

### 4.2 `beta`
- `beta = Cov(r_p, r_b) / Var(r_b)` (sample covariance / variance, `ddof=1`).
- Edge: `Var(r_b) == 0` (flat benchmark) → `beta = 0.0` (no benchmark variance to
  explain). This is the "β=0" acceptance case.

### 4.3 `alpha` (annualised CAPM alpha)
- `alpha = (mean(excess_p) - beta * mean(excess_b)) * 252`.
- When `beta` was forced to `0.0` (flat benchmark), this reduces to
  `mean(excess_p) * 252` (annualised portfolio excess return over cash).

### 4.4 `tracking_error` (annualised)
- Standard deviation of **active** returns: `te = std(r_p - r_b, ddof=1) * sqrt(252)`.
- Edge: `te == 0` (portfolio tracks benchmark exactly) → `0.0`.

### 4.5 `information_ratio` (annualised)
- `ir = mean(r_p - r_b) * 252 / tracking_error`.
- Edge: `tracking_error == 0` → `0.0` (no active risk to reward).

Acceptance sanity cases (also encoded as tests):
- **Portfolio == benchmark** (identical return series) → `beta ≈ 1.0`,
  `excess_return ≈ 0.0`, `alpha ≈ 0.0`, `tracking_error ≈ 0.0`, `information_ratio ≈ 0.0`.
- **Flat portfolio / moving benchmark** (or uncorrelated) → `beta ≈ 0.0`.

## 5. No-look-ahead invariant (mandatory per plan §5)

The benchmark must never include data the portfolio could not have seen. The
engine enforces this:

- If `as_of` is `None`, it is derived as `max(portfolio_equity.index)` — the last
  date of the portfolio curve — so the benchmark fetch is capped at the portfolio's
  own end date.
- `get_index_daily` is then called with `as_of` (plus the `[start, end]` window),
  giving the same ceiling the portfolio itself obeys.
- A unit test asserts that passing an `as_of` strictly before the portfolio end
  yields a comparison computed only over the shorter, non-leaking window.

This keeps 2.3 inside the project's no-future-function rule; the 2.4 runner will
reuse the same `as_of` plumbing.

## 6. Reuse map

- `DataManager.get_index_daily` — single source of benchmark bars (2.0). No direct
  provider/DB access from `benchmark.py`.
- `BenchmarkConfig.indices` / `BacktestConfig.risk_free` via `get_config()` — no
  new config keys (the plan's "`BenchmarkConfig`" already exists from 2.0).
- `daily_returns()` (promoted from `backtest/metrics.py`) — the only return-math
  helper; benchmark-specific maths (alpha/beta/TE/IR) is *benchmark* maths and
  therefore legitimately lives in `benchmark.py`, not duplicated into `metrics.py`.

## 7. Tests (`tests/test_research.py`)

Add a `FakeDataManager` returning synthetic index frames for known cases, plus:

- `test_benchmark_equal`: synthetic portfolio == synthetic benchmark →
  `beta ≈ 1`, `excess_return ≈ 0`, `alpha ≈ 0`, `tracking_error ≈ 0`, `ir ≈ 0`
  (within `1e-9`).
- `test_benchmark_beta_zero`: flat portfolio vs moving benchmark → `beta ≈ 0`,
  `tracking_error` == portfolio vol (defined), `ir` defined.
- `test_benchmark_hand_values`: a small hand-built `portfolio_equity` +
  `benchmark` close series → assert each of the five metrics matches a
  hand-computed value within `1e-9`.
- `test_benchmark_no_lookahead`: `as_of` before portfolio end → comparison uses
  only the non-leaking window (assert `n_points` and metric values match a direct
  computation on the truncated window).
- `test_benchmark_missing_data`: `FakeDataManager` returns empty → `DataError`
  surfaces (never silently ignored).
- `test_benchmark_unknown_key`: `benchmark_code` not in `BenchmarkConfig.indices`
  → `ConfigError`.

Acceptance (per plan §5): synthetic portfolio vs synthetic index; known beta
cases (β=1, β=0); at least one no-look-ahead invariant test; four gates green.

## 8. Frozen decisions (D1–D8)

| # | Decision | Recommended default |
|---|---|---|
| D1 | Engine class name | **`BenchmarkEngine`** (replaces the `BenchmarkComparator` stub; nothing imports the old name). |
| D2 | `DataManager` dependency | Injectable; `None` ⇒ `DataManager()` from `get_config()`. Tests inject a `FakeDataManager`. |
| D3 | Return type | Typed `BenchmarkComparison` dataclass (+ `to_dict()`); not a bare dict, so 2.4/2.6 can persist/render it. |
| D4 | Daily-return helper | Promote private `_daily_returns` → public `daily_returns` in `src/backtest/metrics.py`; import it in `benchmark.py`. No change to `compute_metrics` signature. |
| D5 | Risk-free source | `BacktestConfig.risk_free` (configurable constant, default `0.0`); `compare` accepts an optional `risk_free` override. No real risk-free series yet (open Q #3). |
| D6 | `benchmark_code` meaning | The **key** into `BenchmarkConfig.indices`; unknown key ⇒ `ConfigError`. |
| D7 | No-look-ahead | `as_of` defaults to `max(portfolio_equity.index)`; passed straight to `get_index_daily`. Invariant test required. |
| D8 | Edge handling | `Var(r_b)==0` ⇒ `beta=0.0`; `tracking_error==0` ⇒ `ir=0.0`; empty/short series ⇒ `DataError`; no date overlap ⇒ `DataError`. |

## 9. Risks / notes

- No ORM / CLI change in 2.3 — the result is computed and returned; the 2.4
  runner will persist it into `ExperimentMetric` and the 2.6 report will render it.
- `--benchmark` already exists end-to-end (2.1 → `ExperimentConfig.benchmark`),
  so no new CLI surface is added in 2.3; the engine is consumed by the runner.
- `daily_returns` promotion is the only edit to `metrics.py`; it is purely a
  visibility change (private → public) and cannot alter existing behaviour.
- Fully backward compatible: nothing currently calls the stub, so renaming it to
  `BenchmarkEngine` is risk-free.
