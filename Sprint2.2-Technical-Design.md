# Sprint 2.2 — Metrics Extension (Technical Design)

> Status: **Technical design** for ChatGPT review + freeze before code lands.
> Parent contract: `Phase2-Implementation-Plan.md` §4 "Sprint 2.2 — Metrics Extension".
> Foundation already on `main`: Sprints 2.0 (persistence + index data) and 2.1 (`research` CLI).
> Coding rule carried from Phase 1 / 2.0: **no new metric math outside `src/backtest/metrics.py`**.

## 1. Context

GPT's original Phase 2 plan wanted metrics such as `profit_factor`, `calmar`,
`avg_holding_days`, `max_consecutive_losses`, `exposure`. Per the reuse map
(`Phase2-Implementation-Plan.md` §2) these must be **added into the existing
`src/backtest/metrics.py` dispatcher**, NOT a new `research/metrics.py` module
(that file is explicitly forbidden by the 2.0 frozen decision).

Sprint 2.2 is therefore a **metrics-only** sprint: extend `compute_metrics`
with five well-defined scalar functions, each with a hand-checked unit test.
No ORM change, no new CLI surface, no network, no runner logic. It is the
smallest, lowest-risk sprint in Phase 2 and unblocks the richer reporting in
2.3–2.6 (those sprints will simply request these metric names).

## 2. Scope (strictly 2.2)

In scope:
- Five new metric functions in `src/backtest/metrics.py`.
- Register them in the `compute_metrics` `available` dict (making them
  selectable via `BacktestConfig.metrics`).
- One hand-checked unit test per metric in `tests/test_backtest.py`.

Out of scope (later sprints): benchmark comparison (2.3), runner (2.4),
walk-forward (2.5), report (2.6), any new ORM column, any CLI change.

## 3. Metric definitions

All five take only the inputs `compute_metrics` already receives
(`equity: pd.Series`, `trades: pd.DataFrame`); no signature change.

### 3.1 `profit_factor`
- **Source**: daily equity returns `r = equity.pct_change().fillna(0.0)`.
- **Formula**: `gross_profit = r[r > 0].sum()`, `gross_loss = -r[r < 0].sum()`;
  `profit_factor = gross_profit / gross_loss`.
- **Edge cases**: `gross_loss == 0` → return `float("inf")` (pure winner);
  `len(r) == 0` or all returns zero → `0.0`.
- **Rationale**: the trade blotter carries `weight_change`/`notional`/`cost` but
  no per-trade realised PnL, so a per-trade profit factor is not reconstructable
  without re-simulating. The daily-return profit factor is the standard,
  well-defined alternative and needs no new data.

### 3.2 `calmar`
- **Source**: `cagr(equity)` (existing) and `max_drawdown(equity)` (existing).
- **Formula**: `calmar = cagr / abs(max_drawdown)`.
- **Edge cases**: `max_drawdown == 0` → `0.0` (avoid div-by-zero).

### 3.3 `avg_holding_days`
- **Source**: `trades["date"]` (datetime, one row per rebalance event).
- **Formula**: sort trades by date; `gaps = diff(trades["date"]).days`;
  `avg_holding_days = gaps.mean()`.
- **Edge cases**: `< 2` trades → `0.0` (no interval to measure).
- **Interpretation**: mean calendar-day duration a position is held between
  consecutive rebalances. Cheap, needs no position state.

### 3.4 `max_consecutive_losses`
- **Source**: daily equity returns `r`.
- **Formula**: longest run of consecutive `r < 0` days; count of that run.
- **Edge cases**: no losing day → `0`.

### 3.5 `exposure`
- **Source**: reconstruct position series from `trades` over `equity.index`.
- **Method**:
  ```python
  pos = pd.Series(0.0, index=equity.index)
  for _, t in trades.iterrows():
      i = equity.index.get_loc(t["date"])
      pos.iloc[i:] = pos.iloc[i:] + t["weight_change"]
  exposure = float((pos != 0).mean())
  ```
- **Edge cases**: empty `trades` → `0.0`.
- **Rationale**: `compute_metrics` does not receive a position series, only the
  trade events. Cumulative `weight_change` over the equity date index is the
  faithful reconstruction of held weight, and the fraction of bars with
  non-zero weight is the time-in-market exposure.

## 4. Dispatcher registration

In `compute_metrics`, extend the `available` dict with the five new keys:

```python
"profit_factor": profit_factor(equity),
"calmar": calmar(equity),
"avg_holding_days": avg_holding_days(trades),
"max_consecutive_losses": max_consecutive_losses(equity),
"exposure": exposure(equity, trades),
```

`compute_metrics` already raises `ConfigError` on unknown names, so these
become selectable the moment they are in `available`. No other code path
changes.

## 5. Tests (hand-checked)

Add to `tests/test_backtest.py`, mirroring `test_metrics_hand_computed` style
(`BacktestConfig(metrics=["profit_factor", ...])`):

- `test_metric_profit_factor`: equity `[100,110,99,120]` → hand-compute
  gross profit / gross loss; assert within `1e-9`.
- `test_metric_calmar`: known equity → assert `cagr/abs(mdd)` within `1e-9`.
- `test_metric_avg_holding_days`: two trades 5 calendar days apart → `== 5.0`.
- `test_metric_max_consecutive_losses`: returns with a run of 3 down days → `== 3`.
- `test_metric_exposure`: one buy then sell over N bars → exposure =
  held-bars / total-bars within `1e-9`.
- Plus edge guards: empty/flat equity returns `0.0` for profit_factor;
  `max_drawdown == 0` → calmar `0.0`; `<2` trades → avg_holding_days `0.0`.

Acceptance (per plan §5): each metric has a unit test with a hand-checked
value; all pre-existing `test_backtest.py` stays green; four gates green.

## 6. Frozen decisions (D1–D4)

| # | Decision | Recommended default |
|---|---|---|
| D1 | Add the 5 metrics to the *default* `BacktestConfig.metrics` list? | **No** — register only in the `available` dispatcher so they are selectable without changing existing backtest outputs / snapshots. Lowest risk. |
| D2 | `profit_factor` basis | Daily equity returns (gross profit / gross loss), not per-trade PnL (blotter lacks realised PnL). |
| D3 | `exposure` basis | Reconstruct position from cumulative `weight_change` over `equity.index`; fraction of non-zero-weight bars. |
| D4 | Edge handling | `profit_factor` inf when no loss / `0.0` when flat; `calmar` `0.0` when mdd==0; `avg_holding_days` `0.0` when `<2` trades; `max_consecutive_losses` `0` when none. |

## 7. Risks / notes

- No signature change to `compute_metrics` — fully backward compatible; the
  2.1 `research` CLI and all existing callers are unaffected.
- `exposure`'s position reconstruction assumes `trades["date"]` values are
  present in `equity.index` (true for `BacktestEngine._simulate`, which stamps
  `df.index`). If a future caller passes unaligned trades, `get_loc` would
  raise — acceptable, because the only caller today is `BacktestEngine`.
- These metrics are pure functions; the walk-forward (2.5) and report (2.6)
  sprints will simply name them in `ExperimentConfig.metrics` / config.
