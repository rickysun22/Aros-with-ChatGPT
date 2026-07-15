# Sprint 1.7 — Ranking Engine (Design)

> Status: design locked, implementation pending. NOT pushed to GitHub until the
> whole sprint is complete (per instruction: no upload before 1.7 is done).
> Sorting semantics confirmed with user: **cross-sectional score ranking**.

## 1. Goal

Turn the per-stock strategy scores produced by Sprint 1.5 into a ranked,
tradeable watch-list. Given a universe of candidate stocks, compute each one's
composite research score at a chosen cross-section date, sort descending, and
emit the **Top N** (default 20) candidates with their score breakdown.

This is the first time AROS operates **across instruments** — Sprint 1.6 was
strictly single-instrument backtest, and its CHANGELOG explicitly deferred
cross-instrument handling to 1.7.

## 2. Sorting semantics (confirmed)

**Cross-sectional composite-score ranking.**

- Each configured strategy already emits a continuous `score_<name>` column
  (`WeightedStrategy` → normalised weighted sum ∈ [-1, 1];
  `RuleStrategy` → boolean 0/1). These are the ranking dimensions.
- For every candidate stock we take its `score_<name>` at a chosen
  cross-section (default: each stock's latest available bar; or an explicit
  `--as-of` date).
- The per-stock composite score is the weighted sum of its dimension scores,
  weights normalised to sum to 1 (so the composite stays in the same scale as
  the inputs, roughly [-1, 1]).
- Sort all candidates by composite score descending; keep the top `top_n`.

Why this semantics: it is lightweight (no full backtest per stock), the score
columns already exist and are dimensionally consistent, and the
no-look-ahead guarantee is inherited directly from `StrategyEngine`.

## 3. Module layout

```
src/ranking/
  __init__.py      # exports: RankingEngine, ScoreModel
  engine.py        # RankingEngine: cross-sectional scoring + Top-N selection
```

Kept deliberately small — ranking is a thin composition layer over
`StrategyEngine`. No new metric math; it reuses `score_<name>` already computed.

## 4. Input / output contract

### Input
- `df`: a multi-stock daily frame with a `code` column (one or more codes).
  Rows need at least `date`, `close`, the factor columns the strategies read,
  and `code`.
- `as_of: date | None` — cross-section date; `None` ⇒ each code's latest bar.
- `top_n: int` — how many to keep (default 20).
- `dimensions: list[DimensionSpec] | None` — which `score_<name>` columns and
  their weights. `None` ⇒ every enabled strategy's `score_<name>`, equal weight.

### Output
`RankingEngine.rank(df) -> tuple[pd.DataFrame, pd.DataFrame]`
- `ranking`: one row per candidate code, columns
  `code, composite_score, rank, score_<name1>, score_<name2>, ...`
  sorted by `composite_score` descending, sliced to `top_n`.
- `scored`: the full scored cross-section (every candidate, every dimension)
  before the Top-N slice — useful for analysis / debugging.

`RankingEngine.rank_universe(codes, data_manager, ...) -> same tuple`
fetches each code's bars via `DataManager.get_daily`, concatenates with a
`code` column, then calls `rank`.

## 5. Scoring algorithm

```
For each code group in df:
    take the as_of (or latest) row
    read score_<name> for each dimension
composite = Σ (w_i / Σ|w|) * score_i        # weights normalised
ranking  = sort codes by composite desc, assign rank 1..N, keep top_n
```

- Weights may be any float; negative weights are allowed (a dimension that
  should *penalise* the score). Normalisation uses `Σ|w|` so sign is preserved.
- If a `score_<name>` column is missing after `StrategyEngine.compute`, raise
  `DataError` (misconfigured ranking dimension vs strategy).

## 6. No-look-ahead convention

