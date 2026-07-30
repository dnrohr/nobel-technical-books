"""Command-line interface."""

from pathlib import Path

import typer

from nobel_books import __version__
from nobel_books.config import get_settings
from nobel_books.db import database_status, upgrade_database
from nobel_books.errors import NobelBooksError
from nobel_books.logging import configure_logging

app = typer.Typer(help="Build a provenance-rich bibliography of Nobel laureate books.")
db_app = typer.Typer(help="Manage the bibliography database.")
app.add_typer(db_app, name="db")


def version_callback(value: bool) -> None:
    if value:
        typer.echo(f"nobel-books {__version__}")
        raise typer.Exit


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", callback=version_callback, is_eager=True, help="Show version."
    ),
) -> None:
    """Build a provenance-rich bibliography of Nobel laureate books."""


@app.command()
def init() -> None:
    """Create local data directories and show the next setup command."""

    for path in (Path("data/cache"), Path("data/exports"), Path("data/manual")):
        path.mkdir(parents=True, exist_ok=True)
    typer.echo("Project directories initialized. Run `nobel-books db upgrade` next.")


@db_app.command("upgrade")
def db_upgrade(revision: str = typer.Argument("head")) -> None:
    """Upgrade the database schema."""

    settings = get_settings()
    configure_logging(settings.log_level)
    try:
        upgrade_database(settings.project.database_url, revision)
    except NobelBooksError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Database upgraded to {revision}.")


@app.command()
def status() -> None:
    """Show configuration and database readiness."""

    settings = get_settings()
    migrated, tables = database_status(settings.project.database_url)
    typer.echo(f"Version: {__version__}")
    typer.echo(f"Database: {settings.project.database_url}")
    typer.echo(f"Schema migrated: {'yes' if migrated else 'no'}")
    typer.echo(f"Tables: {', '.join(tables) if tables else '(none)'}")
    typer.echo(f"Enabled sources: {', '.join(k for k, v in settings.sources.items() if v.enabled)}")
