# Sprint 2.1 — Research CLI & Registry Surface (Technical Design)

> Status: **Technical design** — for GPT PASS + frozen decisions *before* any code lands.
> Builds on the Sprint 2.0 foundation (committed `dcb2c98`).
> Companion docs: `Phase2-Implementation-Plan.md` (roadmap 2.0–2.6),
> `Phase2-Research-Engine-Revision.md` (why), `Sprint2.0-Technical-Design.md` (foundation contract).

## 1. Purpose & scope

The Phase 2 implementation plan (§4) assigns **"Sprint 2.1 — Experiment Registry &
Config"** to the research registry. Sprint 2.0 — per the frozen design and GPT PASS —
already delivered the *classes* behind that:

- `ExperimentConfig` (frozen protocol), `WalkForwardSpec`, `ExperimentResult` (`src/research/experiment.py`)
- `ExperimentRun` / `ExperimentMetric` / `ExperimentEquity` ORM (`src/research/models.py`)
- `ExperimentRegistry` CRUD (`src/research/registry.py`)
- `BenchmarkConfig` / `ResearchConfig` + `config/settings.yaml` (`src/core/config.py`)

What 2.0 did **not** ship is the **CLI surface** `main.py research init|list|show|delete`
— which the plan explicitly lists under 2.1 — and a **complete `delete`** (child rows
are not yet purged). So **Sprint 2.1 = the command-line surface + delete-cascade
refinement**. It makes the already-built registry/ORM usable from the terminal.

**Out of scope (still stubs, deferred):** runner (2.4), benchmark compare (2.3),
walk-forward (2.5), report (2.6), metrics extension (2.2). 2.1 only *creates and
inspects* experiment **definitions**; it runs no backtest, computes no metric, fetches
no market data.

## 2. Reuse map (no rebuild)

| 2.1 need | Reuse (do NOT rebuild) |
|---|---|
| Research CLI group | `main.py` Typer — mirror the `universe` / `watchlist` command style |
| Persist / inspect runs | `ExperimentRegistry` (2.0) + `ExperimentRun` / `ExperimentMetric` / `ExperimentEquity` ORM (2.0) |
| Resolve a universe name | `UniverseEngine.get_codes` (1.13) |
| Serializable config schema | `ExperimentConfig` (2.0, **frozen**) |
| DB engine / session | `core.database` (`get_engine` / `get_sessionmaker`) — same cached-engine + autouse test isolation used everywhere |
| Default config values | `AppConfig` (`benchmark.default`, `backtest.strategy`) |
| Metric math | **none** — all metrics stay in `src/backtest/metrics.py` (mirror-free rule from `Phase2-Research-Engine-Revision.md`) |

## 3. CLI contract

Use a Typer **sub-app** so the surface is `python main.py research init|list|show|delete`.

```python
research_app = typer.Typer(help="Phase 2 research experiments (Sprint 2.1)")

@research_app.command("init")   # create a run from a config
@research_app.command("list")   # list runs, newest first
@research_app.command("show")   # show one run (config + lifecycle)
@research_app.command("delete") # delete a run (cascade children)
app.add_typer(research_app, name="research")
```

### 3.1 `research init`

Creates a run from a serializable `ExperimentConfig`. **Two input paths:**

- **Path A — flags:** `--name` (required), `--strategy` (default `cfg.backtest.strategy`),
  `--start` / `--end` (required, `YYYY-MM-DD`), `--universe NAME` **XOR** `--codes a b c`,
  `--benchmark KEY` (default `cfg.benchmark.default`), `--metrics m1 m2 ...` (optional),
  `--walk-forward TRAIN TEST STEP` (optional → `WalkForwardSpec`), `--notes TEXT`,
  `--dry-run` (print config, do not persist).
- **Path B — file:** `--config PATH` (JSON *or* YAML) carries the full `ExperimentConfig`;
  other flags are ignored when `--config` is given (documented; edit the file to tweak).
  `--dry-run` is still allowed.