`StrategyEngine.compute` already guarantees every column it emits uses only
data known as of each bar (Sprints 1.3–1.5). Ranking reads each stock's
`score_<name>` at the cross-section date and never looks forward. A **truncation
test** in `tests/test_ranking.py` asserts that dropping the last bar of every
stock shifts each surviving stock's score by at most float epsilon and does not
reorder the surviving set — guarding the invariant.

Ranking produces a **research watch-list**, not a trade. It therefore has no
position/equity of its own; cost-aware position sizing remains the job of the
backtest engine (1.6) and the future portfolio allocator.

## 7. Config integration

`src/core/config.py` — add:

```python
class DimensionSpec(BaseModel):
    """One ranking dimension: a strategy's score_<name> column + its weight."""
    strategy: str                       # matches StrategySpec.name
    weight: float = 1.0

class RankingConfig(BaseModel):
    top_n: int = 20
    as_of: str | None = None            # "YYYY-MM-DD"; None => latest per code
    dimensions: list[DimensionSpec] | None = None  # None => all enabled, equal weight
```

Wire into `AppConfig.ranking: RankingConfig = Field(default_factory=RankingConfig)`.

## 8. settings.yaml

Append a `ranking:` section:

```yaml
ranking:
  top_n: 20
  as_of: null                 # null => latest bar per stock
  dimensions: null            # null => all enabled strategies, equal weight
  # example explicit form:
  # dimensions:
  #   - strategy: weighted_momentum
  #     weight: 1.0
  #   - strategy: golden_cross_rule
  #     weight: 0.5
```

## 9. CLI

Add a `ranking` command to `main.py`:

```
aros ranking --universe            # rank all synced stocks
aros ranking 600000,600519,000001  # rank an explicit code list
aros ranking --universe --top-n 10 --as-of 2026-06-30
aros ranking --list                # list enabled strategy names (score sources)
```

Prints the Top-N table (code, composite_score, rank, each score_<name>) and the
count. Reads `DataManager` for bars, `get_config()` for strategy + ranking config.

## 10. Tests (`tests/test_ranking.py`)

- `test_composite_weights`: known scores + weights ⇒ expected composite (hand-computed).
- `test_weight_normalisation`: negative & unequal weights normalise correctly.
- `test_sort_descending`: output ordered by composite descending.
- `test_top_n_truncation`: only `top_n` rows returned; remainder excluded.
- `test_all_enabled_equal_weight`: `dimensions=None` uses every strategy score, equal weight.
- `test_missing_dimension_raises`: ranking dimension names a non-existent strategy ⇒ `DataError`.
- `test_multicode_grouping`: 3+ codes, each with distinct scores, ranked independently.
- `test_as_of_selects_bar`: `--as_of` picks the right historical cross-section.
- `test_no_lookahead_truncation`: dropping the last bar does not reorder survivors.
- `test_cli_ranking_list`: `ranking --list` prints strategy names.

## 11. Relationship to 1.5 / 1.6 and boundaries

- **1.5 Strategy Engine**: produces `score_<name>` / `signal_<name>` — the raw
  material for ranking. Reused, not modified.
- **1.6 Backtest Engine**: single-instrument cost-aware simulation. Orthogonal;
  ranking does **not** call the backtester (kept lightweight per the confirmed
  semantics). Optional backtest-metric dimensions are explicitly out of scope
  for 1.7 (deferred — could be a 1.7.x extension or 1.8 input).
- **1.8 Daily Report**: will consume the ranking output as its headline list.

## 12. Acceptance (four gates + CI)

- `ruff check .` clean
- `black --check .` clean
- `mypy src tests main.py` clean
- `pytest -q` all green (existing 107 + new ranking tests)
- No `git push` until the sprint is fully complete; local commit allowed.

## 13. Open points (resolved by this design)

- Cross-instrument handling lands here (first multi-stock sprint). ✔
- Sorting basis = strategy `score_<name>` (not backtest metrics). ✔ (user-confirmed)
- Top N default = 20. ✔ (Roadmap)
