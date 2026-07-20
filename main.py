"""AROS command-line entry point (Typer).

Run with python main.py --help. The core package lives under src/ and is made
importable via the editable install or the pytest pythonpath setting.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any

import typer
import yaml

from backtest.engine import BacktestEngine
from backtest.portfolio import PortfolioBacktest
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
from research.experiment import ExperimentConfig, WalkForwardSpec
from research.registry import ExperimentRegistry
from research.report import ResearchReport
from scheduler import Scheduler, build_notifier
from strategies.engine import StrategyEngine
from universe.engine import UniverseEngine
from watchlist.engine import WatchlistEngine

app = typer.Typer(
    help="AROS - A-Share Research Operating System",
    no_args_is_help=True,
)


def _kb_session() -> Any:
    """Open a DB session with all ORM tables created (KB / validation CLI)."""
    from core.database import Base, get_engine, get_sessionmaker

    engine = get_engine()
    Base.metadata.create_all(engine)
    return get_sessionmaker(engine)()


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


@app.command()
def schedule(
    every: int = typer.Option(30, "--every", help="Interval in minutes between runs"),
    once: bool = typer.Option(False, "--once", help="Run a single cycle then exit"),
    report: bool = typer.Option(False, "--report", help="Scheduled task: daily report"),
    watchlist: bool = typer.Option(False, "--watchlist", help="Scheduled task: watchlist digest"),
    codes: list[str] = typer.Argument(None, help="Codes for report (or use --universe)"),
    universe: str | None = typer.Option(
        None, "--universe", help="Resolve report codes from a pool"
    ),
    backtest: bool = typer.Option(False, "--backtest", help="Attach backtest metrics"),
) -> None:
    """Run a report/digest on an interval and push it via the configured notifier."""
    setup_logging()
    cfg = get_config()
    sched = Scheduler(build_notifier(cfg.scheduler))
    if report:

        def task() -> str:
            rp = cfg.report
            if backtest:
                rp = rp.model_copy(update={"include_backtest": True})
            resolved = list(codes or [])
            if universe is not None:
                resolved = UniverseEngine().get_codes(universe)
            if not resolved:
                return "(no codes: pass CODEs or --universe)"
            eng = ReportEngine.from_config(
                IndicatorConfig(enabled=cfg.indicators.enabled),
                FactorConfig(enabled=cfg.factors.enabled),
                StrategyConfig(enabled=cfg.strategies.enabled),
                cfg.ranking,
                rp,
                backtest=cfg.backtest if rp.include_backtest else None,
            )
            dm = DataManager()
            daily = eng.generate(resolved, dm, None, None)
            return daily.to_markdown(rp.include_detail)

        interval = every * 60
    elif watchlist:

        def task() -> str:
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
            digest = eng.deltas(None)
            return digest.to_markdown(cfg.watchlist.alert_rank_jump)

        interval = every * 60
    else:
        typer.echo("specify --report or --watchlist", err=True)
        raise typer.Exit(code=1)

    if once:
        sched.run_ntimes(task, 0, 1)
    else:
        typer.echo(f"Scheduling every {every} min (Ctrl-C to stop)...")
        sched.run_loop(task, interval)


@app.command()
def portfolio(
    codes: list[str] = typer.Argument(None, help="One or more stock codes"),
    top_n: int = typer.Option(10, "--top-n", help="Hold the Top-N ranked codes"),
    rebalance: str = typer.Option("ME", "--rebalance", help="pandas freq: ME|W|Q|..."),
    universe: str | None = typer.Option(None, "--universe", help="Resolve codes from a pool"),
    start: str | None = typer.Option(None, "--start", help="Start date YYYY-MM-DD"),
    end: str | None = typer.Option(None, "--end", help="End date YYYY-MM-DD"),
) -> None:
    """Backtest a Top-N rebalancing portfolio over the candidate set."""
    setup_logging()
    cfg = get_config()
    if universe is not None:
        codes = UniverseEngine().get_codes(universe)
    if not codes:
        typer.echo("Specify one or more stock CODES, or use --universe NAME", err=True)
        raise typer.Exit(code=1)
    eng = PortfolioBacktest.from_config(
        cfg.indicators,
        cfg.factors,
        cfg.strategies,
        cfg.ranking,
        cfg.backtest,
        top_n=top_n,
        rebalance_freq=rebalance,
    )
    dm = DataManager()
    start_date = date.fromisoformat(start) if start else None
    end_date = date.fromisoformat(end) if end else None
    res = eng.run(list(codes), dm, start_date, end_date)
    if res.equity.empty:
        typer.echo("无数据/无候选，无法回测组合", err=True)
        raise typer.Exit(code=1)
    typer.echo(
        f"组合回测 top_n={top_n} rebalance={rebalance}: "
        f"{len(codes)} 候选, {len(res.selections)} 次再平衡"
    )
    for k, v in res.metrics.items():
        typer.echo(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")
    typer.echo("再平衡持仓（前 5 次）:")
    for d, sel in res.selections[:5]:
        typer.echo(f"  {d.date()}: {sel}")


def _resolve_cli_experiment_config(
    cfg: Any,
    *,
    name: str | None,
    strategy: str | None,
    start: str | None,
    end: str | None,
    universe: str | None,
    codes: str | None,
    benchmark: str | None,
    metrics: str | None,
    walk_forward: tuple[int, int, int] | None,
    seed: int | None,
) -> ExperimentConfig:
    """Build a validated :class:`ExperimentConfig` from CLI flags.

    Shared by ``research init`` and ``research run`` so both keep the same
    validation / resolution rules. Raises ``typer.Exit`` on bad input.
    """
    if name is None or start is None or end is None:
        typer.echo("experiment requires --name/--start/--end (or use --config)", err=True)
        raise typer.Exit(code=2)
    if strategy is None:
        strategy = cfg.backtest.strategy or (
            cfg.strategies.enabled[0].name if cfg.strategies.enabled else None
        )
    if strategy is None:
        typer.echo("no strategy available; pass --strategy", err=True)
        raise typer.Exit(code=2)
    enabled = {s.name for s in cfg.strategies.enabled}
    if strategy not in enabled:
        typer.echo(f"unknown strategy: {strategy}", err=True)
        raise typer.Exit(code=2)
    if universe is not None and codes is not None:
        typer.echo("set either --universe or --codes, not both", err=True)
        raise typer.Exit(code=2)
    if universe is not None:
        try:
            resolved = UniverseEngine().get_codes(universe)
        except Exception:  # noqa: BLE001 - surface any DB issue as a clean error
            resolved = []
        if not resolved:
            typer.echo(f"universe {universe!r} is empty or unknown", err=True)
            raise typer.Exit(code=1)
    resolved_benchmark = benchmark or cfg.benchmark.default
    codes_list = [c.strip() for c in codes.split(",") if c.strip()] if codes else None
    metrics_list = [m.strip() for m in metrics.split(",") if m.strip()] if metrics else None
    return _build_experiment_config(
        name=name,
        strategy=strategy,
        start=start,
        end=end,
        universe=universe,
        codes=codes_list,
        benchmark=resolved_benchmark,
        metrics=metrics_list,
        walk_forward=walk_forward,
        seed=seed,
    )


def _build_experiment_config(
    *,
    name: str,
    strategy: str,
    start: str,
    end: str,
    universe: str | None,
    codes: list[str] | None,
    benchmark: str,
    metrics: list[str] | None,
    walk_forward: tuple[int, int, int] | None,
    seed: int | None,
) -> ExperimentConfig:
    """Map CLI flags to a validated :class:`ExperimentConfig`."""
    wf = None
    if walk_forward is not None:
        wf = WalkForwardSpec(
            train_years=walk_forward[0],
            test_years=walk_forward[1],
            step_years=walk_forward[2],
        )
    return ExperimentConfig(
        name=name,
        strategy=strategy,
        start=start,
        end=end,
        universe=universe,
        codes=codes,
        benchmark=benchmark,
        metrics=metrics,
        walk_forward=wf,
        seed=seed,
    )


def _load_config_file(path: Path) -> dict[str, Any]:
    """Read a JSON or YAML config file into a dict.

    JSON first; fall back to YAML so a ``.yaml`` experiment spec works too.
    """
    text = Path(path).read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        data: dict[str, Any] = yaml.safe_load(text)
        return data
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = yaml.safe_load(text)
    return data


research_app = typer.Typer(help="Phase 2 research experiments (Sprint 2.1)")


@research_app.command("init")
def research_init(
    name: str | None = typer.Option(None, "--name", help="Experiment name"),
    strategy: str | None = typer.Option(
        None, "--strategy", help="Strategy name (default: configured)"
    ),
    start: str | None = typer.Option(None, "--start", help="Start date YYYY-MM-DD"),
    end: str | None = typer.Option(None, "--end", help="End date YYYY-MM-DD"),
    universe: str | None = typer.Option(
        None, "--universe", help="Universe pool name (XOR --codes)"
    ),
    codes: str | None = typer.Option(
        None, "--codes", help="Comma-separated codes (XOR --universe)"
    ),
    benchmark: str | None = typer.Option(
        None, "--benchmark", help="Benchmark key (default: configured)"
    ),
    metrics: str | None = typer.Option(None, "--metrics", help="Comma-separated metric names"),
    walk_forward: tuple[int, int, int] | None = typer.Option(
        None, "--walk-forward", help="Walk-forward TRAIN TEST STEP (years)"
    ),
    seed: int | None = typer.Option(None, "--seed", help="Random seed"),
    notes: str | None = typer.Option(None, "--notes", help="Run note"),
    config: Path | None = typer.Option(None, "--config", help="Config file (JSON/YAML)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print config, do not persist"),
) -> None:
    """Create a research experiment from flags or a --config file."""
    setup_logging()
    cfg = get_config()

    if config is not None:
        exp_cfg = ExperimentConfig.model_validate(_load_config_file(config))
    else:
        exp_cfg = _resolve_cli_experiment_config(
            cfg,
            name=name,
            strategy=strategy,
            start=start,
            end=end,
            universe=universe,
            codes=codes,
            benchmark=benchmark,
            metrics=metrics,
            walk_forward=walk_forward,
            seed=seed,
        )

    if dry_run:
        typer.echo(exp_cfg.model_dump_json(indent=2))
        typer.echo("(not persisted)")
        return

    reg = ExperimentRegistry()
    run_id = reg.create(name=exp_cfg.name, config_json=exp_cfg.model_dump_json(), notes=notes)
    typer.echo(f"Created experiment {run_id} (name={exp_cfg.name!r})")


@research_app.command("run")
def research_run(
    name: str | None = typer.Option(None, "--name", help="Experiment name"),
    strategy: str | None = typer.Option(
        None, "--strategy", help="Strategy name (default: configured)"
    ),
    start: str | None = typer.Option(None, "--start", help="Start date YYYY-MM-DD"),
    end: str | None = typer.Option(None, "--end", help="End date YYYY-MM-DD"),
    universe: str | None = typer.Option(
        None, "--universe", help="Universe pool name (XOR --codes)"
    ),
    codes: str | None = typer.Option(
        None, "--codes", help="Comma-separated codes (XOR --universe)"
    ),
    benchmark: str | None = typer.Option(
        None, "--benchmark", help="Benchmark key (default: configured)"
    ),
    metrics: str | None = typer.Option(None, "--metrics", help="Comma-separated metric names"),
    walk_forward: tuple[int, int, int] | None = typer.Option(
        None, "--walk-forward", help="Walk-forward TRAIN TEST STEP (years)"
    ),
    seed: int | None = typer.Option(None, "--seed", help="Random seed"),
    notes: str | None = typer.Option(None, "--notes", help="Run note"),
    config: Path | None = typer.Option(None, "--config", help="Config file (JSON/YAML)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print config, do not run"),
) -> None:
    """Run a research experiment end to end and persist its results."""
    setup_logging()
    cfg = get_config()

    if config is not None:
        exp_cfg = ExperimentConfig.model_validate(_load_config_file(config))
    else:
        exp_cfg = _resolve_cli_experiment_config(
            cfg,
            name=name,
            strategy=strategy,
            start=start,
            end=end,
            universe=universe,
            codes=codes,
            benchmark=benchmark,
            metrics=metrics,
            walk_forward=walk_forward,
            seed=seed,
        )

    if dry_run:
        typer.echo(exp_cfg.model_dump_json(indent=2))
        typer.echo("(not executed)")
        return

    from research.runner import ResearchRunner
    from research.walk_forward import WalkForwardRunner

    if exp_cfg.walk_forward is not None:
        # Transparent dispatch to the walk-forward runner (Sprint 2.5).
        result = WalkForwardRunner().run(exp_cfg, notes=notes)
        is_agg = result.metrics.get("is_agg", {})
        oos_agg = result.metrics.get("oos_agg", {})
        folds = len(result.windows) // 2
        typer.echo(
            f"Run {result.run_id} complete (name={exp_cfg.name!r}, walk-forward, {folds} folds)"
        )
        for key in ("total_return", "sharpe", "bench_excess_return", "bench_beta"):
            typer.echo(f"  IS  {key:<18}: {is_agg.get(key)}")
            typer.echo(f"  OOS {key:<18}: {oos_agg.get(key)}")
    else:
        result = ResearchRunner().run(exp_cfg, notes=notes)
        m = result.metrics.get("full", {})
        typer.echo(f"Run {result.run_id} complete (name={exp_cfg.name!r})")
        typer.echo(f"  total_return      : {m.get('total_return')}")
        typer.echo(f"  sharpe            : {m.get('sharpe')}")
        typer.echo(f"  bench_excess_return: {m.get('bench_excess_return')}")
        typer.echo(f"  bench_beta        : {m.get('bench_beta')}")


def _fmt_ratio_pct(value: float | None) -> str:
    """Format a ratio as a signed percentage, or '-' for missing."""
    if value is None:
        return "-"
    return f"{value * 100:+.1f}%"


def _seed_csi800(ue: Any) -> None:
    """Seed the csi800 pool from AKShare index constituents (index code 000906)."""
    import akshare as ak

    typer.echo("Seeding csi800 constituents from AKShare (000906) ...")
    df = ak.index_stock_cons(symbol="000906")
    # AKShare returns '股票代码' / '股票名称'; fall back to the first column.
    code_col = "股票代码" if "股票代码" in df.columns else df.columns[0]
    codes = [str(c).strip() for c in df[code_col].tolist() if str(c).strip()]
    ue.add_codes("csi800", codes)
    typer.echo(f"  {len(codes)} constituents")


def _sync_batch_data(
    dm: Any,
    ue: Any,
    names: list[str],
    cfg: Any,
    bench_key: str,
    limit: int,
    seed_csi800: bool,
) -> None:
    """Sync the market data a batch run needs: stock list, each universe's codes,
    and the benchmark index. Codes are capped by ``limit`` for feasibility.
    """
    typer.echo("Syncing A-share stock list ...")
    n_stocks = dm.sync_stock_list()
    typer.echo(f"  {n_stocks} stocks")

    if seed_csi800 or not ue.exists("csi800"):
        _seed_csi800(ue)

    from research.strategy_library import get_strategy

    universes: set[str] = {get_strategy(n).spec.universe for n in names}
    codes_to_sync: set[str] = set()
    for u in sorted(universes):
        if u == "csi800":
            pool = list(ue.get_codes("csi800"))
        elif u == "all_a":
            df = dm.get_stock_list()
            pool = df["code"].astype(str).tolist() if "code" in df.columns else []
        else:  # custom
            pool = []
            for n in names:
                spec = get_strategy(n).spec
                if spec.universe == u:
                    pool.extend(spec.custom_codes or [])
        if limit and limit > 0:
            pool = pool[:limit]
        codes_to_sync.update(pool)

    typer.echo(f"Syncing {len(codes_to_sync)} codes (limit={limit or 'none'}) ...")
    synced = 0
    for code in sorted(codes_to_sync):
        try:
            synced += dm.sync_daily(code)
        except Exception as exc:  # noqa: BLE001 - one bad code must not abort the batch
            typer.echo(f"  skip {code}: {exc}", err=True)
    typer.echo(f"  {synced} bars stored")

    bench_code = cfg.benchmark.indices[bench_key]
    typer.echo(f"Syncing benchmark {bench_key} ({bench_code}) ...")
    try:
        dm.sync_index(bench_code)
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"  benchmark sync failed: {exc}", err=True)


@research_app.command("batch")
def research_batch(
    name: str | None = typer.Option(None, "--name", help="Batch experiment name"),
    start: str | None = typer.Option(None, "--start", help="Start date YYYY-MM-DD"),
    end: str | None = typer.Option(None, "--end", help="End date YYYY-MM-DD"),
    benchmark: str | None = typer.Option(
        None, "--benchmark", help="Benchmark key (default: configured)"
    ),
    strategies: str | None = typer.Option(
        None, "--strategies", help="Comma-separated strategy names (default: all)"
    ),
    limit: int = typer.Option(
        60, "--limit", help="Max codes per universe (feasibility cap; 0 = no cap)"
    ),
    walk_forward: tuple[int, int, int] | None = typer.Option(
        None, "--walk-forward", help="Walk-forward TRAIN TEST STEP (years)"
    ),
    no_sync: bool = typer.Option(
        False, "--no-sync", help="Skip data sync (use already-stored data)"
    ),
    seed_csi800: bool = typer.Option(
        False, "--seed-csi800", help="Force reseed the csi800 pool from AKShare"
    ),
    emit_report: bool = typer.Option(
        False, "--emit-report", help="Write a ranking report (md) to reports/"
    ),
    notes: str | None = typer.Option(None, "--notes", help="Run note"),
) -> None:
    """Batch-backtest strategies on REAL A-share data (Sprint 3.2 real-data path).

    Syncs the prerequisite market data (stock list, each strategy's universe
    codes, and the benchmark index) through DataManager, then runs BatchRunner
    across the selected strategies using the DataManager-backed price/benchmark
    providers. Use --no-sync to reuse already-stored data.
    """
    setup_logging()
    cfg = get_config()
    start = start or cfg.data.start_date
    end = end or cfg.data.end_date
    bench_key = benchmark or cfg.benchmark.default
    if name is None:
        # Include a wall-clock stamp so re-running the same day does not collide
        # with the UNIQUE experiment_runs.name constraint (each strategy run is
        # persisted as "{name}:{strategy}"). Pass --name for a stable label.
        name = f"realdata-{date.today().isoformat()}-{datetime.now().strftime('%H%M%S')}"

    from research.strategy_library import list_strategies

    names = (
        [s.strip() for s in strategies.split(",") if s.strip()]
        if strategies
        else [s.spec.name for s in list_strategies()]
    )
    known = {s.spec.name for s in list_strategies()}
    for n in names:
        if n not in known:
            typer.echo(f"unknown strategy: {n}", err=True)
            raise typer.Exit(code=2)

    exp_cfg = ExperimentConfig(
        name=name,
        strategy=names[0],
        start=start,
        end=end,
        benchmark=bench_key,
        walk_forward=(
            WalkForwardSpec(
                train_years=walk_forward[0],
                test_years=walk_forward[1],
                step_years=walk_forward[2],
            )
            if walk_forward
            else None
        ),
    )

    dm = DataManager()
    ue = UniverseEngine()

    if not no_sync:
        _sync_batch_data(dm, ue, names, cfg, bench_key, limit, seed_csi800)

    from research.batch import BatchRunner

    runner = BatchRunner(data_manager=dm, universe_engine=ue)
    result = runner.run(names, exp_cfg, notes=notes, regime_analysis=True)

    typer.echo(f"\nBatch {name} complete ({len(result.outcomes)} strategies)")
    typer.echo(f"{'strategy':<22}{'cat':<9}{'OOS ret':<12}{'OOS sharpe':<12}")
    for o in result.outcomes:
        ret = o.oos_metrics.get("total_return")
        sh = o.oos_metrics.get("sharpe")
        typer.echo(f"{o.name:<22}{o.category:<9}{_fmt_ratio_pct(ret):<12}{_fmt_ratio_pct(sh):<12}")

    if emit_report:
        from pathlib import Path

        from research.ranking import RankingReport
        from research.scorecard import Scorecard

        ranking = RankingReport.from_batch(result, scorecard=Scorecard())
        out = Path(cfg.paths.report_dir) / f"batch-{name}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(ranking.to_markdown(), encoding="utf-8")
        typer.echo(f"Report written to {out}")


@research_app.command("list")
def research_list() -> None:
    """List experiments, newest first."""
    setup_logging()
    runs = ExperimentRegistry().list()
    if not runs:
        typer.echo("No experiments yet.")
        return
    typer.echo("RUN_ID | NAME | STATUS | CREATED_AT")
    for r in runs:
        created = r.created_at.isoformat(sep=" ") if r.created_at else "-"
        typer.echo(f"{r.id} | {r.name} | {r.status} | {created}")


@research_app.command("show")
def research_show(run_id: str) -> None:
    """Show one experiment (config + lifecycle)."""
    setup_logging()
    run = ExperimentRegistry().get(run_id)
    if run is None:
        typer.echo(f"run {run_id} not found", err=True)
        raise typer.Exit(code=1)
    exp_cfg = ExperimentConfig.model_validate_json(run.config_json)
    created = run.created_at.isoformat(sep=" ") if run.created_at else "-"
    finished = run.finished_at.isoformat(sep=" ") if run.finished_at else "-"
    typer.echo(f"Run:      {run.id}")
    typer.echo(f"Name:     {run.name}")
    typer.echo(f"Status:   {run.status}")
    typer.echo(f"Created:  {created}")
    typer.echo(f"Finished: {finished}")
    typer.echo(f"Notes:    {run.notes or '-'}")
    typer.echo("Config:")
    typer.echo(exp_cfg.model_dump_json(indent=2))


@research_app.command("report")
def research_report(
    run_id: str,
    format: str = typer.Option("markdown", "--format", help="markdown | json | html"),
) -> None:
    """Render a shareable report for an experiment (metrics + benchmark + OOS)."""
    setup_logging()
    reg = ExperimentRegistry()
    run = reg.get(run_id)
    if run is None:
        typer.echo(f"run {run_id} not found", err=True)
        raise typer.Exit(code=1)
    result = reg.load_result(run_id)
    if result is None:
        typer.echo(f"run {run_id} has no results yet", err=True)
        raise typer.Exit(code=1)

    report = ResearchReport.from_run(run, result)
    fmt = (format or "markdown").lower()
    if fmt == "json":
        typer.echo(report.to_json())
    elif fmt == "html":
        typer.echo(report.to_html())
    else:
        typer.echo(report.to_markdown())


@research_app.command("delete")
def research_delete(run_id: str) -> None:
    """Delete an experiment (cascades to its metrics/equity)."""
    setup_logging()
    ok = ExperimentRegistry().delete(run_id)
    if not ok:
        typer.echo(f"run {run_id} not found", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"deleted {run_id}")


app.add_typer(research_app, name="research")


# --------------------------------------------------------------------------- #
# Phase 4.0 / 4.1 -- knowledge base + validation engine subcommands
# --------------------------------------------------------------------------- #
kb_app = typer.Typer(help="Phase 4.0 Strategy Knowledge Base (raw pool + registry)")


@kb_app.command("seed")
def kb_seed(
    force: bool = typer.Option(False, "--force", help="Rebuild existing entries"),
) -> None:
    """Seed the 10 built-in strategies into the formal library as active."""
    setup_logging()
    from research.kb import StrategyRegistry

    n = StrategyRegistry(_kb_session()).seed_builtins(overwrite=force)
    typer.echo(f"Seeded {n} built-in strategies into strategy_registry")


@kb_app.command("list")
def kb_list() -> None:
    """List the formal library entries."""
    setup_logging()
    from research.kb import StrategyRegistry

    rows = StrategyRegistry(_kb_session()).list_active()
    if not rows:
        typer.echo("(empty) run `python main.py research kb seed` first")
        return
    typer.echo(f"{'id':<18}{'cat':<9}{'star':<6}{'rel':<8}{'gate':<7}{'status':<10}")
    for r in rows:
        star = "-" if r.quality_star is None else r.quality_star
        rel = "-" if r.reliability_score is None else f"{r.reliability_score:.1f}"
        gate = "-" if r.gate_passed is None else ("PASS" if r.gate_passed else "FAIL")
        typer.echo(f"{r.strategy_id:<18}{r.category:<9}{star:<6}{rel:<8}{gate:<7}{r.status:<10}")


@kb_app.command("add-raw")
def kb_add_raw(
    name: str = typer.Argument(..., help="Strategy name"),
    source: str | None = typer.Option(None, "--source", help="Source description/link"),
    source_type: str = typer.Option("manual", "--type", help="manual/web/book/paper/other"),
    description: str | None = typer.Option(None, "--desc", help="Original description"),
    rules: str | None = typer.Option(None, "--rules", help="Extractable rules"),
) -> None:
    """Add a raw strategy idea to the pool (for later implementation + validation)."""
    setup_logging()
    from research.kb import RawPool

    sid = RawPool(_kb_session()).add(
        name, source_type=source_type, source=source, description=description, rules=rules
    )
    typer.echo(f"Added raw strategy {sid} ({name!r})")


@kb_app.command("retire")
def kb_retire(strategy_id: str = typer.Argument(..., help="Registry strategy id")) -> None:
    """Retire a formal-library entry (keeps the row for audit)."""
    setup_logging()
    from research.kb import StrategyRegistry

    ok = StrategyRegistry(_kb_session()).retire(strategy_id)
    typer.echo(f"retired {strategy_id}" if ok else f"{strategy_id} not found")


validate_app = typer.Typer(help="Phase 4.1 Strategy Validation Engine + Gate")


def _print_validation(res: Any) -> None:
    """Render a :class:`research.validate.ValidationResult` to the console."""
    typer.echo(f"Strategy : {res.strategy_id}")
    typer.echo(f"  composite      : {res.composite}")
    typer.echo(f"  quality_star   : {'*' * res.quality_star} ({res.quality_star})")
    typer.echo(f"  reliability    : {res.reliability_score}")
    gate_str = "PASS" if res.gate_passed else "FAIL"
    typer.echo(f"  gate           : {gate_str} -> {res.status_suggestion}")
    typer.echo(f"  avg param decay: {res.avg_decay}")
    typer.echo(f"  IS range       : {res.is_range}")
    typer.echo(f"  OOS range      : {res.oos_range}")
    detail = ", ".join(f"{k}={'Y' if v else 'N'}" for k, v in res.gate_detail.items())
    typer.echo("  gate detail    : " + detail)


@validate_app.command("run")
def validate_run(
    strategy: str = typer.Option(..., "--strategy", help="Strategy name (library id)"),
    start: str | None = typer.Option(None, "--start", help="Start date YYYY-MM-DD"),
    end: str | None = typer.Option(None, "--end", help="End date YYYY-MM-DD"),
    benchmark: str | None = typer.Option(None, "--benchmark", help="Benchmark key"),
) -> None:
    """Validate one strategy (walk-forward OOS + Gate) and persist evidence."""
    setup_logging()
    from data.manager import DataManager
    from research.batch import BatchRunner
    from research.validate import ValidationEngine
    from universe.engine import UniverseEngine

    cfg = get_config()
    runner = BatchRunner(data_manager=DataManager(), universe_engine=UniverseEngine())
    res = ValidationEngine(batch_runner=runner, config=cfg).run_strategy(
        strategy, _kb_session(), start=start, end=end, benchmark=benchmark
    )
    _print_validation(res)


@validate_app.command("all")
def validate_all(
    start: str | None = typer.Option(None, "--start", help="Start date YYYY-MM-DD"),
    end: str | None = typer.Option(None, "--end", help="End date YYYY-MM-DD"),
    benchmark: str | None = typer.Option(None, "--benchmark", help="Benchmark key"),
) -> None:
    """Validate every built-in strategy and persist the evidence chain."""
    setup_logging()
    from data.manager import DataManager
    from research.batch import BatchRunner
    from research.strategy_library import list_strategies
    from research.validate import ValidationEngine
    from universe.engine import UniverseEngine

    cfg = get_config()
    runner = BatchRunner(data_manager=DataManager(), universe_engine=UniverseEngine())
    engine = ValidationEngine(batch_runner=runner, config=cfg)
    names = [s.spec.name for s in list_strategies()]
    for name in names:
        res = engine.run_strategy(name, _kb_session(), start=start, end=end, benchmark=benchmark)
        _print_validation(res)
        typer.echo("")


alpha_app = typer.Typer(help="Phase 4.2 Multi-Strategy Consensus Engine")


def _print_consensus(results: list[Any]) -> None:
    """Render ConsensusEngine results to the console."""
    if not results:
        typer.echo("(no candidates) check strategy_registry seed + universe")
        return
    typer.echo(
        f"{'code':<10}{'hits':<6}{'cons':<7}{'aros':<7}{'rating':<7}{'regime':<10}"
        f"{'hit_strategies'}"
    )
    for r in results:
        typer.echo(
            f"{r.code:<10}{r.hit_count:<6}{r.consensus_score:<7}{r.aros_score:<7}"
            f"{r.rating:<7}{r.regime_label:<10}{','.join(r.hit_strategies)}"
        )


@alpha_app.command("daily")
def alpha_daily(
    universe: str | None = typer.Option(None, "--universe", help="csi800/watchlist/custom"),
    date: str | None = typer.Option(None, "--date", help="YYYY-MM-DD, default today"),
    limit: int | None = typer.Option(None, "--limit", help="cap universe codes scanned"),
    regime: str | None = typer.Option(None, "--regime", help="force regime label (skip infer)"),
    no_money_flow: bool = typer.Option(
        False, "--no-money-flow", help="skip 4.3 providers, use neutral (50) money-flow scores"
    ),
) -> None:
    """Daily multi-strategy consensus screening -> ranked Alpha candidates."""
    setup_logging()
    import pandas as pd

    from data.manager import DataManager
    from data.providers.moneyflow import (
        AkShareHiddenFlowProvider,
        AkShareMoneyFlowProvider,
    )
    from research.consensus import ConsensusEngine
    from research.kb import StrategyRegistry
    from universe.engine import UniverseEngine

    cfg = get_config()
    session = _kb_session()
    # Auto-seed the 10 built-ins so the engine has a working library.
    if not StrategyRegistry(session).list_by_status("active"):
        n = StrategyRegistry(session).seed_builtins()
        typer.echo(f"auto-seeded {n} built-in strategies as active")

    dm = DataManager()
    ue = UniverseEngine()

    def _bench(bench_key: str, start: str, end: str) -> pd.Series:
        code = cfg.benchmark.indices[bench_key]
        df = dm.get_index_daily(code, pd.Timestamp(start).date(), pd.Timestamp(end).date())
        return pd.Series(df["close"].to_numpy(dtype=float), index=pd.to_datetime(df["date"]))

    # Sprint 4.3 — wire real money-flow / hidden-flow providers. They degrade to
    # a neutral (50) signal on any network/akshare failure, so an offline run
    # still completes (and the constitution "暗盘永不淘汰候选" holds).
    money_flow_provider = None
    hidden_flow_provider = None
    if not no_money_flow:
        money_flow_provider = AkShareMoneyFlowProvider()
        hidden_flow_provider = AkShareHiddenFlowProvider()

    engine = ConsensusEngine(
        data_manager=dm,
        universe_engine=ue,
        config=cfg,
        benchmark_provider=_bench,
        money_flow_provider=money_flow_provider,
        hidden_flow_provider=hidden_flow_provider,
    )
    results = engine.daily(universe, date, session=session, limit=limit, regime=regime)
    _print_consensus(results)
    top = cfg.consensus.top_n
    typer.echo(
        f"\nPersisted {min(len(results), top)} candidates (Top-{top}) to daily_alpha_candidates."
    )

    # Sprint 4.4 — render the three-format daily Alpha report (Excel + HTML + MD),
    # archived under reports/<run_date>/. Mirrors engine.daily's run_date logic.
    from datetime import date as _date

    from report.daily_alpha import DailyAlphaReport, query_candidates

    run_date = pd.Timestamp(date).date() if date else _date.today()
    candidates = query_candidates(session, run_date)
    # Sprint 4.5 — fill Sheet2's human columns when the user has judged candidates.
    from research.feedback import query_decisions

    decisions = query_decisions(session, run_date)
    paths = DailyAlphaReport().generate(
        candidates, run_date, out_dir="reports", decision_by_candidate=decisions
    )
    typer.echo(f"Report -> xlsx: {paths['xlsx']}")
    typer.echo(f"         html: {paths['html']}")
    typer.echo(f"         md  : {paths['md']}")


@alpha_app.command("decide")
def alpha_decide(
    candidate_id: str = typer.Option(..., "--candidate", help="daily_alpha_candidates.id"),
    decision: str = typer.Option(..., "--decision", help="关注 / 买入 / 放弃 / 忽略"),
    reason: str | None = typer.Option(None, "--reason", help="人工理由"),
) -> None:
    """Record a human judgement on a daily Alpha candidate (4.5 human loop)."""
    setup_logging()
    from research.feedback import HUMAN_DECISIONS, record_decision

    if decision not in HUMAN_DECISIONS:
        typer.echo(f"ERROR: --decision must be one of {HUMAN_DECISIONS}", err=True)
        raise typer.Exit(code=1)
    session = _kb_session()
    try:
        dt = record_decision(session, candidate_id, decision, reason)
    except ValueError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Recorded decision '{dt.human_decision}' for {dt.code} (tracking {dt.id})")


@alpha_app.command("review")
def alpha_review(
    tracking_id: str = typer.Option(..., "--tracking", help="decision_tracking.id"),
    verified: bool | None = typer.Option(
        None, "--verified/--not-verified", help="系统是否被该候选验证"
    ),
    summary: str | None = typer.Option(None, "--summary", help="复盘总结"),
) -> None:
    """Fill auto post-hoc (1/3/5/10d + float pnl) and optional review fields."""
    setup_logging()
    import pandas as pd

    from data.manager import DataManager
    from research.feedback import review

    session = _kb_session()
    dm = DataManager()

    def _price(code: str, start: date, end: date) -> pd.DataFrame | None:
        return dm.get_daily(code, start, end)

    try:
        dt = review(
            session,
            tracking_id,
            _price,
            verified_system=verified,
            review_summary=summary,
        )
    except ValueError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    def _pct(v: float | None) -> str:
        return f"{v * 100:+.1f}%" if v is not None else "-"

    typer.echo(f"Review for {dt.code} (tracking {dt.id}):")
    typer.echo(
        f"  post-hoc: 1d {_pct(dt.result_1d)} · 3d {_pct(dt.result_3d)} · "
        f"5d {_pct(dt.result_5d)} · 10d {_pct(dt.result_10d)}"
    )
    typer.echo(
        f"  float: 最大盈利 {_pct(dt.max_float_profit)} · 最大亏损 {_pct(dt.max_float_loss)} · "
        f"最终 {_pct(dt.final_return)}"
    )
    if dt.verified_system is not None:
        typer.echo(f"  验证系统: {'是' if dt.verified_system else '否'}")
    if dt.review_summary:
        typer.echo(f"  复盘: {dt.review_summary}")


@alpha_app.command("trades-add")
def alpha_trades_add(
    code: str = typer.Option(..., "--code", help="标的代码"),
    name: str | None = typer.Option(None, "--name", help="标的名称"),
    entry_date: str | None = typer.Option(None, "--entry-date", help="YYYY-MM-DD"),
    entry_price: float | None = typer.Option(None, "--entry-price", help="买入价"),
    exit_date: str | None = typer.Option(None, "--exit-date", help="YYYY-MM-DD"),
    exit_price: float | None = typer.Option(None, "--exit-price", help="卖出价"),
    quantity: float | None = typer.Option(None, "--quantity", help="数量"),
    direction: str | None = typer.Option(None, "--direction", help="long / short"),
    pnl: float | None = typer.Option(None, "--pnl", help="盈亏额"),
    pnl_pct: float | None = typer.Option(None, "--pnl-pct", help="盈亏比例"),
    note: str | None = typer.Option(None, "--note", help="备注"),
    source: str = typer.Option("人工录入", "--source", help="人工录入 / 导入"),
) -> None:
    """Manually record a personal trade (design §3.6 — system never derives)."""
    setup_logging()
    from datetime import date as _date

    from research.feedback import record_trade

    session = _kb_session()
    ed = _date.fromisoformat(entry_date) if entry_date else None
    xd = _date.fromisoformat(exit_date) if exit_date else None
    trade = record_trade(
        session,
        code,
        name=name,
        entry_date=ed,
        entry_price=entry_price,
        exit_date=xd,
        exit_price=exit_price,
        quantity=quantity,
        direction=direction,
        pnl=pnl,
        pnl_pct=pnl_pct,
        note=note,
        source=source,
    )
    typer.echo(f"Recorded personal trade {trade.id} for {trade.code}")


@alpha_app.command("trades-list")
def alpha_trades_list(
    code: str | None = typer.Option(None, "--code", help="按代码过滤"),
) -> None:
    """List recorded personal trades (most recent first)."""
    setup_logging()
    from research.feedback import list_trades

    session = _kb_session()
    trades = list_trades(session, code=code)
    if not trades:
        typer.echo("(no personal trades recorded)")
        return
    typer.echo(f"{'id':<12}{'code':<10}{'entry':<12}{'price':<10}{'exit':<12}{'pnl%':<9}")
    for t in trades:
        ep = f"{t.entry_price:.2f}" if t.entry_price is not None else "-"
        pp = f"{t.pnl_pct * 100:+.1f}%" if t.pnl_pct is not None else "-"
        ed = t.entry_date.isoformat() if t.entry_date else "-"
        xd = t.exit_date.isoformat() if t.exit_date else "-"
        typer.echo(f"{t.id:<12}{t.code:<10}{ed:<12}{ep:<10}{xd:<12}{pp:<9}")


# --------------------------------------------------------------------------- #
# Phase 4.6 -- Rating validation & calibration (sub-group of `alpha`)
# --------------------------------------------------------------------------- #
alpha_validate_app = typer.Typer(help="Phase 4.6 Rating Validation & Calibration")


def _bench_price_provider(dm: Any) -> Any:
    """Build a benchmark PriceProvider returning the index's date+close frame."""

    def _p(code: str, start: date, end: date) -> Any:
        return dm.get_index_daily(code, start, end)

    return _p


