"""Normalize source-native editions and deterministically reconcile them."""

import hashlib
from dataclasses import dataclass, field
from typing import Any

from rapidfuzz.fuzz import ratio
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from nobel_books.models.database import (
    Contribution,
    Edition,
    EditionMergeProposal,
    EditionSourceRecord,
    RetailRatingObservation,
    SourceRecord,
)
from nobel_books.normalization.dates import parse_date
from nobel_books.normalization.identifiers import (
    is_valid_isbn10,
    is_valid_isbn13,
    isbn10_to_isbn13,
    normalize_isbn,
)
from nobel_books.normalization.languages import normalize_language
from nobel_books.normalization.names import normalize_name
from nobel_books.normalization.titles import normalize_title


@dataclass
class EditionCandidate:
    record: SourceRecord
    title: str
    normalized_title: str
    subtitle: str | None = None
    language: str | None = None
    publication_date_raw: str | None = None
    publication_year: int | None = None
    publisher: str | None = None
    page_count: int | None = None
    isbn10: set[str] = field(default_factory=set)
    isbn13: set[str] = field(default_factory=set)
    oclc: set[str] = field(default_factory=set)
    doi: set[str] = field(default_factory=set)
    contributors: set[str] = field(default_factory=set)
    identifier_issues: list[dict[str, object]] = field(default_factory=list)

    @property
    def logical_key(self) -> str:
        return f"{self.record.source}:{self.record.source_entity_id or self.record.id}"


class UnionFind:
    def __init__(self, keys: list[str]) -> None:
        self.parent = {key: key for key in keys}

    def find(self, key: str) -> str:
        while self.parent[key] != key:
            self.parent[key] = self.parent[self.parent[key]]
            key = self.parent[key]
        return key

    def union(self, left: str, right: str) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            root, child = sorted((left_root, right_root))
            self.parent[child] = root


def _unwrap(value: object) -> object:
    if isinstance(value, list):
        unwrapped = [_unwrap(item) for item in value]
        return unwrapped[0] if len(unwrapped) == 1 else unwrapped
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


def _strings(value: object) -> list[str]:
    value = _unwrap(value)
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_strings(item))
        return result
    if isinstance(value, dict):
        return [str(item) for item in value.values() if isinstance(item, str)]
    return []


