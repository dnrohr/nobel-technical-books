"""Open Library authority resolution and source-native discovery."""

import csv
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from nobel_books.adapters.openlibrary import (
    AuthorSearchDocument,
    AuthorSearchResponse,
    OpenLibraryAdapter,
    OpenLibraryFetch,
)
from nobel_books.cache import RawResponseCache
from nobel_books.errors import SourceUnavailableError
from nobel_books.models.database import (
    ExternalIdentity,
    Laureate,
    PipelineRun,
    PipelineStatus,
    SourceAuthorCandidate,
    SourceFetch,
    SourceRecord,
)
from nobel_books.normalization.names import normalize_name
from nobel_books.pipeline.discovery import _upsert_assertion
from nobel_books.pipeline.progress import mark_laureate_progress, pending_laureates


@dataclass
class OpenLibrarySummary:
    authors_considered: int = 0
    authors_verified: int = 0
    candidates_for_review: int = 0
    works: int = 0
    editions: int = 0
    fetches: int = 0
    assertions: int = 0
    failures: int = 0


def _record_fetch(
    session: Session,
    run: PipelineRun,
    fetched: OpenLibraryFetch,
    cache: RawResponseCache,
) -> SourceFetch:
    cached = cache.store("openlibrary", fetched.content)
    request_key = hashlib.sha256(fetched.url.encode()).hexdigest()
    existing = session.scalar(
        select(SourceFetch).where(
            SourceFetch.source == "openlibrary",
            SourceFetch.request_key == request_key,
            SourceFetch.content_hash == cached.content_hash,
        )
    )
    if existing is not None:
        return existing
    record = SourceFetch(
        pipeline_run=run,
        source="openlibrary",
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


def _date_matches(candidate: str | None, expected: str | None) -> bool:
    if not candidate or not expected:
        return False
    return candidate.strip().casefold() == expected.strip().casefold()


def score_author_candidate(
    laureate: Laureate, candidate: AuthorSearchDocument
) -> tuple[float, dict[str, object]]:
    exact_name = normalize_name(laureate.display_name) in {
        normalize_name(candidate.name),
        *(normalize_name(name) for name in candidate.alternate_names),
    }
    birth_match = _date_matches(candidate.birth_date, laureate.birth_date_raw)
    death_match = _date_matches(candidate.death_date, laureate.death_date_raw)
    score = (0.25 if exact_name else 0.0) + (0.35 if birth_match else 0.0)
    score += 0.25 if death_match else 0.0
    if not birth_match and not death_match:
        score = min(score, 0.55)
    return score, {
        "exact_normalized_name": exact_name,
        "birth_date_match": birth_match,
        "death_date_match": death_match,
        "candidate_birth_date": candidate.birth_date,
        "candidate_death_date": candidate.death_date,
    }


def _upsert_candidate(
    session: Session,
    laureate: Laureate,
    author_id: str,
    name: str,
    confidence: float,
    status: str,
    evidence: dict[str, object],
    source_fetch_id: int | None,
) -> SourceAuthorCandidate:
    candidate = session.scalar(
        select(SourceAuthorCandidate).where(
            SourceAuthorCandidate.laureate_id == laureate.id,
            SourceAuthorCandidate.source == "openlibrary",
            SourceAuthorCandidate.source_author_id == author_id,
        )
    )
    if candidate is None:
        candidate = SourceAuthorCandidate(
            laureate_id=laureate.id,
            source="openlibrary",
            source_author_id=author_id,
        )
        session.add(candidate)
    candidate.display_name = name
    candidate.confidence = confidence
    candidate.status = status
    candidate.evidence_json = evidence
    candidate.source_fetch_id = source_fetch_id
    candidate.updated_at = datetime.now(UTC)
    return candidate


def _source_id(key: object, prefix: str) -> str | None:
    if not isinstance(key, str):
        return None
    return key.removeprefix(prefix).strip("/")


def _persist_entries(
    session: Session,
    source_fetch: SourceFetch,
    fetched: OpenLibraryFetch,
    entity_type: str,
    parent_predicate: str | None = None,
) -> tuple[list[str], int]:
    entries = fetched.payload.get("entries", [])
    if not isinstance(entries, list):
        return [], 0
    ids: list[str] = []
    assertion_count = 0
    prefix = "/works/" if entity_type == "work" else "/books/"
    for raw_value in entries:
        if not isinstance(raw_value, dict):
            continue
        raw: dict[str, Any] = dict(raw_value)
        entity_id = _source_id(raw.get("key"), prefix)
        if entity_id is None:
            continue
        if parent_predicate and fetched.parent_id:
            raw[parent_predicate] = fetched.parent_id
        record = session.scalar(
            select(SourceRecord).where(
                SourceRecord.source_fetch_id == source_fetch.id,
                SourceRecord.source == "openlibrary",
                SourceRecord.source_entity_type == entity_type,
                SourceRecord.source_entity_id == entity_id,
            )
        )
        if record is None:
            record = SourceRecord(
                source_fetch_id=source_fetch.id,
                source="openlibrary",
                source_entity_type=entity_type,
                source_entity_id=entity_id,
                raw_json=raw,
                source_url=f"https://openlibrary.org{raw['key']}",
            )
            session.add(record)
            session.flush()
        record.raw_json = raw
        for predicate, value in raw.items():
            assertion_count += _upsert_assertion(session, record, predicate, value)
        ids.append(entity_id)
    return ids, assertion_count


def _resolve_author(
    session: Session,
    run: PipelineRun,
    laureate: Laureate,
    adapter: OpenLibraryAdapter,
    cache: RawResponseCache,
    summary: OpenLibrarySummary,
) -> str | None:
    verified = session.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.laureate_id == laureate.id,
            ExternalIdentity.scheme == "openlibrary",
            ExternalIdentity.resolution_status == "verified",
        )
    )
    if verified is not None:
        author_id = verified.value.removeprefix("/authors/").strip("/")
        _upsert_candidate(
            session,
            laureate,
            author_id,
            laureate.display_name,
            1.0,
            "verified",
            {"method": "wikidata_authority_identifier"},
            None,
        )
        return author_id

    fetched = adapter.search_author(laureate.display_name)
    summary.fetches += 1
    source_fetch = _record_fetch(session, run, fetched, cache)
    try:
        response = AuthorSearchResponse.model_validate(fetched.payload)
    except ValidationError:
        return None
    for document in response.docs:
        score, evidence = score_author_candidate(laureate, document)
        author_id = document.key.removeprefix("/authors/").strip("/")
        _upsert_candidate(
            session,
            laureate,
            author_id,
            document.name,
            score,
            "review",
            evidence,
            source_fetch.id,
        )
        summary.candidates_for_review += 1
    return None