@alpha_validate_app.command("migrate")
def alpha_validate_migrate() -> None:
    """Migrate the historical top rating label 'A+' -> 'S' (idempotent)."""
    setup_logging()
    from research.calibration import migrate_rating_labels

    session = _kb_session()
    n_cand, n_perf = migrate_rating_labels(session)
    typer.echo(f"Migrated rating A+ -> S: {n_cand} candidates, {n_perf} performances")


@alpha_validate_app.command("fill")
def alpha_validate_fill(
    as_of: str | None = typer.Option(None, "--as-of", help="YYYY-MM-DD, default today"),
    target: float = typer.Option(0.05, "--target", help="目标达成收益率 (e.g. 0.05)"),
) -> None:
    """Auto-fill CandidatePerformance for every candidate (incremental)."""
    setup_logging()
    import pandas as pd

    from data.manager import DataManager
    from research.calibration import fill_all_performances, migrate_rating_labels

    session = _kb_session()
    migrate_rating_labels(session)  # idempotent; ensures 'S' labels before fill
    dm = DataManager()

    def _price(code: str, start: date, end: date) -> pd.DataFrame | None:
        return dm.get_daily(code, start, end)

    run_date = pd.Timestamp(as_of).date() if as_of else date.today()
    n = fill_all_performances(session, _price, as_of=run_date, target_pct=target)
    typer.echo(f"Filled/updated {n} candidate performance rows (as of {run_date})")


