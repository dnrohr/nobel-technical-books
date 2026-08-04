"""Controlled Google Books candidate discovery."""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from nobel_books.adapters.google_books import GoogleBooksAdapter, GoogleBooksFetch
from nobel_books.cache import RawResponseCache
from nobel_books.errors import SourceUnavailableError
from nobel_books.models.database import (
    DiscoveryQuery,
    Laureate,
    PipelineRun,
    PipelineStatus,
    SourceFetch,
    SourceRecord,
)
from nobel_books.normalization.names import normalize_name
from nobel_books.pipeline.discovery import _upsert_assertion
from nobel_books.pipeline.progress import mark_laureate_progress, pending_laureates


@dataclass(frozen=True)
class QueryVariant:
    kind: str
    query: str


@dataclass
class GoogleBooksSummary:
    laureates: int = 0
    queries: int = 0
    fetches: int = 0
    volumes: int = 0
    new_volumes: int = 0
    ambiguous_relationships: int = 0
    assertions: int = 0
    failures: int = 0
    stopped_early: bool = False
    error_message: str | None = None


def author_query_variants(laureate: Laureate) -> list[QueryVariant]:
    names: list[tuple[str, str]] = [("exact_full_name", laureate.display_name)]
    given = (laureate.given_name or "").strip()
    family = (laureate.family_name or "").strip()
    if given and family:
        first_family = f"{given.split()[0]} {family}"
        names.append(("first_and_family", first_family))
        initials = " ".join(f"{part[0]}." for part in given.split() if part)
        names.append(("initials_and_family", f"{initials} {family}"))
    seen: set[str] = set()
    variants: list[QueryVariant] = []
    for kind, name in names:
        query = f'inauthor:"{name}"'
        if query not in seen:
            variants.append(QueryVariant(kind=kind, query=query))
            seen.add(query)
    return variants


def _record_fetch(
    session: Session,
    run: PipelineRun,
    fetched: GoogleBooksFetch,
    cache: RawResponseCache,
) -> SourceFetch:
    cached = cache.store("google_books", fetched.content)
    request_key = hashlib.sha256(fetched.url.encode()).hexdigest()
    existing = session.scalar(
        select(SourceFetch).where(
            SourceFetch.source == "google_books",
            SourceFetch.request_key == request_key,
            SourceFetch.content_hash == cached.content_hash,
        )
    )
    if existing is not None:
        return existing
    record = SourceFetch(
        pipeline_run=run,
        source="google_books",
        request_url=fetched.url,
        request_key=request_key,
        fetched_at=datetime.now(UTC),
        status_code=fetched.status_code,
        content_hash=cached.content_hash,
        cache_path=cached.path.as_posix(),
    )
    session.add(record)
    session.flush()
    return record


def _log_query(session: Session, laureate: Laureate, variant: QueryVariant) -> DiscoveryQuery:
    query = session.scalar(
        select(DiscoveryQuery).where(
            DiscoveryQuery.laureate_id == laureate.id,
            DiscoveryQuery.source == "google_books",
            DiscoveryQuery.query_text == variant.query,
        )
    )
    if query is None:
        query = DiscoveryQuery(
            laureate_id=laureate.id,
            source="google_books",
            query_text=variant.query,
        )
        session.add(query)
    query.variant_type = variant.kind
    query.status = "running"
    query.result_count = 0
    query.executed_at = datetime.now(UTC)
    return query


def _relationship_status(laureate: Laureate, authors: object) -> str:
    if not isinstance(authors, list):
        return "ambiguous"
    expected = {
        normalize_name(laureate.display_name),
        normalize_name(
            " ".join(
                value for value in (laureate.given_name or "", laureate.family_name or "") if value
            )
        ),
    }
    if laureate.given_name and laureate.family_name:
        expected.add(normalize_name(f"{laureate.given_name.split()[0]} {laureate.family_name}"))
    normalized_authors = {normalize_name(author) for author in authors if isinstance(author, str)}
    return "supported" if expected & normalized_authors else "ambiguous"


