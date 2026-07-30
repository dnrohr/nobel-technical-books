"""Command-line interface."""

import os
import sys
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy import select
from sqlalchemy.orm import Session

from nobel_books import __version__
from nobel_books.adapters.crossref import CrossrefAdapter
from nobel_books.adapters.google_books import GoogleBooksAdapter
from nobel_books.adapters.nobel import NobelApiAdapter
from nobel_books.adapters.openalex import OpenAlexAdapter
from nobel_books.adapters.openlibrary import OpenLibraryAdapter
from nobel_books.adapters.wikidata import WikidataBookAdapter, WikidataIdentityAdapter
from nobel_books.adapters.wikipedia import WikipediaAdapter
from nobel_books.audit.report import write_audit_report
from nobel_books.cache import RawResponseCache
from nobel_books.classification.classifier import (
    classify_works,
    load_rules,
    score_relationships,
)
from nobel_books.config import get_settings
from nobel_books.db import database_status, make_engine, upgrade_database
from nobel_books.errors import NobelBooksError
from nobel_books.export.exporters import (
    export_all,
    export_editions_csv,
    export_evidence_csv,
    export_json,
    export_markdown,
    export_works_csv,
)
from nobel_books.logging import configure_logging
from nobel_books.models.database import Laureate
from nobel_books.pipeline.discovery import discover_wikidata_candidates
from nobel_books.pipeline.google_books import discover_google_books
from nobel_books.pipeline.identities import export_identity_review, resolve_identities
from nobel_books.pipeline.laureates import sync_laureates
from nobel_books.pipeline.openlibrary import (
    discover_openlibrary,
    export_openlibrary_identity_review,
)
from nobel_books.pipeline.scholarly import (
    discover_openalex,
    enrich_crossref,
    write_source_limitations,
)
from nobel_books.pipeline.wikipedia import discover_wikipedia
from nobel_books.reconciliation.editions import reconcile_editions
from nobel_books.reconciliation.works import cluster_works
from nobel_books.review.workflow import (
    export_review_queue,
    import_review_decisions,
)

app = typer.Typer(help="Build a provenance-rich bibliography of Nobel laureate books.")
db_app = typer.Typer(help="Manage the bibliography database.")
laureates_app = typer.Typer(help="Import and inspect Nobel laureates.")
identities_app = typer.Typer(help="Resolve and review external person identities.")
reconcile_app = typer.Typer(help="Reconcile normalized source records.")
review_app = typer.Typer(help="Export and import durable review decisions.")
export_app = typer.Typer(help="Export bibliography artifacts.")
audit_app = typer.Typer(help="Audit coverage, regressions, and dataset drift.")
app.add_typer(db_app, name="db")
app.add_typer(laureates_app, name="laureates")
app.add_typer(identities_app, name="identities")
app.add_typer(reconcile_app, name="reconcile")
app.add_typer(review_app, name="review")
app.add_typer(export_app, name="export")
app.add_typer(audit_app, name="audit")


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

    if source_name not in {
        "wikidata",
        "openlibrary",
        "google-books",
        "openalex",
        "crossref",
        "wikipedia",
    }:
        typer.echo(f"Error: source is not implemented: {source_name}", err=True)
        raise typer.Exit(code=1)
    settings = get_settings()
    config_key = source_name.replace("-", "_")
    source = settings.sources.get(config_key)
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
            elif source_name == "openlibrary":
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
            elif source_name == "google-books":
                api_key = (
                    os.environ.get(source.api_key_env) if source.api_key_env is not None else None
                )
                google_adapter = GoogleBooksAdapter(
                    source.base_url,
                    settings.project.user_agent,
                    api_key=api_key,
                    requests_per_second=source.requests_per_second,
                    page_size=source.page_size,
                    max_results_per_query=source.max_results_per_query,
                )
                google_summary = discover_google_books(
                    session,
                    google_adapter,
                    RawResponseCache(),
                    max_authors=source.max_authors_per_run,
                    nobel_api_id=laureate_id,
                )
                message = (
                    f"Google Books: queries={google_summary.queries}, "
                    f"volumes={google_summary.volumes}, "
                    f"new_volumes={google_summary.new_volumes}, "
                    f"ambiguous={google_summary.ambiguous_relationships}, "
                    f"fetches={google_summary.fetches}"
                )
            elif source_name == "openalex":
                if not settings.project.contact_email:
                    typer.echo(
                        "Error: project.contact_email is required for OpenAlex.",
                        err=True,
                    )
                    raise typer.Exit(code=1)
                openalex_adapter = OpenAlexAdapter(
                    source.base_url,
                    settings.project.contact_email,
                    api_key=(os.environ.get(source.api_key_env) if source.api_key_env else None),
                    include_xpac=source.include_xpac,
                    requests_per_second=source.requests_per_second,
                    page_size=source.page_size,
                )
                scholarly = discover_openalex(
                    session,
                    openalex_adapter,
                    RawResponseCache(),
                    max_authors=source.max_authors_per_run,
                    nobel_api_id=laureate_id,
                )
                write_source_limitations(
                    Path("data/exports/source_limitations.json"),
                    include_xpac=source.include_xpac,
                )
                message = (
                    f"OpenAlex: authors={scholarly.authors_resolved}, "
                    f"books={scholarly.openalex_books}, fetches={scholarly.fetches}"
                )
            elif source_name == "crossref":
                contact = (
                    os.environ.get(source.mailto_env) if source.mailto_env else None
                ) or settings.project.contact_email
                if not contact:
                    typer.echo("Error: contact email is required for Crossref.", err=True)
                    raise typer.Exit(code=1)
                crossref_adapter = CrossrefAdapter(
                    source.base_url,
                    contact,
                    user_agent=settings.project.user_agent,
                    requests_per_second=source.requests_per_second,
                )
                scholarly = enrich_crossref(session, crossref_adapter, RawResponseCache())
                write_source_limitations(
                    Path("data/exports/source_limitations.json"),
                    include_xpac=settings.sources.get("openalex", source).include_xpac,
                )
                message = (
                    f"Crossref: live_book_types={scholarly.crossref_book_types}, "
                    f"DOIs_enriched={scholarly.crossref_dois}, "
                    f"fetches={scholarly.fetches}"
                )
            else:
                wikipedia_adapter = WikipediaAdapter(
                    source.base_url,
                    settings.project.user_agent,
                    requests_per_second=source.requests_per_second,
                )
                wikipedia = discover_wikipedia(
                    session,
                    wikipedia_adapter,
                    RawResponseCache(),
                    headings=source.bibliography_headings,
                    max_authors=source.max_authors_per_run,
                    nobel_api_id=laureate_id,
                )
                message = (
                    f"Wikipedia: pages={wikipedia.pages_with_sections}, "
                    f"sections={wikipedia.sections_fetched}, "
                    f"candidates={wikipedia.candidates}, "
                    f"failures={wikipedia.failures}"
                )
    finally:
        engine.dispose()
    typer.echo(message)