@alpha_validate_app.command("report")
def alpha_validate_report(
    as_of: str | None = typer.Option(None, "--as-of", help="YYYY-MM-DD, default today"),
    no_benchmark: bool = typer.Option(False, "--no-benchmark", help="跳过基线超额对比"),
) -> None:
    """Generate the 4.6 validation reports (Calibration / Strategy / Human / Paper)."""
    setup_logging()
    import pandas as pd

    from data.manager import DataManager
    from research.calibration import generate_validation_reports

    session = _kb_session()
    run_date = pd.Timestamp(as_of).date() if as_of else date.today()
    bench_provider = None
    bench_code = None
    if not no_benchmark:
        try:
            cfg = get_config()
            dm = DataManager()
            if cfg.benchmark.indices:
                bench_code = next(iter(cfg.benchmark.indices.values()))
                bench_provider = _bench_price_provider(dm)
        except Exception as exc:  # noqa: BLE001 - degrade gracefully if no benchmark
            typer.echo(f"(benchmark unavailable: {exc}; skipping baseline)", err=True)
    paths = generate_validation_reports(
        session,
        out_dir="reports",
        as_of=run_date,
        bench_price_provider=bench_provider,
        bench_code=bench_code,
    )
    typer.echo(f"Report -> md : {paths['md']}")
    typer.echo(f"         html: {paths['html']}")
    typer.echo(f"         xlsx: {paths['xlsx']}")


