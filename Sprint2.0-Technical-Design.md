# Sprint 2.0 — Technical Design (Phase 2 Foundation)

> Status: **DRAFT for review** — framework contract to agree on **before** any code lands.
> Primary reference: `Phase2-Research-Engine-Revision.md` (the single source of truth, aligned to 1.1–1.16).
> Roadmap: `Phase2-Implementation-Plan.md` (sprint-by-sprint 2.0–2.6).
> Purpose: freeze the **data + persistence foundation** (schemas, interfaces, module
> boundaries, config, test contracts) so both sides build 2.1–2.6 on identical footing.

## 0. Scope & non-scope

**In scope (2.0 only):**
- 2.0a — index / benchmark market data through `DataManager` (new `IndexBar` ORM + provider path + accessor).
- 2.0b — experiment persistence layer on `core.database` (`ExperimentRun` / `ExperimentMetric` / `ExperimentEquity`).
- The `src/research/` package skeleton (empty-but-typed module stubs + public exports) so 2.1–2.6 只填肉不搭骨架.
- Config surface (`ResearchConfig`, `BenchmarkConfig`) wired into `AppConfig`.
- One real-data end-to-end smoke (fetch one index, persist one dummy experiment) — first time we leave the Fake stubs.

**NOT in 2.0** (deferred to their sprints): metric math (2.2), benchmark comparison logic (2.3), runner orchestration (2.4), walk-forward (2.5), research report rendering (2.6). 2.0 only lays rails.

## 1. Design principles (inherited, non-negotiable)

- **No future functions** — index accessor honours the same `as_of`/`end` ceiling as `get_daily`.
- **Single data entry** — index bars flow through `DataManager`, never a side channel.
- **Reuse, don't rebuild** — ORM follows the exact pattern of `BacktestPoint`/`RankingPoint`; no new DB framework.
- **Best-effort persistence where non-critical** — experiment writes must not silently corrupt; but a failed *cache-like* read degrades (mirrors 1.12).
- **Testable + gated** — every new unit has a test; four gates green; ≥1 no-look-ahead assertion (index accessor).

## 2. Module layout (what 2.0 creates)

```text
src/
  data/
    models.py        # + IndexBar ORM
    provider.py      # + get_index_daily on DataProvider protocol + AkShareProvider
    manager.py       # + DataManager.get_index_daily / sync_index
  research/          # NEW package (skeleton only in 2.0)
    __init__.py      # public exports
    models.py        # ExperimentRun / ExperimentMetric / ExperimentEquity ORM
    experiment.py    # ExperimentConfig (pydantic) + ExperimentResult dataclass  [filled 2.1]
    registry.py      # ExperimentRegistry (create/get/list/delete)              [filled 2.1]
    metrics.py       # DO NOT CREATE — metrics live in src/backtest/metrics.py  (2.2 extends there)
    benchmark.py     # stub only                                                [filled 2.3]
    runner.py        # stub only                                                [filled 2.4]
    walk_forward.py  # stub only                                                [filled 2.5]
    report.py        # stub only                                                [filled 2.6]
  core/
    config.py        # + ResearchConfig + BenchmarkConfig
```

> Note the explicit anti-pattern guard: `research/metrics.py` is intentionally **not** created; all metric math stays in `src/backtest/metrics.py` (§Reuse Map of the revision doc). A one-line comment in `research/__init__.py` records this decision so nobody re-adds it.

## 3. Data foundation (2.0a)

### 3.1 `IndexBar` ORM (`src/data/models.py`)

Separate table from per-stock `DailyBar` (different symbol space, no adjust factor, distinct sync cadence).

| column | type | notes |
|---|---|---|
| `id` | int PK autoincrement | |
| `code` | str, indexed | index symbol, e.g. `000300` |
| `date` | int (YYYYMMDD) | same integer-date convention as `DailyBar` |
| `open/high/low/close` | float | |
| `volume` | float, nullable | index volume may be absent |
| `amount` | float, nullable | 成交额, optional |
| — | | **UniqueConstraint(`code`, `date`)** |

