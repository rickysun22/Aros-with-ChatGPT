# AROS

A-Share Research Operating System.

AROS is a modular A-share research platform for data ingestion, validation, indicators, factors, strategy research, backtesting, and ranking.

## Current scope

- Sprint 1: Project Foundation
- Data range target: 2015-01-01 to 2026-06-30
- Data source: AKShare
- Data frequency: Daily bars

## Core principles

- Single source of truth through `DataManager`
- No future data leakage
- Configurable, testable, explainable modules
- Research first, trading second

## Planned modules

- `src/core`: config, logging, database, exceptions
- `src/data`: ingestion, normalization, validation, management
- `src/indicators`: technical indicators
- `src/factors`: research factors
- `src/strategies`: strategy definitions
- `src/backtest`: backtesting engine
- `src/ranking`: scoring and ranking
- `src/report`: reporting
- `tests`: automated tests

## Development

This repository is developed in sprints. Each sprint ends with validation and review before the next step begins.
