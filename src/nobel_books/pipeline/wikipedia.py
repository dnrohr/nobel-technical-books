"""Optional Wikipedia bibliography fallback extraction."""

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from nobel_books.adapters.wikipedia import WikipediaAdapter, WikipediaFetch
from nobel_books.cache import RawResponseCache
from nobel_books.errors import SourceUnavailableError
from nobel_books.models.database import (
    Laureate,
    PipelineRun,
    PipelineStatus,
    SourceFetch,
    SourceRecord,
)
from nobel_books.normalization.titles import normalize_title
from nobel_books.pipeline.discovery import _upsert_assertion

LIST_ITEM = re.compile(r"^\s*[*#]\s*(.+?)\s*$")
CITE_BOOK = re.compile(r"\{\{\s*cite\s+book\s*\|(.*?)\}\}", re.IGNORECASE)
ITALIC_TITLE = re.compile(r"'{2,5}([^']+?)'{2,5}")
WIKILINK_TITLE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
YEAR = re.compile(r"(?<!\d)(1[0-9]{3}|20[0-9]{2})(?!\d)")


@dataclass(frozen=True)
class WikipediaCandidate:
    title: str
    year: int | None
    publisher: str | None
    isbn: str | None
    citation: str


@dataclass
class WikipediaSummary:
    laureates_considered: int = 0
    pages_with_sections: int = 0
    sections_fetched: int = 0
    candidates: int = 0
    failures: int = 0


def _template_fields(content: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for part in content.split("|"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        fields[key.strip().casefold()] = value.strip()
    return fields


def parse_bibliography_wikitext(wikitext: str) -> list[WikipediaCandidate]:
    """Parse conservative list items and Cite book templates."""

    candidates: list[WikipediaCandidate] = []
    seen: set[tuple[str, int | None]] = set()
    for line in wikitext.splitlines():
        match = LIST_ITEM.match(line)
        if not match:
            continue
        citation = match.group(1)
        title: str | None = None
        publisher: str | None = None
        isbn: str | None = None
        year: int | None = None
        cite = CITE_BOOK.search(citation)
        if cite:
            fields = _template_fields(cite.group(1))
            title = fields.get("title")
            publisher = fields.get("publisher")
            isbn = fields.get("isbn")
            year_value = fields.get("year") or fields.get("date")
            year_match = YEAR.search(year_value or "")
            year = int(year_match.group(1)) if year_match else None
        if not title:
            title_match = ITALIC_TITLE.search(citation) or WIKILINK_TITLE.search(citation)
            title = title_match.group(1).strip() if title_match else None
            year_match = YEAR.search(citation)
            year = int(year_match.group(1)) if year_match else None
        if not title or not normalize_title(title):
            continue
        key = (normalize_title(title), year)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            WikipediaCandidate(
                title=title,
                year=year,
                publisher=publisher,
                isbn=isbn,
                citation=citation,
            )
        )
    return candidates


def _record_fetch(
    session: Session,
    run: PipelineRun,
    fetched: WikipediaFetch,
    cache: RawResponseCache,
) -> SourceFetch:
    cached = cache.store("wikipedia", fetched.content)
    request_key = hashlib.sha256(fetched.url.encode()).hexdigest()
    existing = session.scalar(
        select(SourceFetch).where(
            SourceFetch.source == "wikipedia",
            SourceFetch.request_key == request_key,
            SourceFetch.content_hash == cached.content_hash,
        )
    )
    if existing is not None:
        return existing
    record = SourceFetch(
        pipeline_run=run,
        source="wikipedia",
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


def _parse_metadata(fetched: WikipediaFetch) -> tuple[str, int, int, list[dict[str, object]]]:
    parsed = fetched.payload["parse"]
    title = str(parsed.get("title") or fetched.page_title)
    page_id = int(parsed.get("pageid") or 0)
    revision_id = int(parsed.get("revid") or 0)
    sections = parsed.get("sections", [])
    return title, page_id, revision_id, sections if isinstance(sections, list) else []


def discover_wikipedia(
    session: Session,
    adapter: WikipediaAdapter,
    cache: RawResponseCache,
    *,
    headings: list[str],
    max_authors: int,
    nobel_api_id: str | None = None,
) -> WikipediaSummary:
    query = select(Laureate).order_by(Laureate.id)
    if nobel_api_id is not None:
        query = query.where(Laureate.nobel_api_id == nobel_api_id)
    laureates = session.scalars(query.limit(max_authors)).all()
    run = PipelineRun(
        profile="discover-wikipedia",
        status=PipelineStatus.RUNNING,
        started_at=datetime.now(UTC),
    )
    session.add(run)
    session.flush()
    summary = WikipediaSummary(laureates_considered=len(laureates))
    normalized_headings = {normalize_title(heading) for heading in headings}
    for laureate in laureates:
        try:
            metadata = adapter.sections(laureate.display_name)
            _record_fetch(session, run, metadata, cache)
            page_title, page_id, revision_id, sections = _parse_metadata(metadata)
            relevant = [
                section
                for section in sections
                if normalize_title(str(section.get("line", ""))) in normalized_headings
                and isinstance(section.get("index"), str)
            ]
            if relevant:
                summary.pages_with_sections += 1
            for section in relevant:
                try:
                    section_fetch = adapter.section(page_title, str(section["index"]))
                    source_fetch = _record_fetch(session, run, section_fetch, cache)
                    summary.sections_fetched += 1
                    parsed = section_fetch.payload["parse"]
                    revision_id = int(parsed.get("revid") or revision_id)
                    wikitext_value = parsed.get("wikitext", "")
                    wikitext = str(wikitext_value) if isinstance(wikitext_value, str) else ""
                    for candidate in parse_bibliography_wikitext(wikitext):
                        stable = (
                            f"{page_id}:{revision_id}:{section['index']}:"
                            f"{normalize_title(candidate.title)}:{candidate.year}"
                        )
                        entity_id = hashlib.sha256(stable.encode()).hexdigest()
                        record = session.scalar(
                            select(SourceRecord).where(
                                SourceRecord.source == "wikipedia",
                                SourceRecord.source_entity_type == "work",
                                SourceRecord.source_entity_id == entity_id,
                            )
                        )
                        raw: dict[str, object] = {
                            "title": candidate.title,
                            "year": candidate.year,
                            "publisher": candidate.publisher,
                            "isbn": candidate.isbn,
                            "citation": candidate.citation,
                            "page_title": page_title,
                            "page_id": page_id,
                            "revision_id": revision_id,
                            "section_index": section["index"],
                            "section_heading": section.get("line"),
                            "candidate_for_laureate_id": laureate.id,
                            "review_status": "needs_corroboration",
                        }
                        if record is None:
                            record = SourceRecord(
                                source_fetch_id=source_fetch.id,
                                source="wikipedia",
                                source_entity_type="work",
                                source_entity_id=entity_id,
                                raw_json=raw,
                                source_url=(
                                    f"https://en.wikipedia.org/?curid={page_id}&oldid={revision_id}"
                                ),
                            )
                            session.add(record)
                            session.flush()
                            summary.candidates += 1
                        for predicate, value in raw.items():
                            _upsert_assertion(
                                session,
                                record,
                                predicate,
                                value,
                                reliability_class="D",
                                confidence=0.35,
                            )
                except (SourceUnavailableError, KeyError, TypeError, ValueError):
                    summary.failures += 1
        except (SourceUnavailableError, KeyError, TypeError, ValueError):
            summary.failures += 1
    run.status = PipelineStatus.SUCCEEDED
    run.finished_at = datetime.now(UTC)
    session.commit()
    return summary