Rationale for a separate table (vs a `kind` flag on `DailyBar`): keeps `DailyBar` queries/indices untouched, avoids polluting the 1.2 stock model, mirrors how 1.9/1.11 added sibling tables rather than columns.

### 3.2 Provider path (`src/data/provider.py`)

- Extend the `DataProvider` protocol with `get_index_daily(code, start, end) -> DataFrame` (same normalized columns as `get_daily`: `date, open, high, low, close, volume[, amount]`).
- `AkShareProvider.get_index_daily`: wrap `ak.stock_zh_index_daily` (or `ak.index_zh_a_hist`) with the existing column-normalization helper. **Decision needed** — which AKShare fn (see §7 Q1).
- `AStockDataProvider` (HTTP fallback): index endpoint is a **later** concern; in 2.0 it raises `NotImplementedError` with a clear message so `data.source=astockdata` fails loudly rather than silently. (Documented, not a bug.)

### 3.3 `DataManager` accessors (`src/data/manager.py`)

```python
def sync_index(self, code: str, start: str | None = None, end: str | None = None) -> int: ...
def get_index_daily(self, code: str, start=None, end=None, as_of=None) -> pd.DataFrame: ...
```

- `get_index_daily` mirrors `get_daily`: integer-indexed frame with a `date` column; `as_of` filters `date <= as_of` (the no-look-ahead ceiling).
- Missing benchmark data → **raise `DataError`** with the index code (revision §4.1: "缺失基准数据应清晰报错"), never return an empty silent frame.

### 3.4 Config (`config/settings.yaml`)

```yaml
benchmark:
  default: csi300
  indices:
    csi300: "000300"
    csi500: "000905"
    csi1000: "000852"
    sh_composite: "000001"
```

Backed by `BenchmarkConfig` (pydantic) in `core/config.py`, wired to `AppConfig.benchmark`.

## 4. Experiment persistence (2.0b)

### 4.1 ORM (`src/research/models.py`, on `core.database.Base`)

**`ExperimentRun`**
| column | type | notes |
|---|---|---|
| `id` | str PK | short uuid (e.g. `exp_a1b2c3`) |
| `name` | str, unique | human label |
| `config_json` | text | full `ExperimentConfig` round-trip |
| `status` | str | `created` / `running` / `done` / `failed` |
| `created_at` | datetime | |
| `finished_at` | datetime, nullable | |
| `notes` | text, nullable | |

**`ExperimentMetric`**
| column | type | notes |
|---|---|---|
| `id` | int PK | |
| `run_id` | str, FK→ExperimentRun.id, indexed | |
| `metric_name` | str | e.g. `sharpe`, `calmar` |
| `value` | float, nullable | nullable = not computable (empty trades) |
| `is_oos` | bool | in-sample vs out-of-sample |
| `window` | str, nullable | walk-forward window tag, e.g. `2019-2020` |
| — | | **UniqueConstraint(`run_id`, `metric_name`, `is_oos`, `window`)** |

**`ExperimentEquity`**
| column | type | notes |
|---|---|---|
| `id` | int PK | |
| `run_id` | str, FK, indexed | |
| `window` | str, nullable | |
| `is_oos` | bool | |
| `equity_json` | text | serialized equity curve (date→equity) |

Rationale: metrics as rows (not a wide json) so 2.5 walk-forward can tag IS/OOS per window and 2.6 can query/aggregate without parsing blobs. Equity kept as json blob (mirrors 1.12 `equity_json`) since it's read whole.

### 4.2 What 2.0 implements vs stubs

- 2.0 **implements**: the three ORM models + a minimal `ExperimentRegistry` with `create(name, config_json) -> run_id`, `get(run_id)`, `list()`, `delete(run_id)` (CRUD only, no run logic).
- 2.0 **stubs** (typed signatures + `raise NotImplementedError`): `ExperimentConfig` fields are defined (so schema is frozen) but `ResearchRunner.run` etc. land in their sprints.

### 4.3 `ExperimentConfig` frozen schema (defined now, consumed 2.1+)

