"""Command-line interface."""

import sys
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy import select
from sqlalchemy.orm import Session

from nobel_books import __version__
from nobel_books.adapters.nobel import NobelApiAdapter
from nobel_books.adapters.openlibrary import OpenLibraryAdapter
from nobel_books.adapters.wikidata import WikidataBookAdapter, WikidataIdentityAdapter
from nobel_books.cache import RawResponseCache
from nobel_books.config import get_settings
from nobel_books.db import database_status, make_engine, upgrade_database
from nobel_books.errors import NobelBooksError
from nobel_books.logging import configure_logging
from nobel_books.models.database import Laureate
from nobel_books.pipeline.discovery import discover_wikidata_candidates
from nobel_books.pipeline.identities import export_identity_review, resolve_identities
from nobel_books.pipeline.laureates import sync_laureates
from nobel_books.pipeline.openlibrary import (
    discover_openlibrary,
    export_openlibrary_identity_review,
)

app = typer.Typer(help="Build a provenance-rich bibliography of Nobel laureate books.")
db_app = typer.Typer(help="Manage the bibliography database.")
laureates_app = typer.Typer(help="Import and inspect Nobel laureates.")
identities_app = typer.Typer(help="Resolve and review external person identities.")
app.add_typer(db_app, name="db")
app.add_typer(laureates_app, name="laureates")
app.add_typer(identities_app, name="identities")


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


@identities_app.command("resolve")
def identities_resolve() -> None:
    """Resolve imported laureates through exact Wikidata Nobel IDs."""

    settings = get_settings()
    source = settings.sources.get("wikidata")
    if source is None or not source.enabled or source.base_url is None:
        typer.echo("Error: Wikidata source is not enabled and configured.", err=True)
        raise typer.Exit(code=1)
    adapter = WikidataIdentityAdapter(
        source.base_url,
        settings.project.user_agent,
        batch_size=source.page_size,
    )
    engine = make_engine(settings.project.database_url)
    try:
        with Session(engine) as session:
            summary = resolve_identities(session, adapter, RawResponseCache())
    finally:
        engine.dispose()
    typer.echo(
        f"Resolved identities: verified={summary.verified}, "
        f"unresolved={summary.unresolved}, ambiguous={summary.ambiguous}, "
        f"batches={summary.batches}"
    )


@identities_app.command("review-export")
def identities_review_export(
    output: Annotated[Path, typer.Option("--output", help="Review CSV path.")] = Path(
        "data/exports/identity_review.csv"
    ),
) -> None:
    """Export unresolved and ambiguous identity matches."""

    settings = get_settings()
    engine = make_engine(settings.project.database_url)
    try:
        with Session(engine) as session:
            count = export_identity_review(session, output)
    finally:
        engine.dispose()
    typer.echo(f"Exported {count} identity review row(s) to {output}.")


@app.command("discover")
def discover(
    source_name: Annotated[
        str, typer.Option("--source", help="Configured candidate source.")
    ] = "wikidata",
    laureate_id: Annotated[
        str | None,
        typer.Option("--laureate-id", help="Limit discovery to one Nobel API ID."),
    ] = None,
) -> None:
    """Discover source-native book candidates without canonical merging."""

    if source_name not in {"wikidata", "openlibrary"}:
        typer.echo(f"Error: source is not implemented: {source_name}", err=True)
        raise typer.Exit(code=1)
    settings = get_settings()
    source = settings.sources.get(source_name)
    if source is None or not source.enabled or source.base_url is None:
        typer.echo(f"Error: {source_name} source is not enabled and configured.", err=True)
        raise typer.Exit(code=1)
    engine = make_engine(settings.project.database_url)
    try:
        with Session(engine) as session:
            if source_name == "wikidata":
                wikidata_adapter = WikidataBookAdapter(
                    source.base_url,
                    settings.project.user_agent,
                    batch_size=source.page_size,
                )
                summary = discover_wikidata_candidates(
                    session, wikidata_adapter, RawResponseCache()
                )
                message = (
                    f"Discovered {summary.records} Wikidata candidate(s): "
                    f"works={summary.works}, editions={summary.editions}, "
                    f"assertions={summary.assertions}, batches={summary.batches}"
                )
            else:
                if not settings.project.contact_email:
                    typer.echo(
                        "Error: project.contact_email is required for Open Library.",
                        err=True,
                    )
                    raise typer.Exit(code=1)
                user_agent = f"{settings.project.user_agent} {settings.project.contact_email}"
                openlibrary_adapter = OpenLibraryAdapter(
                    source.base_url,
                    user_agent,
                    requests_per_second=source.requests_per_second,
                    page_size=source.page_size,
                )
                openlibrary_summary = discover_openlibrary(
                    session,
                    openlibrary_adapter,
                    RawResponseCache(),
                    max_authors=source.max_authors_per_run,
                    nobel_api_id=laureate_id,
                )
                review_path = Path("data/exports/openlibrary_identity_review.csv")
                review_count = export_openlibrary_identity_review(session, review_path)
                message = (
                    f"Open Library: verified_authors={openlibrary_summary.authors_verified}, "
                    f"review_candidates={review_count}, works={openlibrary_summary.works}, "
                    f"editions={openlibrary_summary.editions}, "
                    f"fetches={openlibrary_summary.fetches}"
                )
    finally:
        engine.dispose()
    typer.echo(message)
