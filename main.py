"""AROS command-line entry point (Typer).

Run with ``python main.py --help``. The ``core`` package lives under ``src/``
and is made importable via the editable install (``pip install -e .``) or the
pytest ``pythonpath`` setting.
"""

from __future__ import annotations

from datetime import date

import typer

from core.config import FactorConfig, IndicatorConfig, get_config
from core.logging import setup_logging
from data.manager import DataManager
from factors.engine import FactorEngine
from indicators.engine import IndicatorEngine

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
    code: str = typer.Option(None, "--code", help="Sync one stock's daily bars by code"),
    list_stocks: bool = typer.Option(False, "--list", help="Sync the full A-share stock list"),
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
    """Compute indicators then factors for a stock (read-only)."""
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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
