"""Command-line interface."""

import sys
from pathlib import Path

import typer
from sqlalchemy import select
from sqlalchemy.orm import Session

from nobel_books import __version__
from nobel_books.adapters.nobel import NobelApiAdapter
from nobel_books.cache import RawResponseCache
from nobel_books.config import get_settings
from nobel_books.db import database_status, make_engine, upgrade_database
from nobel_books.errors import NobelBooksError
from nobel_books.logging import configure_logging
from nobel_books.models.database import Laureate
from nobel_books.pipeline.laureates import sync_laureates

app = typer.Typer(help="Build a provenance-rich bibliography of Nobel laureate books.")
db_app = typer.Typer(help="Manage the bibliography database.")
laureates_app = typer.Typer(help="Import and inspect Nobel laureates.")
app.add_typer(db_app, name="db")
app.add_typer(laureates_app, name="laureates")


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

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


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


@laureates_app.command("sync")
def laureates_sync() -> None:
    """Import all individual laureates in the three target categories."""

    settings = get_settings()
    source = settings.sources.get("nobel")
    if source is None or not source.enabled or source.base_url is None:
        typer.echo("Error: Nobel source is not enabled and configured.", err=True)
        raise typer.Exit(code=1)
    configure_logging(settings.log_level)
    adapter = NobelApiAdapter(source.base_url, page_size=source.page_size)
    engine = make_engine(settings.project.database_url)
    try:
        with Session(engine) as session:
            summary = sync_laureates(session, adapter, RawResponseCache())
    finally:
        engine.dispose()
    typer.echo(f"Imported {summary.laureates} laureates from {summary.pages} page(s).")
    typer.echo(f"Skipped {summary.organizations_skipped} organization(s).")
    for category, count in sorted(summary.awards_by_category.items()):
        typer.echo(f"{category}: {count}")
    years = ", ".join(f"{year}={count}" for year, count in sorted(summary.awards_by_year.items()))
    typer.echo(f"Awards by year: {years}")


@laureates_app.command("list")
def laureates_list() -> None:
    """List imported laureates."""

    settings = get_settings()
    engine = make_engine(settings.project.database_url)
    try:
        with Session(engine) as session:
            laureates = session.scalars(select(Laureate).order_by(Laureate.display_name)).all()
            for laureate in laureates:
                typer.echo(f"{laureate.nobel_api_id}\t{laureate.display_name}")
    finally:
        engine.dispose()
