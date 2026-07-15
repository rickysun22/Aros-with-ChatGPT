"""AROS command-line entry point (Typer).

Run with python main.py --help. The core package lives under src/ and is made
importable via the editable install or the pytest pythonpath setting.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import typer

from backtest.engine import BacktestEngine
from core.config import (
    FactorConfig,
    IndicatorConfig,
    StrategyConfig,
    get_config,
)
from core.logging import setup_logging
from data.manager import DataManager
from factors.engine import FactorEngine
from indicators.engine import IndicatorEngine
from ranking.engine import RankingEngine
from report.engine import ReportEngine
from strategies.engine import StrategyEngine
from universe.engine import UniverseEngine
from watchlist.engine import WatchlistEngine

app = typer.Typer(
    help="AROS - A-Share Research Operating System",
    no_args_is_help=True,
)


@app.command()
def version() -> None:
    """Show the AROS version."""
    typer.echo("AROS 0.1.0")


@app.command()
def info() -> None:
    """Show a summary of the active configuration."""
    setup_logging()
    cfg = get_config()
    typer.echo(f"App        : {cfg.app_name}")
    typer.echo(f"Data source: {cfg.data.source} ({cfg.data.frequency})")
    typer.echo(f"Data range : {cfg.data.start_date} ~ {cfg.data.end_date}")
    typer.echo(f"Database   : {cfg.database.url}")
    typer.echo(f"Log level  : {cfg.logging.level}")


@app.command()
def sync(
    code: str = typer.Option(None, "--code", help="Sync one stock daily bars by code"),
    list_stocks: bool = typer.Option(False, "--list", help="Sync the full A-share list"),
) -> None:
    """Sync market data from the provider into the database."""
    setup_logging()
    dm = DataManager()
    if list_stocks:
        typer.echo(f"Synced {dm.sync_stock_list()} stocks")
        return
    if code:
        typer.echo(f"Synced {dm.sync_daily(code)} daily bars for {code}")
        return
    typer.echo("Specify --list or --code CODE", err=True)
    raise typer.Exit(code=1)


@app.command()
def bars(
    code: str = typer.Argument(..., help="Stock code, e.g. 600000"),
    start: str = typer.Option(None, "--start", help="Start date YYYY-MM-DD"),
    end: str = typer.Option(None, "--end", help="End date YYYY-MM-DD"),
) -> None:
    """Print stored daily bars for a stock (read-only)."""
    setup_logging()
    dm = DataManager()
    start_date = date.fromisoformat(start) if start else None
    end_date = date.fromisoformat(end) if end else None
    df = dm.get_daily(code, start_date, end_date)
    typer.echo(f"{code}: {len(df)} bars")
    if not df.empty:
        typer.echo(df.head(10).to_string(index=False))


@app.command()
def indicators(
    code: str | None = typer.Argument(None, help="Stock code, e.g. 600000"),
    list_all: bool = typer.Option(False, "--list", help="List available indicator names"),
    name: list[str] | None = typer.Option(None, "--name", help="Only these indicator name(s)"),
    start: str | None = typer.Option(None, "--start", help="Start date YYYY-MM-DD"),
    end: str | None = typer.Option(None, "--end", help="End date YYYY-MM-DD"),
) -> None:
    """Compute configured indicators for a stock (read-only)."""
    setup_logging()
    cfg = get_config()
    specs = cfg.indicators.enabled
    if name:
        selected = [s for s in specs if s.name in name]
        missing = set(name) - {s.name for s in selected}
        if missing:
            typer.echo(f"Unknown indicator(s): {sorted(missing)}", err=True)
            raise typer.Exit(code=2)
        specs = selected

    if list_all:
        typer.echo("Available indicators: " + ", ".join(IndicatorEngine.available()))
        typer.echo(f"Configured ({len(specs)}): " + ", ".join(s.name for s in specs))
        return

    if not code:
        typer.echo("Specify a stock CODE or use --list", err=True)
        raise typer.Exit(code=1)

    engine = IndicatorEngine.from_config(IndicatorConfig(enabled=specs))
    dm = DataManager()
    start_date = date.fromisoformat(start) if start else None
    end_date = date.fromisoformat(end) if end else None
    df = engine.compute_code(code, dm, start_date, end_date)
    typer.echo(f"{code}: {len(df)} rows")
    if df.empty:
        return
    indicator_cols = [
        c
        for c in df.columns
        if c not in ("date", "open", "high", "low", "close", "volume", "amount", "code")
    ]
    typer.echo(df[["date", "close", *indicator_cols]].tail(10).to_string(index=False))


@app.command()
def factors(
    code: str | None = typer.Argument(None, help="Stock code, e.g. 600000"),
    list_all: bool = typer.Option(False, "--list", help="List available factor names"),
    name: list[str] | None = typer.Option(None, "--name", help="Only these factor name(s)"),
    start: str | None = typer.Option(None, "--start", help="Start date YYYY-MM-DD"),
    end: str | None = typer.Option(None, "--end", help="End date YYYY-MM-DD"),
) -> None:
    """Compute configured indicators then factors for a stock (read-only)."""
    setup_logging()
    cfg = get_config()
    specs = cfg.factors.enabled
    if name:
        selected = [s for s in specs if s.name in name]
        missing = set(name) - {s.name for s in selected}
        if missing:
            typer.echo(f"Unknown factor(s): {sorted(missing)}", err=True)
            raise typer.Exit(code=2)
        specs = selected

    if list_all:
        typer.echo("Available factors: " + ", ".join(FactorEngine.available()))
        typer.echo(f"Configured ({len(specs)}): " + ", ".join(s.name for s in specs))
        return

    if not code:
        typer.echo("Specify a stock CODE or use --list", err=True)
        raise typer.Exit(code=1)

    engine = FactorEngine.from_config(
        IndicatorConfig(enabled=cfg.indicators.enabled),
        FactorConfig(enabled=specs),
    )
    dm = DataManager()
    start_date = date.fromisoformat(start) if start else None
    end_date = date.fromisoformat(end) if end else None
    df = engine.compute_code(code, dm, start_date, end_date)
    typer.echo(f"{code}: {len(df)} rows")
    if df.empty:
        return
    factor_cols = [
        c
        for c in df.columns
        if c not in ("date", "open", "high", "low", "close", "volume", "amount", "code")
    ]
    typer.echo(df[["date", "close", *factor_cols]].tail(10).to_string(index=False))


@app.command()
def strategies(
    code: str | None = typer.Argument(None, help="Stock code, e.g. 600000"),
    list_all: bool = typer.Option(False, "--list", help="List available strategy types"),
    name: list[str] | None = typer.Option(None, "--name", help="Only these strategy name(s)"),
    start: str | None = typer.Option(None, "--start", help="Start date YYYY-MM-DD"),
    end: str | None = typer.Option(None, "--end", help="End date YYYY-MM-DD"),
) -> None:
    """Compute configured strategies (factors then signals) for a stock."""
    setup_logging()
    cfg = get_config()
    specs = cfg.strategies.enabled
    if name:
        selected = [s for s in specs if s.name in name]
        missing = set(name) - {s.name for s in selected}
        if missing:
            typer.echo(f"Unknown strategy(ies): {sorted(missing)}", err=True)
            raise typer.Exit(code=2)
        specs = selected

    if list_all:
        typer.echo("Available strategies: " + ", ".join(StrategyEngine.available()))
        typer.echo(f"Configured ({len(specs)}): " + ", ".join(s.name for s in specs))
        return

    if not code:
        typer.echo("Specify a stock CODE or use --list", err=True)
        raise typer.Exit(code=1)

    engine = StrategyEngine.from_config(
        IndicatorConfig(enabled=cfg.indicators.enabled),
        FactorConfig(enabled=cfg.factors.enabled),
        StrategyConfig(enabled=specs),
    )
    dm = DataManager()
    start_date = date.fromisoformat(start) if start else None
    end_date = date.fromisoformat(end) if end else None
    df = engine.compute_code(code, dm, start_date, end_date)
    typer.echo(f"{code}: {len(df)} rows")
    if df.empty:
        return
    signal_cols = [c for c in df.columns if c == "signal" or c.startswith("signal_")]
    typer.echo(df[["date", "close", *signal_cols]].tail(10).to_string(index=False))


@app.command()
def backtest(
    code: str | None = typer.Argument(None, help="Stock code, e.g. 600000"),
    list_all: bool = typer.Option(
        False, "--list", help="List available strategy names for backtest"
    ),
    name: str | None = typer.Option(
        None, "--strategy", help="Backtest this strategy signal_<name>"
    ),
    start: str | None = typer.Option(None, "--start", help="Start date YYYY-MM-DD"),
    end: str | None = typer.Option(None, "--end", help="End date YYYY-MM-DD"),
) -> None:
    """Backtest a configured strategy as a cost-aware A-share portfolio."""
    setup_logging()
    cfg = get_config()
    specs = cfg.strategies.enabled
    if list_all:
        typer.echo("Available strategies: " + ", ".join(StrategyEngine.available()))
        typer.echo(f"Configured ({len(specs)}): " + ", ".join(s.name for s in specs))
        default_strategy = cfg.backtest.strategy or (specs[0].name if specs else "none")
        typer.echo(f"Default backtest strategy: {default_strategy}")
        return
    if not code:
        typer.echo("Specify a stock CODE or use --list", err=True)
        raise typer.Exit(code=1)
    engine = BacktestEngine.from_config(
        IndicatorConfig(enabled=cfg.indicators.enabled),
        FactorConfig(enabled=cfg.factors.enabled),
        StrategyConfig(enabled=specs),
        cfg.backtest,
    )
    dm = DataManager()
    start_date = date.fromisoformat(start) if start else None
    end_date = date.fromisoformat(end) if end else None
    signal_col = f"signal_{name}" if name else None
    df, metrics = engine.run_code(code, dm, start_date, end_date, signal_col)
    if isinstance(metrics, dict) and metrics == {}:
        typer.echo(f"{code}: no data", err=True)
        raise typer.Exit(code=1)
    used = engine.config.strategy or (engine.names[0] if engine.names else "unknown")
    typer.echo(f"{code}: {len(df)} rows, strategy={used}")
    typer.echo("Metrics:")
    for k, v in metrics.items():
        if isinstance(v, float):
            typer.echo(f"  {k:>14}: {v:>10.4f}")
        else:
            typer.echo(f"  {k:>14}: {v}")
    typer.echo("Equity curve (last 10):")
    cols = [c for c in ("date", "close", "position", "equity") if c in df.columns]
    typer.echo(df[cols].tail(10).to_string(index=False))


@app.command()
def ranking(
    codes: list[str] = typer.Argument(None, help="One or more stock codes, e.g. 600000 600519"),
    list_all: bool = typer.Option(False, "--list", help="List strategies available for ranking"),
    top_n: int | None = typer.Option(None, "--top-n", help="Override ranking.top_n"),
    as_of: str | None = typer.Option(None, "--as-of", help="Cross-section date YYYY-MM-DD"),
    start: str | None = typer.Option(None, "--start", help="Start date YYYY-MM-DD"),
    end: str | None = typer.Option(None, "--end", help="End date YYYY-MM-DD"),
) -> None:
    """Rank candidate stocks by composite strategy score; print Top-N."""
    setup_logging()
    cfg = get_config()
    specs = cfg.strategies.enabled
    if list_all:
        typer.echo("Available strategies: " + ", ".join(StrategyEngine.available()))
        typer.echo(f"Configured ({len(specs)}): " + ", ".join(s.name for s in specs))
        dims = (
            ", ".join(f"{d.strategy}(w={d.weight})" for d in cfg.ranking.dimensions)
            if cfg.ranking.dimensions is not None
            else ", ".join(s.name for s in specs)
        )
        typer.echo(f"Ranking dimensions (equal weight if null): {dims}")
        typer.echo(f"top_n: {cfg.ranking.top_n}, as_of: {cfg.ranking.as_of or 'latest'}")
        return
    if not codes:
        typer.echo("Specify one or more stock CODES or use --list", err=True)
        raise typer.Exit(code=1)
    rc = cfg.ranking
    if top_n is not None:
        rc = rc.model_copy(update={"top_n": top_n})
    if as_of is not None:
        rc = rc.model_copy(update={"as_of": as_of})
    engine = RankingEngine.from_config(
        IndicatorConfig(enabled=cfg.indicators.enabled),
        FactorConfig(enabled=cfg.factors.enabled),
        StrategyConfig(enabled=specs),
        rc,
    )
    dm = DataManager()
    start_date = date.fromisoformat(start) if start else None
    end_date = date.fromisoformat(end) if end else None
    table, _scored = engine.rank_universe(list(codes), dm, start_date, end_date)
    if table.empty:
        typer.echo("No ranking produced (no data or no scores).", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"Ranking Top-{len(table)} of {len(codes)} candidates:")
    cols = [c for c in ("rank", "code", "composite_score") if c in table.columns]
    extra = [c for c in table.columns if c.startswith("score_")]
    typer.echo(table[cols + extra].to_string(index=False))


@app.command()
def report(
    codes: list[str] = typer.Argument(None, help="One or more stock codes"),
    list_all: bool = typer.Option(False, "--list", help="List strategies + report config"),
    top_n: int | None = typer.Option(None, "--top-n", help="Override report.top_n"),
    as_of: str | None = typer.Option(None, "--as-of", help="Cross-section date YYYY-MM-DD"),
    start: str | None = typer.Option(None, "--start", help="Start date YYYY-MM-DD"),
    end: str | None = typer.Option(None, "--end", help="End date YYYY-MM-DD"),
    fmt: str | None = typer.Option(None, "--format", help="Output format: markdown|json|html"),
    out: str | None = typer.Option(None, "--out", help="Write report to FILE"),
    universe: str | None = typer.Option(
        None, "--universe", help="Resolve candidate codes from a named pool"
    ),
    backtest: bool = typer.Option(
        False, "--backtest", help="Attach per-candidate backtest metrics"
    ),
) -> None:
    """Generate the daily research report (ranking Top-N + price snapshots)."""
    setup_logging()
    cfg = get_config()
    specs = cfg.strategies.enabled
    if list_all:
        typer.echo("Available strategies: " + ", ".join(StrategyEngine.available()))
        typer.echo(f"Configured ({len(specs)}): " + ", ".join(s.name for s in specs))
        rp = cfg.report
        typer.echo(
            f"Report: top_n={rp.top_n}, as_of={rp.as_of or 'latest'}, "
            f"format={rp.format}, freshness_days={rp.freshness_days}, "
            f"include_detail={rp.include_detail}, include_backtest={rp.include_backtest}"
        )
        return
    if universe is not None:
        ue = UniverseEngine()
        codes = ue.get_codes(universe)
        if not codes:
            typer.echo(f"Universe {universe!r} is empty or unknown", err=True)
            raise typer.Exit(code=1)
        typer.echo(f"Resolved {len(codes)} codes from universe {universe!r}")
    if not codes:
        typer.echo("Specify one or more stock CODES, or use --universe NAME", err=True)
        raise typer.Exit(code=1)
    rp = cfg.report
    updates: dict[str, Any] = {}
    if top_n is not None:
        updates["top_n"] = top_n
    if as_of is not None:
        updates["as_of"] = as_of
    if fmt is not None:
        updates["format"] = fmt
    if backtest:
        updates["include_backtest"] = True
    if updates:
        rp = rp.model_copy(update=updates)
    engine = ReportEngine.from_config(
        IndicatorConfig(enabled=cfg.indicators.enabled),
        FactorConfig(enabled=cfg.factors.enabled),
        StrategyConfig(enabled=specs),
        cfg.ranking,
        rp,
        backtest=cfg.backtest if rp.include_backtest else None,
    )
    dm = DataManager()
    start_date = date.fromisoformat(start) if start else None
    end_date = date.fromisoformat(end) if end else None
    daily = engine.generate(list(codes), dm, start_date, end_date)
    if rp.format == "json":
        text = daily.to_json()
    elif rp.format == "html":
        text = daily.to_html(rp.include_detail)
    else:
        text = daily.to_markdown(rp.include_detail)
    if out:
        Path(out).write_text(text, encoding="utf-8")
        typer.echo(f"Report written to {out} ({len(daily.rows)} rows)")
    else:
        typer.echo(text)


@app.command()
def watchlist(
    action: str = typer.Argument(..., help="add|remove|list|snapshot|history|digest"),
    code: str = typer.Argument(None, help="CODE for add/remove/history"),
    note: str | None = typer.Option(None, "--note", help="Note for add"),
    limit: int = typer.Option(20, "--limit", help="History rows to show"),
    as_of: str | None = typer.Option(None, "--as-of", help="Cross-section date YYYY-MM-DD"),
    start: str | None = typer.Option(None, "--start", help="Start date YYYY-MM-DD"),
    end: str | None = typer.Option(None, "--end", help="End date YYYY-MM-DD"),
    fmt: str = typer.Option("markdown", "--format", help="digest output: markdown|json"),
    backtest: bool = typer.Option(
        False, "--backtest", help="snapshot 时附上每只标的回测表现并落库 (BacktestPoint)"
    ),
) -> None:
    """Track a watchlist: persist daily ranking + show day-over-day deltas."""

    setup_logging()
    cfg = get_config()
    re = RankingEngine.from_config(cfg.indicators, cfg.factors, cfg.strategies, cfg.ranking)
    wl_cfg = cfg.watchlist
    if backtest:
        wl_cfg = wl_cfg.model_copy(update={"include_backtest": True})
    eng = WatchlistEngine(
        re,
        wl_cfg,
        backtest_config=cfg.backtest,
        indicators=cfg.indicators,
        factors=cfg.factors,
        strategies=cfg.strategies,
    )
    dm = DataManager()
    start_date = date.fromisoformat(start) if start else None
    end_date = date.fromisoformat(end) if end else None

    if action == "add":
        if not code:
            typer.echo("add requires a CODE", err=True)
            raise typer.Exit(code=1)
        eng.add(code, note)
        typer.echo(f"added {code} to watchlist")
    elif action == "remove":
        if not code:
            typer.echo("remove requires a CODE", err=True)
            raise typer.Exit(code=1)
        eng.remove(code)
        typer.echo(f"removed {code} from watchlist")
    elif action == "list":
        active = eng.list_active()
        typer.echo(
            "Watchlist (" + str(len(active)) + "): " + (", ".join(active) if active else "(empty)")
        )
        typer.echo(f"Backtest in snapshot: {wl_cfg.include_backtest}")
    elif action == "snapshot":
        digest = eng.snapshot(as_of, data_manager=dm, start_date=start_date, end_date=end_date)
        text = (
            digest.to_json() if fmt == "json" else digest.to_markdown(cfg.watchlist.alert_rank_jump)
        )
        typer.echo(text)
    elif action == "history":
        if not code:
            typer.echo("history requires a CODE", err=True)
            raise typer.Exit(code=1)
        for pt in eng.history(code, limit):
            typer.echo(f"{pt.as_of} rank={pt.rank} score={pt.composite_score}")
    elif action == "digest":
        digest = eng.deltas(as_of)
        text = (
            digest.to_json() if fmt == "json" else digest.to_markdown(cfg.watchlist.alert_rank_jump)
        )
        typer.echo(text)
    else:
        typer.echo(f"unknown action: {action}", err=True)
        raise typer.Exit(code=1)


@app.command()
def universe(
    action: str = typer.Argument(..., help="add|remove|list|show|delete"),
    name: str = typer.Argument(None, help="Pool name (add/remove/show/delete)"),
    codes: list[str] = typer.Argument(None, help="Codes for add/remove"),
) -> None:
    """Manage named stock pools (candidate universes) for the report command."""
    setup_logging()
    eng = UniverseEngine()
    if action == "add":
        if not name:
            typer.echo("add requires a pool NAME", err=True)
            raise typer.Exit(code=1)
        eng.add_codes(name, list(codes or []))
        typer.echo(f"Pool {name!r}: {eng.get_codes(name)}")
    elif action == "remove":
        if not name:
            typer.echo("remove requires a pool NAME", err=True)
            raise typer.Exit(code=1)
        eng.remove_codes(name, list(codes or []))
        typer.echo(f"Pool {name!r}: {eng.get_codes(name)}")
    elif action == "list":
        pools = eng.list_pools()
        typer.echo(f"Universe pools ({len(pools)}): " + (", ".join(pools) if pools else "(none)"))
    elif action == "show":
        if not name:
            typer.echo("show requires a pool NAME", err=True)
            raise typer.Exit(code=1)
        typer.echo(f"{name!r}: {eng.get_codes(name)}")
    elif action == "delete":
        if not name:
            typer.echo("delete requires a pool NAME", err=True)
            raise typer.Exit(code=1)
        ok = eng.delete(name)
        typer.echo(f"deleted {name!r}" if ok else f"pool {name!r} not found")
    else:
        typer.echo(f"unknown action: {action}", err=True)
        raise typer.Exit(code=1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