def discover_openlibrary(
    session: Session,
    adapter: OpenLibraryAdapter,
    cache: RawResponseCache,
    *,
    max_authors: int,
    nobel_api_id: str | None = None,
    refresh: bool = False,
    zero_results_only: bool = False,
) -> OpenLibrarySummary:
    """Resolve a cautious cohort and retrieve verified authors' works and editions."""

    laureates = pending_laureates(
        session,
        "openlibrary",
        max_authors,
        nobel_api_id=nobel_api_id,
        refresh=refresh,
        zero_results_only=zero_results_only,
    )
    run = PipelineRun(
        profile="discover-openlibrary",
        status=PipelineStatus.RUNNING,
        started_at=datetime.now(UTC),
    )
    session.add(run)
    session.flush()
    summary = OpenLibrarySummary(authors_considered=len(laureates))
    try:
        for laureate in laureates:
            laureate_works = 0
            try:
                with session.begin_nested():
                    author_id = _resolve_author(session, run, laureate, adapter, cache, summary)
                    if author_id is None:
                        mark_laureate_progress(
                            session, laureate, "openlibrary", "succeeded", result_count=0
                        )
                        continue
                    summary.authors_verified += 1
                    for works_fetch in adapter.author_works(author_id):
                        summary.fetches += 1
                        source_fetch = _record_fetch(session, run, works_fetch, cache)
                        work_ids, count = _persist_entries(
                            session,
                            source_fetch,
                            works_fetch,
                            "work",
                            "author_id",
                        )
                        summary.works += len(work_ids)
                        laureate_works += len(work_ids)
                        summary.assertions += count
                        for work_id in work_ids:
                            for editions_fetch in adapter.work_editions(work_id):
                                summary.fetches += 1
                                edition_fetch_record = _record_fetch(
                                    session, run, editions_fetch, cache
                                )
                                edition_ids, edition_count = _persist_entries(
                                    session,
                                    edition_fetch_record,
                                    editions_fetch,
                                    "edition",
                                    "work_id",
                                )
                                summary.editions += len(edition_ids)
                                summary.assertions += edition_count
                mark_laureate_progress(
                    session,
                    laureate,
                    "openlibrary",
                    "succeeded",
                    result_count=laureate_works,
                )
            except SourceUnavailableError:
                summary.failures += 1
                mark_laureate_progress(session, laureate, "openlibrary", "failed")
                continue
        run.status = PipelineStatus.SUCCEEDED
        run.finished_at = datetime.now(UTC)
        run.error_message = (
            f"{summary.failures} author request(s) skipped" if summary.failures else None
        )
        session.commit()
    except Exception as exc:
        session.rollback()
        session.add(
            PipelineRun(
                profile="discover-openlibrary",
                status=PipelineStatus.FAILED,
                started_at=run.started_at,
                finished_at=datetime.now(UTC),
                error_message=str(exc),
            )
        )
        session.commit()
        raise
    return summary


def export_openlibrary_identity_review(session: Session, path: Path) -> int:
    rows = session.execute(
        select(Laureate, SourceAuthorCandidate)
        .join(SourceAuthorCandidate, SourceAuthorCandidate.laureate_id == Laureate.id)
        .where(
            SourceAuthorCandidate.source == "openlibrary",
            SourceAuthorCandidate.status == "review",
        )
        .order_by(Laureate.display_name, SourceAuthorCandidate.confidence.desc())
    ).all()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            [
                "nobel_api_id",
                "laureate_name",
                "openlibrary_author_id",
                "candidate_name",
                "confidence",
                "status",
            ]
        )
        for laureate, candidate in rows:
            writer.writerow(
                [
                    laureate.nobel_api_id,
                    laureate.display_name,
                    candidate.source_author_id,
                    candidate.display_name,
                    f"{candidate.confidence:.2f}",
                    candidate.status,
                ]
            )
    return len(rows)