@alpha_validate_app.command("calibrate")
def alpha_validate_calibrate(
    as_of: str | None = typer.Option(None, "--as-of", help="YYYY-MM-DD, default today"),
) -> None:
    """Print rating distribution + significance + a two-stage calibration proposal."""
    setup_logging()
    import pandas as pd

    from research.calibration import build_validation_payload

    session = _kb_session()
    run_date = pd.Timestamp(as_of).date() if as_of else date.today()
    p = build_validation_payload(session, as_of=run_date)
    cov = p["coverage"]
    cov_str = f"{cov:.1%}" if isinstance(cov, float) and not math.isnan(cov) else "n/a"
    typer.echo(
        f"As of {p['as_of']}: candidates={p['n_candidates']} "
        f"performances={p['n_performances']} coverage={cov_str}"
    )
    typer.echo(f"Monotone S>A>B>C: {'YES' if p['monotone'] else 'NO'}")
    for pair, s in p["significance"].items():
        if s["mean_diff"] is None:
            typer.echo(f"  {pair}: sample {s['sample']} (insufficient)")
        else:
            flag = "SIGNIFICANT" if s["significant"] else "not significant"
            typer.echo(f"  {pair}: mean_diff={s['mean_diff']:+.2%} p={s['mwu_p']:.4f} {flag}")
    cal = p["calibration"]
    typer.echo(
        f"Calibration: {cal['trading_days']} trading days -> "
        f"{'CAN calibrate' if cal['can_calibrate'] else 'OBSERVE ONLY'} ({cal['note']})"
    )
    if cal["proposed"] is not None:
        pr = cal["proposed"]
        typer.echo(
            f"  proposed thresholds: S>={pr['rating_s']:.1f} A>={pr['rating_a']:.1f} "
            f"B>={pr['rating_b']:.1f}"
        )