@app.command("normalize")
def normalize() -> None:
    """Normalize and deterministically reconcile edition source records."""

    settings = get_settings()
    engine = make_engine(settings.project.database_url)
    try:
        with Session(engine) as session:
            editions, proposals = reconcile_editions(session)
    finally:
        engine.dispose()
    typer.echo(f"Reconciled {editions} edition(s); recorded {proposals} merge proposal(s).")


@reconcile_app.command("editions")
def reconcile_editions_command() -> None:
    """Run edition normalization and reconciliation."""

    normalize()


@reconcile_app.command("works")
def reconcile_works_command(
    review_output: Annotated[
        Path, typer.Option("--review-output", help="Work merge/split review CSV.")
    ] = Path("data/exports/work_review_queue.csv"),
) -> None:
    """Cluster editions into canonical works and apply durable overrides."""

    settings = get_settings()
    engine = make_engine(settings.project.database_url)
    try:
        with Session(engine) as session:
            summary = cluster_works(session, review_path=review_output)
    finally:
        engine.dispose()
    typer.echo(
        f"Clustered {summary.works} canonical work(s), linked "
        f"{summary.editions_linked} edition(s), created {summary.series_works} "
        f"series work(s), and queued {summary.review_items} review item(s)."
    )


@app.command("classify")
def classify() -> None:
    """Apply deterministic taxonomy and confidence rules."""

    settings = get_settings()
    engine = make_engine(settings.project.database_url)
    try:
        with Session(engine) as session:
            classification = classify_works(session, load_rules())
            relationships = score_relationships(session)
    finally:
        engine.dispose()
    typer.echo(
        f"Classified {classification.classified} work(s): "
        f"manual={classification.manual}, low_confidence={classification.low_confidence}; "
        f"scored {relationships.contributions} contribution(s), "
        f"review={relationships.contribution_reviews}."
    )


@app.command("score")
def score() -> None:
    """Recompute laureate-work relationship confidence."""

    settings = get_settings()
    engine = make_engine(settings.project.database_url)
    try:
        with Session(engine) as session:
            summary = score_relationships(session)
    finally:
        engine.dispose()
    typer.echo(
        f"Scored {summary.contributions} contribution(s); "
        f"{summary.contribution_reviews} require review."
    )