Behavior:
- `--universe` + `--codes` together → exit code 2 (mutual exclusivity, mirrors
  `ExperimentConfig`'s `model_validator`).
- If `--universe` given: `UniverseEngine().get_codes(universe)`; empty/unknown → exit 1
  ("universe ... is empty or unknown"). The **name** is stored (not the resolved codes —
  the runner resolves at run time in 2.4), so the config stays stable.
- Build the `ExperimentConfig`, then `registry.create(name, cfg.model_dump_json())`.
- On success: `Created experiment <run_id> (name="<name>")`.
- With `--dry-run`: print the resolved config as JSON + `"(not persisted)"`; **no DB write**.

### 3.2 `research list`

`registry.list()` (newest first). Print columns `RUN_ID | NAME | STATUS | CREATED_AT`.
No runs → `No experiments yet.`

### 3.3 `research show RUN_ID`

`registry.get(run_id)`; `None` → exit 1 (`run <id> not found`). Otherwise print:

```
Run:      <run_id>
Name:     <name>
Status:   <status>
Created:  <created_at>
Finished: <finished_at or "-">
Notes:    <notes or "-">
Config:
{ExperimentConfig parsed from config_json, pretty JSON}
```

### 3.4 `research delete RUN_ID`

`registry.delete(run_id)`; `False` → exit 1 (`run <id> not found`). `True` →
`deleted <run_id>`. Child `ExperimentMetric` / `ExperimentEquity` rows are cascade-removed
(see §5).

## 4. Config construction

A private helper in `main.py`, `_build_experiment_config(...)`, maps flags →
`ExperimentConfig` fields. `--walk-forward t s st` →
`WalkForwardSpec(train_years=t, test_years=s, step_years=st)`. For `--config PATH`:
`json.loads` → `ExperimentConfig.model_validate`; on `JSONDecodeError` fall back to
`yaml.safe_load` → `model_validate`. The resulting object is round-trippable through
`model_dump_json()` / `model_validate_json` (already proven by the 2.0 test contract).

## 5. Registry refinement — delete cascade

`ExperimentRegistry.delete` (2.0 CRUD stub) is enhanced to **also purge** the run's
`ExperimentMetric` and `ExperimentEquity` rows before deleting the run.

Rationale: the child FKs use plain `ForeignKey(...)` with **no** `ondelete="CASCADE"`,
and SQLite ships foreign-key enforcement **off** by default (SQLAlchemy does not enable
`PRAGMA foreign_keys=ON` automatically). Explicit deletion is therefore the reliable path
and keeps the ORM unchanged. Import `ExperimentMetric` / `ExperimentEquity` into
`registry.py` and delete them by `run_id` first.

```python
def delete(self, run_id: str) -> bool:
    run = self.session.get(ExperimentRun, run_id)
    if run is None:
        return False
    self.session.query(ExperimentMetric).filter_by(run_id=run_id).delete()
    self.session.query(ExperimentEquity).filter_by(run_id=run_id).delete()
    self.session.delete(run)
    self.session.commit()
    return True
```

## 6. No-future-function note

`init` performs **no** backtest / metric computation and reads at most the universe
membership list (a static pool, not market data). `list` / `show` / `delete` are pure
reads/deletes. 2.1 therefore introduces **no look-ahead surface** — the no-look-ahead
invariant is inherited from 2.0, not newly tested here (the config round-trip test still
proves serialization integrity).

## 7. File changes

| File | Change |
|---|---|
| `main.py` | Add `research_app` sub-app (4 subcommands) + `_build_experiment_config` helper; `app.add_typer(research_app, name="research")`. |
| `src/research/registry.py` | `delete` cascade (purge `ExperimentMetric` / `ExperimentEquity`). |
| `tests/test_research.py` (extend) | CLI smoke + cascade tests (§8). |
| `CHANGELOG.md` / `Roadmap.md` | Add Sprint 2.1 section / row **at merge time** (per the 2.0 pattern). |

No new engine module, no new metrics, no `research/metrics.py`.

## 8. Test contract

Uses `typer.testing.CliRunner` + `monkeypatch.setenv("AROS_DATABASE_URL", "sqlite:///<tmp>")`;
the autouse `_isolate_runtime` fixture (conftest.py) resets `get_config` / `_ENGINE` per
test, exactly like `test_backtest.py` / `test_universe.py`.

- `test_cli_research_init_flags` — init via flags; exit 0; printed `run_id` starts with `exp_`.
- `test_cli_research_init_config_file` — write a temp JSON config; `research init --config`; then `research show <id>` round-trips the config.
- `test_cli_research_init_both_sources_fails` — `--universe U --codes a` → exit code != 0.
- `test_cli_research_init_unknown_universe_fails` — unknown universe → exit 1.
- `test_cli_research_init_dry_run` — `--dry-run`; `research list` is empty; output contains the config JSON.
- `test_cli_research_list_show_delete` — init → list shows it → show prints config → delete removes it → second delete → exit 1.
- `test_registry_delete_cascades` — add a child `ExperimentMetric` to a run, `registry.delete(run_id)`, assert the metric row is gone.

## 9. Acceptance

- `ruff check .` + `black --check .` + `mypy src tests main.py` + `pytest -q` all green
  (pytest gains ~7 tests; existing 184 still pass).
- Config round-trip; registry CRUD + delete-cascade; all four CLI subcommands smoke-tested;
  **no network** needed.
- No new metric math outside `src/backtest/metrics.py`.

## 10. Decisions for GPT to freeze (before code)

- **D1 — CLI style:** Typer sub-app `research init|list|show|delete` *(recommended)* vs flat `research-init`.
- **D2 — `--universe` at init:** store the **name** (validate existence only); resolve to codes at run time (2.4) *(recommended)* vs resolve now and store codes.
- **D3 — `--config` format:** accept **JSON and YAML** *(recommended)* vs JSON only.
- **D4 — delete cascade:** explicit child deletion inside `registry.delete` (no FK `ondelete`) *(recommended)* vs add `ondelete="CASCADE"` + `PRAGMA foreign_keys`.
- **D5 — `--walk-forward TRAIN TEST STEP`:** persist a `WalkForwardSpec` now; runs land in 2.5 *(recommended yes)*.
- **D6 — `--dry-run` on `init`:** include it for safe inspection *(recommended yes)*.
- **D7 — `--strategy` validation at init:** reject unknown strategy names (exit 2, checked against `cfg.strategies.enabled`) for fail-fast *(recommended)* vs pass-through (runner validates in 2.4).

**Carried forward (NOT decided in 2.1):** walk-forward defaults (proposed 3y/1y/1y),
risk-free rate source, scheduler integration, the 2.2 metric list — all belong to their
own sprints.