alpha_papertrade_app = typer.Typer(help="Phase 4.7 Paper Trading (Exit Experiment)")


@alpha_papertrade_app.command("init")
def alpha_papertrade_init(
    portfolio_id: str = typer.Option(..., "--id", help="组合ID, e.g. S1_E1"),
    axis: str = typer.Option(..., "--axis", help="selection | exit"),
    name: str | None = typer.Option(None, "--name", help="展示名"),
    picker: str = typer.Option("ai", "--picker", help="ai | human | random"),
    preset: str = typer.Option("E1", "--preset", help="退出预设 E1/E2/E3"),
    exit_config: str | None = typer.Option(
        None, "--exit-config", help="自定义 ExitConfig YAML/JSON 路径(覆盖 preset)"
    ),
    capital: float = typer.Option(100000.0, "--capital", help="初始资金"),
    max_positions: int = typer.Option(5, "--max-positions", help="最大持仓数"),
    position_fraction: float = typer.Option(0.2, "--position-fraction", help="单仓仓位比例"),
    entry_mode: str = typer.Option(
        "immediate", "--entry-mode", help="immediate|signal_confirmation|manual"
    ),
    max_holding: int | None = typer.Option(None, "--max-holding", help="组合级持有上限(交易日)"),
) -> None:
    """Create one paper-trading portfolio (one cell of the experiment)."""
    setup_logging()
    from research.papertrade import ExitConfig, exit_preset, init_portfolio

    cfg = exit_preset(preset)
    if exit_config is not None:
        with open(exit_config, encoding="utf-8") as fh:
            raw = fh.read()
        cfg = (
            ExitConfig.from_json(raw)
            if raw.lstrip().startswith("{")
            else ExitConfig.from_json(__import__("json").dumps(__import__("yaml").safe_load(raw)))
        )
    session = _kb_session()
    p = init_portfolio(
        session,
        portfolio_id=portfolio_id,
        axis=axis,
        name=name,
        picker=picker,
        exit_config=cfg,
        initial_capital=capital,
        max_positions=max_positions,
        position_fraction=position_fraction,
        entry_mode=entry_mode,
        max_holding_days=max_holding,
    )
    typer.echo(f"Created portfolio {p.id} (axis={p.axis}, picker={p.picker}, preset={preset})")


