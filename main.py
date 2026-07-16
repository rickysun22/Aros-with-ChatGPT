"""AROS command-line entry point (Typer).

Run with python main.py --help. The core package lives under src/ and is made
importable via the editable install or the pytest pythonpath setting.
"""

from __future__ import annotations

import json
from datetime import date
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
from scheduler import Scheduler, build_notifier
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

    result = ResearchRunner().run(exp_cfg, notes=notes)
    m = result.metrics.get("full", {})
    typer.echo(f"Run {result.run_id} complete (name={exp_cfg.name!r})")
    typer.echo(f"  total_return      : {m.get('total_return')}")
    typer.echo(f"  sharpe            : {m.get('sharpe')}")
    typer.echo(f"  bench_excess_return: {m.get('bench_excess_return')}")
    typer.echo(f"  bench_beta        : {m.get('bench_beta')}")


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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