def _first(raw: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        values = _strings(raw.get(key))
        if values:
            return values[0]
    return None


def _identifier_values(raw: dict[str, Any], direct_keys: tuple[str, ...], kind: str) -> list[str]:
    values: list[str] = []
    for key in direct_keys:
        values.extend(_strings(raw.get(key)))
    industry = raw.get("industryIdentifiers")
    if isinstance(industry, list):
        for entry in industry:
            if (
                isinstance(entry, dict)
                and str(entry.get("type", "")).replace("_", "").casefold() == kind.casefold()
                and isinstance(entry.get("identifier"), str)
            ):
                values.append(entry["identifier"])
    return values


def candidate_from_record(record: SourceRecord) -> EditionCandidate | None:
    raw: dict[str, Any] = dict(record.raw_json)
    title = _first(raw, "title", "itemLabel")
    if not title:
        return None
    date_raw = _first(raw, "publish_date", "publishedDate", "publication_date")
    parsed_date = parse_date(date_raw)
    language = _first(raw, "language")
    if language is None:
        language = _first(raw, "languages")
    candidate = EditionCandidate(
        record=record,
        title=title,
        normalized_title=normalize_title(title),
        subtitle=_first(raw, "subtitle"),
        language=normalize_language(language),
        publication_date_raw=date_raw,
        publication_year=parsed_date.lower_year,
        publisher=_first(raw, "publisher", "publishers"),
        page_count=next(
            (
                int(value)
                for value in (
                    raw.get("pageCount"),
                    raw.get("number_of_pages"),
                    raw.get("pagination"),
                )
                if isinstance(value, int | str) and str(value).isdigit()
            ),
            None,
        ),
        oclc={
            normalize_isbn(value)
            for value in _identifier_values(raw, ("oclc", "oclc_numbers"), "oclc")
        },
        doi={
            value.casefold().removeprefix("https://doi.org/") for value in _strings(raw.get("doi"))
        },
        contributors={
            normalize_name(value)
            for key in ("authors", "person", "author_id")
            for value in _strings(raw.get(key))
        },
    )
    for value in _identifier_values(raw, ("isbn10", "isbn_10"), "isbn10"):
        normalized = normalize_isbn(value)
        if is_valid_isbn10(normalized):
            candidate.isbn10.add(normalized)
            converted = isbn10_to_isbn13(normalized)
            if converted:
                candidate.isbn13.add(converted)
        else:
            candidate.identifier_issues.append({"type": "invalid_isbn10", "value": value})
    for value in _identifier_values(raw, ("isbn13", "isbn_13"), "isbn13"):
        normalized = normalize_isbn(value)
        if is_valid_isbn13(normalized):
            candidate.isbn13.add(normalized)
        else:
            candidate.identifier_issues.append({"type": "invalid_isbn13", "value": value})
    return candidate


def hard_conflicts(left: EditionCandidate, right: EditionCandidate) -> list[str]:
    conflicts: list[str] = []
    if left.isbn13 and right.isbn13 and left.isbn13.isdisjoint(right.isbn13):
        conflicts.append("conflicting_isbn13")
    if left.isbn10 and right.isbn10 and left.isbn10.isdisjoint(right.isbn10):
        conflicts.append("conflicting_isbn10")
    if left.doi and right.doi and left.doi.isdisjoint(right.doi):
        conflicts.append("conflicting_doi")
    return conflicts


def fuzzy_score(left: EditionCandidate, right: EditionCandidate) -> tuple[float, dict[str, object]]:
    title = ratio(left.normalized_title, right.normalized_title) / 100
    contributors = 0.0
    if left.contributors and right.contributors:
        contributors = len(left.contributors & right.contributors) / len(
            left.contributors | right.contributors
        )
    year = float(
        left.publication_year is not None
        and right.publication_year is not None
        and abs(left.publication_year - right.publication_year) <= 1
    )
    publisher = float(
        bool(left.publisher and right.publisher)
        and normalize_title(left.publisher or "") == normalize_title(right.publisher or "")
    )
    language = float(bool(left.language and right.language) and left.language == right.language)
    score = 0.45 * title + 0.20 * contributors + 0.10 * year
    score += 0.10 * publisher + 0.10 * language
    return score, {
        "title_similarity": title,
        "contributor_similarity": contributors,
        "year_compatible": bool(year),
        "publisher_compatible": bool(publisher),
        "language_compatible": bool(language),
    }


def _exact_match(left: EditionCandidate, right: EditionCandidate) -> str | None:
    if left.isbn13 & right.isbn13:
        return "exact_isbn13"
    if left.isbn10 & right.isbn10:
        return "exact_isbn10"
    if left.oclc & right.oclc:
        return "exact_oclc"
    if left.doi & right.doi:
        return "exact_doi"
    return None


def reconcile_editions(session: Session) -> tuple[int, int]:
    records = session.scalars(
        select(SourceRecord)
        .where(SourceRecord.source_entity_type == "edition")
        .order_by(SourceRecord.source, SourceRecord.source_entity_id, SourceRecord.id)
    ).all()
    candidates = [candidate for record in records if (candidate := candidate_from_record(record))]
    candidates.sort(key=lambda candidate: candidate.logical_key)
    union = UnionFind([candidate.logical_key for candidate in candidates])
    session.execute(delete(EditionMergeProposal))
    # Membership is derived from the current source records. Rebuild it so a
    # record that moves to a different cluster cannot leave an orphan edition.
    session.execute(delete(EditionSourceRecord))
    for index, left in enumerate(candidates):
        for right in candidates[index + 1 :]:
            exact = _exact_match(left, right)
            conflicts = hard_conflicts(left, right)
            score, evidence = fuzzy_score(left, right)
            if exact:
                union.union(left.logical_key, right.logical_key)
                status, confidence = "auto_merge", 1.0
                evidence["exact_match"] = exact
            elif conflicts:
                status, confidence = "blocked", score
            elif score >= 0.92:
                union.union(left.logical_key, right.logical_key)
                status, confidence = "auto_merge", score
            elif score >= 0.82:
                status, confidence = "review", score
            else:
                continue
            session.add(
                EditionMergeProposal(
                    left_source_record_id=min(left.record.id, right.record.id),
                    right_source_record_id=max(left.record.id, right.record.id),
                    confidence=confidence,
                    status=status,
                    evidence_json=evidence,
                    conflicts_json=conflicts,
                )
            )
    groups: dict[str, list[EditionCandidate]] = {}
    for candidate in candidates:
        groups.setdefault(union.find(candidate.logical_key), []).append(candidate)
    source_priority = {"wikidata": 0, "openlibrary": 1, "google_books": 2}
    active_edition_ids: set[int] = set()
    for members in groups.values():
        members.sort(
            key=lambda candidate: (
                source_priority.get(candidate.record.source, 9),
                candidate.logical_key,
            )
        )
        logical_keys = sorted(member.logical_key for member in members)
        cluster_key = hashlib.sha256("\n".join(logical_keys).encode()).hexdigest()
        preferred = members[0]
        edition = session.scalar(select(Edition).where(Edition.cluster_key == cluster_key))
        if edition is None:
            edition = Edition(
                cluster_key=cluster_key,
                title=preferred.title,
                normalized_title=preferred.normalized_title,
                review_status="unreviewed",
                overall_confidence=0.7,
                merge_method="singleton",
                identifier_issues=[],
            )
            session.add(edition)
            session.flush()
        active_edition_ids.add(edition.id)
        edition.title = preferred.title
        edition.subtitle = preferred.subtitle
        edition.normalized_title = preferred.normalized_title
        edition.language = next((item.language for item in members if item.language), None)
        edition.publication_date_raw = next(
            (item.publication_date_raw for item in members if item.publication_date_raw),
            None,
        )
        edition.publication_year = next(
            (item.publication_year for item in members if item.publication_year), None
        )
        edition.publisher = next((item.publisher for item in members if item.publisher), None)
        edition.page_count = next((item.page_count for item in members if item.page_count), None)
        edition.isbn10 = next(iter(sorted(set().union(*(item.isbn10 for item in members)))), None)
        edition.isbn13 = next(iter(sorted(set().union(*(item.isbn13 for item in members)))), None)
        edition.oclc = next(iter(sorted(set().union(*(item.oclc for item in members)))), None)
        edition.doi = next(iter(sorted(set().union(*(item.doi for item in members)))), None)
        edition.wikidata_qid = next(
            (item.record.source_entity_id for item in members if item.record.source == "wikidata"),
            None,
        )
        edition.openlibrary_edition_id = next(
            (
                item.record.source_entity_id
                for item in members
                if item.record.source == "openlibrary"
            ),
            None,
        )
        edition.google_books_id = next(
            (
                item.record.source_entity_id
                for item in members
                if item.record.source == "google_books"
            ),
            None,
        )
        edition.review_status = "auto_accepted" if len(members) > 1 else "unreviewed"
        edition.overall_confidence = 1.0 if len(members) > 1 else 0.7
        edition.merge_method = "exact_or_fuzzy" if len(members) > 1 else "singleton"
        edition.identifier_issues = [
            {"source_record_id": item.record.id, **issue}
            for item in members
            for issue in item.identifier_issues
        ]
        for member in members:
            link = session.get(EditionSourceRecord, member.record.id)
            if link is None:
                link = EditionSourceRecord(source_record_id=member.record.id)
                session.add(link)
            link.edition_id = edition.id

    stale_edition_ids = set(session.scalars(select(Edition.id)).all()) - active_edition_ids
    if stale_edition_ids:
        rated_stale_ids = set(
            session.scalars(
                select(RetailRatingObservation.edition_id).where(
                    RetailRatingObservation.edition_id.in_(stale_edition_ids)
                )
            ).all()
        )
        if rated_stale_ids:
            raise ValueError(
                "Cannot remove stale editions with retail rating observations: "
                f"{sorted(rated_stale_ids)}"
            )
        session.execute(delete(Contribution).where(Contribution.edition_id.in_(stale_edition_ids)))
        session.execute(delete(Edition).where(Edition.id.in_(stale_edition_ids)))
    session.commit()
    return len(groups), len(session.scalars(select(EditionMergeProposal)).all())