@alpha_papertrade_app.command("run")
def alpha_papertrade_run(
    run_date: str = typer.Option(..., "--date", help="YYYY-MM-DD 交易日"),
) -> None:
    """Simulate one trading day for all portfolios (entries T+1 then exits)."""
    setup_logging()
    import pandas as pd

    from data.manager import DataManager
    from research.papertrade import simulate_day

    session = _kb_session()
    dm = DataManager()

    def _price(code: str, start: date, end: date) -> pd.DataFrame | None:
        return dm.get_daily(code, start, end)

    d = pd.Timestamp(run_date).date()
    summary = simulate_day(session, d, _price)
    typer.echo(f"{summary['date']}: entries={summary['entries']} exits={summary['exits']}")


@alpha_papertrade_app.command("report")
def alpha_papertrade_report(
    as_of: str | None = typer.Option(None, "--as-of", help="YYYY-MM-DD, default today"),
    portfolio_id: str | None = typer.Option(None, "--id", help="仅某组合"),
    no_benchmark: bool = typer.Option(False, "--no-benchmark", help="跳过基准对比"),
) -> None:
    """Generate the Portfolio Performance Report (md + html + xlsx)."""
    setup_logging()
    import pandas as pd

    from data.manager import DataManager
    from research.papertrade import generate_papertrade_report

    session = _kb_session()
    run_date = pd.Timestamp(as_of).date() if as_of else date.today()

    def _price(code: str, start: date, end: date) -> pd.DataFrame | None:
        return DataManager().get_daily(code, start, end)

    bench_provider = None
    bench_code = None
    if not no_benchmark:
        try:
            cfg = get_config()
            dm = DataManager()
            if cfg.benchmark.indices:
                bench_code = next(iter(cfg.benchmark.indices.values()))
                bench_provider = _bench_price_provider(dm)
        except Exception as exc:  # noqa: BLE001 - degrade gracefully if no benchmark
            typer.echo(f"(benchmark unavailable: {exc}; skipping baseline)", err=True)
    ids = [portfolio_id] if portfolio_id else None
    paths = generate_papertrade_report(
        session,
        out_dir="reports",
        as_of=run_date,
        price_provider=_price,
        bench_price_provider=bench_provider,
        bench_code=bench_code,
        portfolio_ids=ids,
    )
    typer.echo(f"Report -> md : {paths['md']}")
    typer.echo(f"         html: {paths['html']}")
    typer.echo(f"         xlsx: {paths['xlsx']}")


