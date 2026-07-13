"""AROS command-line entry point (Typer).

Run with ``python main.py --help``. The ``core`` package lives under ``src/``
and is made importable via the editable install (``pip install -e .``) or the
pytest ``pythonpath`` setting.
"""

from __future__ import annotations

import typer

from core.config import get_config
from core.logging import setup_logging

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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