```python
class ExperimentConfig(BaseModel):
    name: str
    universe: str | None = None          # UniversePool name (1.13); or...
    codes: list[str] | None = None       # ...explicit codes (mutually exclusive)
    strategy: str                        # StrategyEngine strategy name (1.5)
    start: str
    end: str
    benchmark: str = "csi300"            # key into BenchmarkConfig.indices
    metrics: list[str] | None = None     # None => BacktestConfig.metrics default
    walk_forward: WalkForwardSpec | None = None   # train/test/step; None => single full-range run
    seed: int | None = None
```

Freezing this now is the whole point of 2.0: 2.1–2.6 read these fields; changing them later ripples across the phase.

## 5. `src/research/__init__.py` skeleton (2.0)

Exports the models + registry now; re-exports the (stubbed) engines so downstream imports are stable:

```python
from .models import ExperimentRun, ExperimentMetric, ExperimentEquity
from .experiment import ExperimentConfig, ExperimentResult, WalkForwardSpec
from .registry import ExperimentRegistry
# NOTE: metrics intentionally NOT here — see src/backtest/metrics.py
__all__ = [...]
```

## 6. Test contract (2.0)

| test | asserts |
|---|---|
| `test_index_bar_roundtrip` | `IndexBar` insert/read on in-memory sqlite; unique `(code,date)` enforced |
| `test_get_index_daily_fake` | `FakeProvider` returns synthetic index bars; columns normalized |
| `test_get_index_daily_as_of_no_lookahead` | `as_of` filters `date <= as_of`; no future bar visible |
| `test_get_index_daily_missing_raises` | missing benchmark → `DataError` with code in message |
| `test_experiment_registry_crud` | create/get/list/delete on in-memory sqlite; `config_json` round-trip |
| `test_experiment_metric_unique` | duplicate `(run_id,metric_name,is_oos,window)` rejected |
| `test_research_config_wiring` | real `settings.yaml` loads `benchmark` + `research` sections |
| `test_smoke_real_index` (opt, network-gated) | fetch one real index via AKShare, persist a dummy run; skipped in CI if offline |

All four gates: `ruff check .` / `black --check .` / `mypy src tests main.py` / `pytest -q`.

## 7. Open decisions (need ChatGPT sign-off before coding)

1. **AKShare index fn** — `stock_zh_index_daily` (symbol like `sh000300`, no date range) vs `index_zh_a_hist` (code `000300` + date range + 前/后复权 N/A). Prefer `index_zh_a_hist` for native date-range + integer-date alignment. Agree?
2. **Index table vs flag** — separate `IndexBar` (proposed) vs a `kind` column on `DailyBar`. Proposal: separate table. Agree?
3. **Experiment id** — short uuid PK + unique `name` (proposed) vs name-as-PK. Proposal: uuid + unique name (rename-safe, human-searchable).
4. **Metrics storage shape** — long rows (`ExperimentMetric` per metric, proposed) vs one wide json per run. Proposal: long rows (walk-forward IS/OOS tagging + queryable).
5. **Real-data smoke in CI** — network-gated skip (proposed) vs commit a tiny cached index fixture. Proposal: network-gated skip + optional local fixture.
6. **`astockdata` index fallback** — `NotImplementedError` in 2.0 (proposed) vs implement now. Proposal: defer; AKShare is the default index source.

## 8. Definition of Done (2.0)

- [ ] `IndexBar` ORM + `DataProvider.get_index_daily` + `DataManager.get_index_daily/sync_index` (as_of-safe, missing→`DataError`).
- [ ] `benchmark` config section + `BenchmarkConfig`; `research` config section + `ResearchConfig`.
- [ ] `src/research/` skeleton: `models.py` (3 ORM), `experiment.py` (frozen `ExperimentConfig` + stubs), `registry.py` (CRUD), stubbed `benchmark/runner/walk_forward/report`.
- [ ] `research/metrics.py` deliberately absent; guard comment in `__init__.py`.
- [ ] Test contract §6 green; ≥1 no-look-ahead assertion.
- [ ] Four gates green + CI green.
- [ ] ChatGPT PASS on this design + §7 decisions resolved.