alpha_app.add_typer(alpha_papertrade_app, name="papertrade")
alpha_app.add_typer(alpha_validate_app, name="validate")


# --------------------------------------------------------------------------- #
# Phase 4.7 -- Entry Intelligence (Alpha Entry Engine)
# --------------------------------------------------------------------------- #
alpha_entry_app = typer.Typer(help="Phase 4.7 Entry Intelligence (买点评估)")


@alpha_entry_app.command("eval")
def alpha_entry_eval(
    code: str = typer.Option(..., "--code", help="股票代码"),
    as_of: str | None = typer.Option(None, "--date", help="YYYY-MM-DD, default today"),
    signal_date: str | None = typer.Option(
        None, "--signal-date", help="候选信号日(取 AROS/评级); 默认取该代码最近一条"
    ),
) -> None:
    """评估某标的当前买点：Entry Score + 动作(strong_buy/buy/wait/avoid)。

    综合策略组合(命中类别) + 标的当期价格行为/量/位置 + 市场判断(regime)，
    与 AROS Score 解耦地给出"现在是否适合买"。
    """
    setup_logging()
    import pandas as pd

    from research.entry import EntryEngine, MarketState, resolve_categories
    from research.models import DailyAlphaCandidate, DailyScreening

    session = _kb_session()
    d = pd.Timestamp(as_of).date() if as_of else date.today()

    q = session.query(DailyAlphaCandidate).filter_by(code=code)
    if signal_date:
        q = q.join(DailyScreening, DailyAlphaCandidate.screening_id == DailyScreening.id).filter(
            DailyScreening.run_date == pd.Timestamp(signal_date).date()
        )
    cand = q.order_by(DailyAlphaCandidate.id.desc()).first()
    aros = cand.aros_score if cand else 50.0
    rating = cand.rating if cand else "C"
    hit = json.loads(cand.hit_strategies_json) if cand and cand.hit_strategies_json else []
    cats = resolve_categories(session, hit) if cand else []
    regime = cand.regime_label if cand else "Neutral"
    mkt = MarketState(regime=regime)

    dm = DataManager()

    def _price(c: str, s: date, e: date) -> Any:
        return dm.get_daily(c, s, e)

    sig = EntryEngine().evaluate(
        code, d, _price, aros_score=aros, rating=rating, categories=cats, market=mkt
    )
    typer.echo(
        f"{code} @ {d}  Entry Score={sig.entry_score:.1f}  "
        f"动作={sig.action}  置信={sig.confidence:.2f}"
    )
    typer.echo(f"  AROS={sig.aros_score:.1f} 评级={sig.rating} 主导模型={sig.dominant_family}")
    typer.echo(f"  组件={sig.components}")
    typer.echo(f"  理由: {sig.reason}")


