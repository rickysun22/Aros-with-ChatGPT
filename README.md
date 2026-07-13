# AROS

A-Share Research Operating System.

AROS is a modular A-share research platform for data ingestion, validation, indicators, factors, strategy research, backtesting, and ranking.

## Status

| Sprint | Scope | Status |
|--------|-------|--------|
| **1.1** | Project Foundation (scaffold, config, logging, db, CLI, tests) | ✅ completed |
| 1.2+ | Database Layer, AKShare Layer, DataManager, indicators, factors, strategies, backtest | ⏳ planned |

- Data range target: 2015-01-01 to 2026-06-30
- Data source: AKShare
- Data frequency: Daily bars

## Core principles

- Single source of truth through `DataManager`
- No future data leakage
- Configurable, testable, explainable modules
- Research first, trading second

## Project layout

```
Aros-with-ChatGPT/
├── config/settings.yaml   # runtime configuration (data range, paths, db)
├── src/core/              # foundation: config, logging, database, exceptions
├── main.py                # Typer CLI entry point
├── tests/                 # automated tests
├── pyproject.toml         # deps + tooling (pytest / ruff / black / mypy)
├── requirements.txt       # runtime + dev dependencies
└── .env.example           # local override template
```

## Development setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e ".[dev]"      # editable install so `core` is importable
cp .env.example .env         # optional local overrides
```

## Quality gates

```bash
pytest            # run the test suite
ruff check .      # lint
black --check .   # format check
mypy src tests    # static type check
```

All four gates must pass before a sprint is considered done.

## Usage

```bash
python main.py --help
python main.py version
python main.py info
```

## Planned modules

- `src/core` (done): config, logging, database, exceptions
- `src/data`: ingestion, normalization, validation, management
- `src/indicators`: technical indicators
- `src/factors`: research factors
- `src/strategies`: strategy definitions
- `src/backtest`: backtesting engine
- `src/ranking`: scoring and ranking
- `src/report`: reporting

## Development

This repository is developed in sprints. Each sprint ends with validation and review before the next step begins.
