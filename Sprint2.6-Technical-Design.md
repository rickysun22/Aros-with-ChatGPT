# Sprint 2.6 — Research Report (Technical Design)

**Status:** implemented (2026-07-17). Fills the `src/research/report.py`
`NotImplementedError` stub.

## Goal

Turn a persisted experiment (metrics + benchmark comparison + walk-forward IS/OOS)
into a shareable report in three formats — **markdown / json / html** — without
inventing any new metric math. The report is a *pure function* of an
`ExperimentResult` (+ optional DB run metadata), so it renders either a fresh
in-memory result or one reconstructed from the database.

## Decisions (frozen)

- **D1 — Renderer is a dataclass, not a service.** `ResearchReport` carries the
  fully-rendered payload (`run_id`, name, strategy, start, end, benchmark, status,
  `is_oos`, windows, metrics, equity, `generated_at`). Builders `from_run(run,
  result)` and `from_result(result)`; serializers `to_dict/to_json/to_markdown/
  to_html`. No `DataManager` / DB access inside the renderer — keep it pure.
- **D2 — Reuse the `DailyReport` visual language.** Inline CSS + inline SVG bars
  (from 1.8 / 1.14). HTML must be **self-contained and offline**: no
  `http(s)://` references, no external JS/CSS. A single-range run has *no* chart;
  a walk-forward run renders an IS-vs-OOS diverging-bar SVG.
- **D3 — Markdown is the machine-reference format.** Each metric renders as
  `中文标签 \`raw_key\`` so both the human label and the raw key are present
  (parsable, unambiguous). JSON exposes the raw keys directly.
- **D4 — DB reconstruction lives in the registry, not the renderer.**
  `ExperimentRegistry.load_result(run_id) -> ExperimentResult | None` reads
  `ExperimentMetric` + `ExperimentEquity` grouped by `window`, orders windows, and
  derives `is_oos` from the window names. Returns `None` when the run is missing.
- **D5 — CLI surface.** `research report <id> [--format markdown|json|html]`
  (default `markdown`). Loads `ExperimentRun` + reconstructed `ExperimentResult`
  via the registry and prints the report. `research show` is unchanged.
- **D6 — No ORM schema change, no new metric functions.** Report + loader only
  *present / reconstruct* existing data.

## No-look-ahead

Not applicable at the rendering layer — the report only displays numbers the
runner (2.4) and walk-forward runner (2.5) already produced under their
double no-look-ahead guarantee. The loader (`load_result`) is a faithful 1:1
reconstruction of those stored values.

## Files

| File | Change |
|------|--------|
| `src/research/report.py` | `ResearchReport` + `render_experiment_report` (stub entry point) |
| `src/research/registry.py` | `load_result(run_id)` |
| `src/research/__init__.py` | export `ResearchReport`, `render_experiment_report` |
| `main.py` | `research report <id> [--format ...]` |
| `tests/test_research.py` | +8 cases |

## Tests (8)

1. markdown carries id + OOS flag + raw/bench keys (raw key + Chinese label).
2. `render_experiment_report` stub returns markdown with id + OOS flag.
3. json round-trip (run_id, is_oos, metric values).
4. html self-contained + offline; single-run has no `<svg>`.
5. walk-forward report has IS/OOS section + SVG + IS-OOS decay column.
6. `load_result` DB round-trip (in-memory session) feeds `from_run` (name /
   benchmark / status / run_id correct).
7. CLI `research report <id>` markdown + `--format json` + `--format html`.
8. (covers load + render integration) — all of the above exercise both builders.

## Gates

ruff / black / mypy (68 files) / pytest — **229 passed, 1 skipped**.
