"""OpenAlex book discovery and Crossref DOI enrichment."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from nobel_books.adapters.crossref import BOOK_TYPES, CrossrefAdapter
from nobel_books.adapters.openalex import OpenAlexAdapter
from nobel_books.cache import RawResponseCache
from nobel_books.models.database import (
    Edition,
    EditionSourceRecord,
    ExternalIdentity,
    Laureate,
    PipelineRun,
    PipelineStatus,
    SourceFetch,
    SourceRecord,
)
from nobel_books.pipeline.discovery import _upsert_assertion


@dataclass
class ScholarlySummary:
    authors_resolved: int = 0
    openalex_books: int = 0
    crossref_dois: int = 0
    crossref_book_types: int = 0
    fetches: int = 0
    assertions: int = 0


def _record_fetch(
    session: Session,
    run: PipelineRun,
    source: str,
    url: str,
    status_code: int,
    content: bytes,
    cache: RawResponseCache,
) -> SourceFetch:
    cached = cache.store(source, content)
    request_key = hashlib.sha256(url.encode()).hexdigest()
    existing = session.scalar(
        select(SourceFetch).where(
            SourceFetch.source == source,
            SourceFetch.request_key == request_key,
            SourceFetch.content_hash == cached.content_hash,
        )
    )
    if existing is not None:
        return existing
    record = SourceFetch(
        pipeline_run=run,
        source=source,
        request_url=url,
        request_key=request_key,
        fetched_at=datetime.now(UTC),
        status_code=status_code,
        content_hash=cached.content_hash,
        cache_path=cached.path.as_posix(),
    )
    session.add(record)
    session.flush()
    return record


def _upsert_openalex_identity(
    session: Session, laureate: Laureate, author: dict[str, Any]
) -> str | None:
    raw_id = author.get("id")
    if not isinstance(raw_id, str):
        return None
    author_id = raw_id.rstrip("/").rsplit("/", 1)[-1]
    identity = session.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.scheme == "openalex",
            ExternalIdentity.value == author_id,
        )
    )
    if identity is None:
        identity = ExternalIdentity(scheme="openalex", value=author_id)
        session.add(identity)
    identity.laureate_id = laureate.id
    identity.canonical_url = raw_id
    identity.resolution_status = "verified"
    identity.confidence = 1.0
    identity.evidence_json = {"method": "exact_orcid"}
    return author_id


def discover_openalex(
    session: Session,
    adapter: OpenAlexAdapter,
    cache: RawResponseCache,
    *,
    max_authors: int,
    nobel_api_id: str | None = None,
) -> ScholarlySummary:
    query = select(Laureate).order_by(Laureate.id)
    if nobel_api_id is not None:
        query = query.where(Laureate.nobel_api_id == nobel_api_id)
    laureates = session.scalars(query.limit(max_authors)).all()
    run = PipelineRun(
        profile="discover-openalex",
        status=PipelineStatus.RUNNING,
        started_at=datetime.now(UTC),
    )
    session.add(run)
    session.flush()
    summary = ScholarlySummary()
    try:
        for laureate in laureates:
            openalex = session.scalar(
                select(ExternalIdentity).where(
                    ExternalIdentity.laureate_id == laureate.id,
                    ExternalIdentity.scheme == "openalex",
                    ExternalIdentity.resolution_status == "verified",
                )
            )
            author_id = openalex.value if openalex else None
            if author_id is None:
                orcid = session.scalar(
                    select(ExternalIdentity).where(
                        ExternalIdentity.laureate_id == laureate.id,
                        ExternalIdentity.scheme == "orcid",
                        ExternalIdentity.resolution_status == "verified",
                    )
                )
                if orcid is None:
                    continue
                fetched_author = adapter.resolve_orcid(orcid.value)
                summary.fetches += 1
                _record_fetch(
                    session,
                    run,
                    "openalex",
                    fetched_author.url,
                    fetched_author.status_code,
                    fetched_author.content,
                    cache,
                )
                if len(fetched_author.response.results) != 1:
                    continue
                author_id = _upsert_openalex_identity(
                    session, laureate, fetched_author.response.results[0]
                )
            if author_id is None:
                continue
            summary.authors_resolved += 1
            for fetched in adapter.books(author_id):
                summary.fetches += 1
                source_fetch = _record_fetch(
                    session,
                    run,
                    "openalex",
                    fetched.url,
                    fetched.status_code,
                    fetched.content,
                    cache,
                )
                for raw in fetched.response.results:
                    raw_id = raw.get("id")
                    if not isinstance(raw_id, str) or raw.get("type") != "book":
                        continue
                    work_id = raw_id.rstrip("/").rsplit("/", 1)[-1]
                    record = session.scalar(
                        select(SourceRecord).where(
                            SourceRecord.source == "openalex",
                            SourceRecord.source_entity_type == "work",
                            SourceRecord.source_entity_id == work_id,
                        )
                    )
                    if record is None:
                        record = SourceRecord(
                            source_fetch_id=source_fetch.id,
                            source="openalex",
                            source_entity_type="work",
                            source_entity_id=work_id,
                            raw_json=raw,
                            source_url=raw_id,
                        )
                        session.add(record)
                        session.flush()
                        summary.openalex_books += 1
                    for predicate, value in raw.items():
                        summary.assertions += _upsert_assertion(session, record, predicate, value)
                    summary.assertions += _upsert_assertion(
                        session, record, "candidate_for_laureate_id", laureate.id
                    )
        run.status = PipelineStatus.SUCCEEDED
        run.finished_at = datetime.now(UTC)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return summary


def enrich_crossref(
    session: Session,
    adapter: CrossrefAdapter,
    cache: RawResponseCache,
) -> ScholarlySummary:
    run = PipelineRun(
        profile="enrich-crossref",
        status=PipelineStatus.RUNNING,
        started_at=datetime.now(UTC),
    )
    session.add(run)
    session.flush()
    summary = ScholarlySummary()
    types_fetch = adapter.types()
    summary.fetches += 1
    _record_fetch(
        session,
        run,
        "crossref",
        types_fetch.url,
        types_fetch.status_code,
        types_fetch.content,
        cache,
    )
    items = types_fetch.message.get("items", []) if isinstance(types_fetch.message, dict) else []
    live_types = {
        item["id"] for item in items if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    summary.crossref_book_types = len(BOOK_TYPES & live_types)
    editions = session.scalars(
        select(Edition).where(Edition.doi.is_not(None)).order_by(Edition.doi)
    ).all()
    for edition in editions:
        if not edition.doi:
            continue
        fetched = adapter.doi(edition.doi)
        summary.fetches += 1
        source_fetch = _record_fetch(
            session,
            run,
            "crossref",
            fetched.url,
            fetched.status_code,
            fetched.content,
            cache,
        )
        if not isinstance(fetched.message, dict):
            continue
        work_type = fetched.message.get("type")
        if work_type not in BOOK_TYPES:
            continue
        record = session.scalar(
            select(SourceRecord).where(
                SourceRecord.source == "crossref",
                SourceRecord.source_entity_type == "edition",
                SourceRecord.source_entity_id == edition.doi,
            )
        )
        if record is None:
            record = SourceRecord(
                source_fetch_id=source_fetch.id,
                source="crossref",
                source_entity_type="edition",
                source_entity_id=edition.doi,
                raw_json=fetched.message,
                source_url=f"https://doi.org/{edition.doi}",
            )
            session.add(record)
            session.flush()
            session.add(EditionSourceRecord(source_record_id=record.id, edition_id=edition.id))
            summary.crossref_dois += 1
        for predicate, value in fetched.message.items():
            summary.assertions += _upsert_assertion(session, record, predicate, value)
    run.status = PipelineStatus.SUCCEEDED
    run.finished_at = datetime.now(UTC)
    session.commit()
    return summary


def source_limitations_document(*, include_xpac: bool) -> dict[str, object]:
    return {
        "openalex": {
            "coverage": "technical and scholarly books linked to resolved authors",
            "limitations": [
                "does not cover most memoirs or popular books",
                "older non-digitized monographs may be absent",
                "book coverage is not comprehensive",
            ],
            "include_xpac": include_xpac,
            "xpac_quality_warning": (
                "XPAC records have lower average data quality" if include_xpac else None
            ),
        },
        "crossref": {
            "coverage": "DOI-registered books and monographs",
            "limitations": [
                "most older books lack DOIs",
                "used for enrichment and corroboration, not complete discovery",
            ],
            "book_types": sorted(BOOK_TYPES),
        },
    }


def write_source_limitations(path: Path, *, include_xpac: bool) -> None:
    document = source_limitations_document(include_xpac=include_xpac)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