# --------------------------------------------------------------------------- #
# Phase 4.8 -- Exit Intelligence (Alpha Exit Engine)
# --------------------------------------------------------------------------- #
alpha_exit_app = typer.Typer(help="Phase 4.8 Exit Intelligence (卖点评估)")


def _consensus_score_provider(session: Any) -> Any:
    """ScoreProvider wired to the system's real daily screening output.

    Returns the latest ``DailyAlphaCandidate`` AROS Score (+ money-flow) for the
    code on/before ``as_of`` — the honest "real AROS Score" source for the 4.8
    Daily Exit Intelligence. Returns ``None`` when no candidate exists (so the
    engine never fabricates a decay signal).
    """
    from research.exit import ExitScoreInput
    from research.models import DailyAlphaCandidate, DailyScreening

    def _p(code: str, as_of: date) -> ExitScoreInput | None:
        c = (
            session.query(DailyAlphaCandidate)
            .filter_by(code=code)
            .join(DailyScreening, DailyAlphaCandidate.screening_id == DailyScreening.id)
            .filter(DailyScreening.run_date <= as_of)
            .order_by(DailyScreening.run_date.desc())
            .first()
        )
        if c is None:
            return None
        return ExitScoreInput(
            aros_score=c.aros_score,
            entry_aros_score=c.aros_score,
            public_money_score=c.public_money_score,
            hidden_flow_score=c.hidden_flow_score,
            sector_score=c.sector_score,
        )

    return _p


@alpha_exit_app.command("eval")
def alpha_exit_eval(
    trade_id: str = typer.Option(..., "--trade-id", help="持仓模拟交易ID"),
    as_of: str | None = typer.Option(None, "--date", help="YYYY-MM-DD, default today"),
) -> None:
    """评估某持仓当前是否应离场：分级 Exit Signal(High/Medium/Low) + 可解释原因。

    真实 AROS Score 经 ScoreProvider(系统每日筛选产出) 驱动逻辑衰减；同时检查
    资金转弱 / 趋势破坏 / 硬止损。
    """
    setup_logging()
    import pandas as pd

    from research.exit import ExitEngine
    from research.models import SimulatedTrade

    session = _kb_session()
    d = pd.Timestamp(as_of).date() if as_of else date.today()
    t = session.get(SimulatedTrade, trade_id)
    if t is None:
        typer.echo(f"trade {trade_id} not found", err=True)
        raise typer.Exit(1)
    if t.exit_date is not None:
        typer.echo(f"trade {trade_id} already closed on {t.exit_date}", err=True)
        raise typer.Exit(1)

    dm = DataManager()

    def _price(c: str, s: date, e: date) -> Any:
        return dm.get_daily(c, s, e)

    provider = _consensus_score_provider(session)
    sig = ExitEngine().evaluate(
        t.code,
        d,
        t.entry_price,
        _price,
        provider,
        entry_date=t.entry_date,
        entry_aros_score=t.aros_score,
        rating=t.rating,
    )
    typer.echo(f"{t.code} @ {d}  退出等级={sig.level}  建议离场={sig.should_exit}")
    typer.echo(f"  AROS={sig.aros_score} 衰减={sig.score_drop}")
    if sig.reasons:
        for r in sig.reasons:
            typer.echo(f"  - {r}")
    else:
        typer.echo("  - 无显著离场信号")


alpha_app.add_typer(alpha_entry_app, name="entry")
alpha_app.add_typer(alpha_exit_app, name="exit")


research_app.add_typer(kb_app, name="kb")
research_app.add_typer(validate_app, name="validate")
research_app.add_typer(alpha_app, name="alpha")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