@review_app.command("export")
def review_export(
    output: Annotated[Path, typer.Option("--output", help="Review queue CSV path.")] = Path(
        "data/exports/review_queue.csv"
    ),
) -> None:
    """Export stable low-confidence contribution decisions."""

    settings = get_settings()
    engine = make_engine(settings.project.database_url)
    try:
        with Session(engine) as session:
            count = export_review_queue(session, output)
    finally:
        engine.dispose()
    typer.echo(f"Exported {count} review row(s) to {output}.")


@review_app.command("import")
def review_import(path: Path) -> None:
    """Import accept/reject decisions as durable manual overrides."""

    settings = get_settings()
    engine = make_engine(settings.project.database_url)
    try:
        with Session(engine) as session:
            count = import_review_decisions(session, path)
            score_relationships(session)
    finally:
        engine.dispose()
    typer.echo(f"Imported {count} review decision(s) from {path}.")


@review_app.command("serve")
def review_serve(
    host: Annotated[str, typer.Option(help="Bind address.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Bind port.")] = 8000,
) -> None:
    """Serve the bibliography explorer with review actions."""

    _serve_explorer(host, port)


@app.command("explore")
def explore(
    host: Annotated[str, typer.Option(help="Bind address.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Bind port.")] = 8000,
) -> None:
    """Explore laureates, prizes, books, editions, and provenance."""

    _serve_explorer(host, port)


def _serve_explorer(host: str, port: int) -> None:
    """Run the local explorer application."""

    import uvicorn

    from nobel_books.review.web import create_review_app

    settings = get_settings()
    engine = make_engine(settings.project.database_url)
    try:
        uvicorn.run(create_review_app(engine), host=host, port=port)
    finally:
        engine.dispose()


def _run_export(kind: str) -> None:
    settings = get_settings()
    output_dir = settings.exports.output_dir
    engine = make_engine(settings.project.database_url)
    try:
        with Session(engine) as session:
            if kind == "csv":
                counts = {
                    "works": export_works_csv(session, output_dir / "works.csv"),
                    "editions": export_editions_csv(session, output_dir / "editions.csv"),
                    "evidence": export_evidence_csv(session, output_dir / "evidence.csv"),
                }
            elif kind == "json":
                counts = {"laureates": export_json(session, output_dir / "bibliography.json")}
            elif kind == "markdown":
                counts = {"entries": export_markdown(session, output_dir / "bibliography.md")}
            else:
                counts = export_all(session, output_dir)
    finally:
        engine.dispose()
    typer.echo(
        f"Exported {kind}: " + ", ".join(f"{name}={count}" for name, count in counts.items())
    )


@export_app.command("csv")
def export_csv_command() -> None:
    """Export works, editions, and evidence CSVs."""

    _run_export("csv")


@export_app.command("json")
def export_json_command() -> None:
    """Export nested bibliography JSON."""

    _run_export("json")


@export_app.command("markdown")
def export_markdown_command() -> None:
    """Export classified Markdown bibliography."""

    _run_export("markdown")


@export_app.command("all")
def export_all_command() -> None:
    """Export all bibliography and coverage artifacts."""

    _run_export("all")


@audit_app.command("run")
def audit_run(
    output: Annotated[Path, typer.Option("--output")] = Path("data/exports/audit.json"),
    previous: Annotated[Path | None, typer.Option("--previous")] = None,
    regressions: Annotated[Path, typer.Option("--regressions")] = Path(
        "tests/golden/regression_bibliographies.yaml"
    ),
) -> None:
    """Report destructive drift, suspicious gaps, and incomplete research coverage."""

    settings = get_settings()
    enabled_sources = {
        name for name, config in settings.sources.items() if config.enabled and name != "nobel"
    }
    engine = make_engine(settings.project.database_url)
    try:
        with Session(engine) as session:
            report = write_audit_report(
                session,
                output,
                enabled_sources,
                previous_path=previous,
                regression_path=regressions,
            )
    finally:
        engine.dispose()
    differential = report["differential"]
    incomplete = report["incomplete_summary"]
    if not isinstance(differential, dict) or not isinstance(incomplete, dict):
        raise typer.Exit(code=1)
    typer.echo(
        f"Audit written to {output}; blocking={len(differential['blocking_changes'])}, "
        f"zero-book={incomplete['zero_book_laureates']}, "
        f"incomplete-coverage={incomplete['incomplete_source_coverage']}, "
        f"stale-overrides={incomplete['stale_overrides']}."
    )
    if differential["blocking_changes"]:
        raise typer.Exit(code=2)