def _persist_volume(
    session: Session,
    laureate: Laureate,
    fetched: GoogleBooksFetch,
    source_fetch: SourceFetch,
    volume_id: str,
    volume_info: dict[str, object],
) -> tuple[bool, int, bool]:
    record = session.scalar(
        select(SourceRecord).where(
            SourceRecord.source == "google_books",
            SourceRecord.source_entity_type == "edition",
            SourceRecord.source_entity_id == volume_id,
        )
    )
    created = record is None
    relationship = _relationship_status(laureate, volume_info.get("authors"))
    raw: dict[str, object] = {
        "volume_id": volume_id,
        **volume_info,
        "candidate_for_laureate_id": laureate.id,
        "query_variant": fetched.query,
        "relationship_status": relationship,
        "review_status": "needs_review",
    }
    if record is None:
        record = SourceRecord(
            source_fetch_id=source_fetch.id,
            source="google_books",
            source_entity_type="edition",
            source_entity_id=volume_id,
            raw_json=raw,
            source_url=f"https://books.google.com/books?id={volume_id}",
        )
        session.add(record)
        session.flush()
    count = 0
    for predicate, value in raw.items():
        count += _upsert_assertion(session, record, predicate, value)
    return created, count, relationship == "ambiguous"


def discover_google_books(
    session: Session,
    adapter: GoogleBooksAdapter,
    cache: RawResponseCache,
    *,
    max_authors: int,
    nobel_api_id: str | None = None,
    refresh: bool = False,
) -> GoogleBooksSummary:
    laureates = pending_laureates(
        session,
        "google_books",
        max_authors,
        nobel_api_id=nobel_api_id,
        refresh=refresh,
    )
    run = PipelineRun(
        profile="discover-google-books",
        status=PipelineStatus.RUNNING,
        started_at=datetime.now(UTC),
    )
    session.add(run)
    session.flush()
    summary = GoogleBooksSummary(laureates=len(laureates))
    try:
        for laureate in laureates:
            laureate_volume_count = 0
            for variant in author_query_variants(laureate):
                summary.queries += 1
                query_log = _log_query(session, laureate, variant)
                seen_for_query: set[str] = set()
                try:
                    for fetched in adapter.volumes(variant.query, variant.kind):
                        summary.fetches += 1
                        source_fetch = _record_fetch(session, run, fetched, cache)
                        for volume in fetched.response.items:
                            summary.volumes += 1
                            laureate_volume_count += 1
                            seen_for_query.add(volume.id)
                            created, count, ambiguous = _persist_volume(
                                session,
                                laureate,
                                fetched,
                                source_fetch,
                                volume.id,
                                volume.volume_info,
                            )
                            summary.new_volumes += int(created)
                            summary.assertions += count
                            summary.ambiguous_relationships += int(ambiguous)
                except SourceUnavailableError as exc:
                    query_log.status = "failed"
                    query_log.result_count = len(seen_for_query)
                    summary.failures += 1
                    summary.stopped_early = True
                    summary.error_message = str(exc)
                    mark_laureate_progress(session, laureate, "google_books", "failed")
                    break
                query_log.status = "succeeded"
                query_log.result_count = len(seen_for_query)
            if not summary.stopped_early:
                mark_laureate_progress(
                    session,
                    laureate,
                    "google_books",
                    "succeeded",
                    result_count=laureate_volume_count,
                )
            if summary.stopped_early:
                break
        run.status = PipelineStatus.FAILED if summary.stopped_early else PipelineStatus.SUCCEEDED
        run.finished_at = datetime.now(UTC)
        run.error_message = summary.error_message
        session.commit()
    except Exception as exc:
        session.rollback()
        session.add(
            PipelineRun(
                profile="discover-google-books",
                status=PipelineStatus.FAILED,
                started_at=run.started_at,
                finished_at=datetime.now(UTC),
                error_message=str(exc),
            )
        )
        session.commit()
        raise
    return summary
