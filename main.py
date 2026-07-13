"""AROS command-line entry point (Typer).

Run with ``python main.py --help``. The ``core`` package lives under ``src/``
and is made importable via the editable install (``pip install -e .``) or the
pytest ``pythonpath`` setting.
"""

from __future__ import annotations

from datetime import date

import typer

from core.config import get_config
from core.logging import setup_logging
from data.manager import DataManager

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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
