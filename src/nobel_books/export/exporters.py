"""CSV, JSON, Markdown, and coverage report exporters."""

import csv
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nobel_books.classification.classifier import _work_records
from nobel_books.models.database import (
    Assertion,
    CanonicalWork,
    Contribution,
    Edition,
    EditionSourceRecord,
    ExternalIdentity,
    IdentityResolution,
    Laureate,
    PipelineRun,
    PrizeAward,
    SourceFetch,
    SourceRecord,
)
from nobel_books.pipeline.scholarly import source_limitations_document


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(
            {
                field: " ".join(value.split()) if isinstance(value, str) else value
                for field, value in row.items()
            }
            for row in rows
        )


def _editions(session: Session, work_id: int) -> list[Edition]:
    return list(
        session.scalars(
            select(Edition)
            .where(Edition.canonical_work_id == work_id)
            .order_by(Edition.publication_year, Edition.title)
        ).all()
    )


def _record_sources(
    session: Session, work: CanonicalWork
) -> tuple[list[SourceRecord], list[str], list[str]]:
    records = _work_records(session, work)
    sources = sorted({record.source for record in records})
    urls = sorted({record.source_url for record in records if record.source_url})
    return records, sources, urls


def _prizes(session: Session, laureate_id: int) -> list[PrizeAward]:
    return list(
        session.scalars(
            select(PrizeAward)
            .where(PrizeAward.laureate_id == laureate_id)
            .order_by(PrizeAward.year, PrizeAward.category)
        ).all()
    )


def export_works_csv(session: Session, path: Path) -> int:
    rows: list[dict[str, object]] = []
    contributions = session.execute(
        select(Contribution, Laureate, CanonicalWork)
        .join(Laureate, Laureate.id == Contribution.laureate_id)
        .join(CanonicalWork, CanonicalWork.id == Contribution.canonical_work_id)
        .where(
            Contribution.review_status != "rejected",
            Laureate.is_organization.is_(False),
        )
        .order_by(Laureate.display_name, CanonicalWork.preferred_title)
    ).all()
    for contribution, laureate, work in contributions:
        records, sources, urls = _record_sources(session, work)
        if not records or not contribution.evidence_json:
            raise ValueError(f"Export work lacks evidence: {work.id}")
        editions = _editions(session, work.id)
        prizes = _prizes(session, laureate.id)
        co_contributions = session.execute(
            select(Contribution, Laureate)
            .join(Laureate, Laureate.id == Contribution.laureate_id)
            .where(
                Contribution.canonical_work_id == work.id,
                Contribution.laureate_id != laureate.id,
            )
        ).all()
        rows.append(
            {
                "laureate_name": laureate.display_name,
                "nobel_api_id": laureate.nobel_api_id,
                "prize_categories": "|".join(sorted({prize.category for prize in prizes})),
                "prize_years": "|".join(str(prize.year) for prize in prizes),
                "prize_subfields": "|".join(
                    sorted({prize.subfield for prize in prizes if prize.subfield})
                ),
                "award_summaries": "|".join(
                    prize.motivation for prize in prizes if prize.motivation
                ),
                "preferred_title": work.preferred_title,
                "original_title": work.original_title or "",
                "first_publication_year": work.first_publication_year or "",
                "role": contribution.role,
                "coauthors_or_coeditors": "|".join(
                    person.display_name for _, person in co_contributions
                ),
                "work_type": work.work_type,
                "technicality_score": work.technicality_score,
                "audience_level": work.audience_level or "",
                "review_status": contribution.review_status,
                "relationship_confidence": contribution.relationship_confidence,
                "overall_confidence": min(
                    contribution.relationship_confidence,
                    work.overall_confidence,
                    work.classification_confidence or 0,
                ),
                "edition_count": len(editions),
                "languages": "|".join(
                    sorted({edition.language for edition in editions if edition.language})
                ),
                "isbn13s": "|".join(
                    sorted({edition.isbn13 for edition in editions if edition.isbn13})
                ),
                "dois": "|".join(sorted({edition.doi for edition in editions if edition.doi})),
                "oclc_numbers": "|".join(
                    sorted({edition.oclc for edition in editions if edition.oclc})
                ),
                "wikidata_qid": next(
                    (record.source_entity_id for record in records if record.source == "wikidata"),
                    "",
                ),
                "openlibrary_work_id": next(
                    (
                        record.source_entity_id
                        for record in records
                        if record.source == "openlibrary" and record.source_entity_type == "work"
                    ),
                    "",
                ),
                "source_count": len(sources),
                "source_urls": "|".join(urls),
                "notes": work.classification_reason or "",
            }
        )
    fields = [
        "laureate_name",
        "nobel_api_id",
        "prize_categories",
        "prize_years",
        "prize_subfields",
        "award_summaries",
        "preferred_title",
        "original_title",
        "first_publication_year",
        "role",
        "coauthors_or_coeditors",
        "work_type",
        "technicality_score",
        "audience_level",
        "review_status",
        "relationship_confidence",
        "overall_confidence",
        "edition_count",
        "languages",
        "isbn13s",
        "dois",
        "oclc_numbers",
        "wikidata_qid",
        "openlibrary_work_id",
        "source_count",
        "source_urls",
        "notes",
    ]
    _write_csv(path, fields, rows)
    return len(rows)


def export_editions_csv(session: Session, path: Path) -> int:
    rows: list[dict[str, object]] = []
    editions = session.scalars(select(Edition).order_by(Edition.id)).all()
    for edition in editions:
        records = session.scalars(
            select(SourceRecord)
            .join(
                EditionSourceRecord,
                EditionSourceRecord.source_record_id == SourceRecord.id,
            )
            .where(EditionSourceRecord.edition_id == edition.id)
        ).all()
        if not records:
            raise ValueError(f"Export edition lacks evidence: {edition.id}")
        rows.append(
            {
                "canonical_work_id": edition.canonical_work_id or "",
                "edition_title": edition.title,
                "language": edition.language or "",
                "publication_date": edition.publication_date_raw or "",
                "publisher": edition.publisher or "",
                "edition_statement": edition.edition_statement or "",
                "format": edition.format or "",
                "isbn10": edition.isbn10 or "",
                "isbn13": edition.isbn13 or "",
                "doi": edition.doi or "",
                "oclc": edition.oclc or "",
                "source_ids": "|".join(
                    f"{record.source}:{record.source_entity_id}" for record in records
                ),
                "confidence": edition.overall_confidence,
                "source_urls": "|".join(
                    sorted(record.source_url for record in records if record.source_url)
                ),
            }
        )
    fields = (
        list(rows[0])
        if rows
        else [
            "canonical_work_id",
            "edition_title",
            "language",
            "publication_date",
            "publisher",
            "edition_statement",
            "format",
            "isbn10",
            "isbn13",
            "doi",
            "oclc",
            "source_ids",
            "confidence",
            "source_urls",
        ]
    )
    _write_csv(path, fields, rows)
    return len(rows)


def export_evidence_csv(session: Session, path: Path) -> int:
    rows = []
    assertions = session.execute(
        select(Assertion, SourceRecord, SourceFetch)
        .join(SourceRecord, SourceRecord.id == Assertion.source_record_id)
        .join(SourceFetch, SourceFetch.id == SourceRecord.source_fetch_id)
        .order_by(Assertion.id)
    ).all()
    for assertion, record, fetch in assertions:
        rows.append(
            {
                "target_record": f"{assertion.subject_type}:{assertion.subject_id}",
                "field": assertion.predicate,
                "asserted_value": json.dumps(
                    assertion.value_json, ensure_ascii=False, sort_keys=True
                ),
                "source": record.source,
                "source_entity_id": record.source_entity_id or "",
                "source_url": record.source_url or "",
                "retrieval_date": fetch.fetched_at.isoformat(),
                "reliability_class": assertion.reliability_class,
                "confidence": assertion.confidence,
                "is_selected": assertion.is_selected,
                "is_contradicted": assertion.is_contradicted,
            }
        )
    fields = (
        list(rows[0])
        if rows
        else [
            "target_record",
            "field",
            "asserted_value",
            "source",
            "source_entity_id",
            "source_url",
            "retrieval_date",
            "reliability_class",
            "confidence",
            "is_selected",
            "is_contradicted",
        ]
    )
    _write_csv(path, fields, rows)
    return len(rows)


def bibliography_document(session: Session) -> dict[str, object]:
    latest_run = session.scalar(select(PipelineRun).order_by(PipelineRun.id.desc()))
    laureate_items: list[dict[str, object]] = []
    laureates = session.scalars(
        select(Laureate).where(Laureate.is_organization.is_(False)).order_by(Laureate.display_name)
    ).all()
    for laureate in laureates:
        prizes = _prizes(session, laureate.id)
        identifiers: dict[str, list[str]] = defaultdict(list)
        for identity in session.scalars(
            select(ExternalIdentity).where(
                ExternalIdentity.laureate_id == laureate.id,
                ExternalIdentity.resolution_status == "verified",
            )
        ):
            identifiers[identity.scheme].append(identity.value)
        works = []
        contribution_rows = session.execute(
            select(Contribution, CanonicalWork)
            .join(CanonicalWork, CanonicalWork.id == Contribution.canonical_work_id)
            .where(
                Contribution.laureate_id == laureate.id,
                Contribution.review_status != "rejected",
            )
            .order_by(CanonicalWork.preferred_title)
        ).all()
        for contribution, work in contribution_rows:
            records, sources, urls = _record_sources(session, work)
            if not records:
                raise ValueError(f"JSON work lacks evidence: {work.id}")
            editions = _editions(session, work.id)
            works.append(
                {
                    "id": work.id,
                    "title": work.preferred_title,
                    "roles": [
                        {
                            "role": contribution.role,
                            "confidence": contribution.relationship_confidence,
                            "status": contribution.review_status,
                        }
                    ],
                    "classification": {
                        "type": work.work_type,
                        "technicality_score": work.technicality_score,
                        "audience": work.audience_level,
                        "confidence": work.classification_confidence,
                        "reason": work.classification_reason,
                    },
                    "editions": [
                        {
                            "id": edition.id,
                            "title": edition.title,
                            "language": edition.language,
                            "publication_date": edition.publication_date_raw,
                            "isbn10": edition.isbn10,
                            "isbn13": edition.isbn13,
                            "doi": edition.doi,
                            "oclc": edition.oclc,
                        }
                        for edition in editions
                    ],
                    "evidence": [
                        {
                            "source": record.source,
                            "source_entity_id": record.source_entity_id,
                            "url": record.source_url,
                        }
                        for record in records
                    ],
                    "source_count": len(sources),
                    "source_urls": urls,
                }
            )
        laureate_items.append(
            {
                "nobel_api_id": laureate.nobel_api_id,
                "name": laureate.display_name,
                "prizes": [
                    {
                        "category": prize.category,
                        "year": prize.year,
                        "subfield": prize.subfield,
                        "award_summary": prize.motivation,
                    }
                    for prize in prizes
                ],
                "identifiers": dict(identifiers),
                "coverage": {"work_count": len(works)},
                "works": works,
            }
        )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "pipeline_run": latest_run.id if latest_run else None,
        "limitations": {
            "release_status": (
                "Machine-generated research dataset; ambiguous and unreviewed "
                "records require human audit."
            ),
            "sources": source_limitations_document(include_xpac=False),
        },
        "laureates": laureate_items,
    }


def export_json(session: Session, path: Path) -> int:
    document = bibliography_document(session)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
        newline="\n",
    )
    return len(document["laureates"])  # type: ignore[arg-type]


def _markdown_section(work: CanonicalWork, role: str) -> str:
    if role in {"editor", "coeditor"}:
        return "Edited works"
    if work.work_type in {"memoir", "essays", "fiction"}:
        return "Memoir and essays"
    if work.work_type == "popular_science":
        return "Popular science"
    if (work.technicality_score or 0) >= 0.5:
        return "Technical works"
    return "Unresolved candidates"


def export_markdown(session: Session, path: Path) -> int:
    lines = [
        "# Nobel Laureate Books",
        "",
        "> Machine-generated research dataset. Ambiguous and unreviewed records",
        "> require human audit; source coverage is not comprehensive.",
        "",
    ]
    count = 0
    for category, heading in (
        ("physics", "Physics"),
        ("chemistry", "Chemistry"),
        ("medicine", "Physiology or Medicine"),
    ):
        lines.extend([f"## {heading}", ""])
        laureates = session.scalars(
            select(Laureate)
            .join(PrizeAward)
            .where(
                PrizeAward.category == category,
                Laureate.is_organization.is_(False),
            )
            .distinct()
            .order_by(Laureate.display_name)
        ).all()
        for laureate in laureates:
            lines.extend([f"### {laureate.display_name}", ""])
            grouped: dict[str, list[tuple[Contribution, CanonicalWork]]] = defaultdict(list)
            rows = session.execute(
                select(Contribution, CanonicalWork)
                .join(
                    CanonicalWork,
                    CanonicalWork.id == Contribution.canonical_work_id,
                )
                .where(
                    Contribution.laureate_id == laureate.id,
                    Contribution.review_status != "rejected",
                )
                .order_by(CanonicalWork.preferred_title)
            ).all()
            for contribution, work in rows:
                grouped[_markdown_section(work, contribution.role)].append((contribution, work))
            for section in (
                "Technical works",
                "Popular science",
                "Memoir and essays",
                "Edited works",
                "Unresolved candidates",
            ):
                lines.extend([f"#### {section}", ""])
                for contribution, work in grouped[section]:
                    _, sources, urls = _record_sources(session, work)
                    if not sources:
                        raise ValueError(f"Markdown work lacks evidence: {work.id}")
                    year = work.first_publication_year or "unknown year"
                    links = ", ".join(
                        f"[source {index + 1}]({url})" for index, url in enumerate(urls[:3])
                    )
                    lines.append(
                        f"- *{' '.join(work.preferred_title.split())}* ({year}); "
                        f"{contribution.role}; {work.work_type}; "
                        f"relationship confidence "
                        f"{contribution.relationship_confidence:.2f}"
                        + (f"; {links}" if links else "")
                    )
                    count += 1
                lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return count


def export_limitations(json_path: Path, markdown_path: Path) -> None:
    document = {
        "release_status": (
            "Machine-generated research dataset; ambiguous and unreviewed records "
            "require human audit."
        ),
        "source_limitations": source_limitations_document(include_xpac=False),
        "redistribution": (
            "Restricted or proprietary source metadata must not be redistributed "
            "outside its permitted use."
        ),
    }
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
        newline="\n",
    )
    lines = [
        "# Dataset limitations",
        "",
        str(document["release_status"]),
        "",
        "OpenAlex emphasizes scholarly books and is not comprehensive for memoirs, "
        "popular books, or older monographs. Crossref covers DOI-registered works and "
        "is used for corroboration rather than complete discovery.",
        "",
        str(document["redistribution"]),
        "",
    ]
    markdown_path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def coverage_document(
    session: Session, previous: dict[str, Any] | None = None
) -> dict[str, object]:
    category_counts: dict[str, int] = {
        str(row[0]): int(row[1])
        for row in session.execute(
            select(PrizeAward.category, func.count(func.distinct(PrizeAward.laureate_id))).group_by(
                PrizeAward.category
            )
        )
    }
    resolution_counts: dict[str, int] = {
        str(row[0]): int(row[1])
        for row in session.execute(
            select(IdentityResolution.status, func.count()).group_by(IdentityResolution.status)
        )
    }
    source_counts: dict[str, int] = {
        str(row[0]): int(row[1])
        for row in session.execute(
            select(SourceRecord.source, func.count()).group_by(SourceRecord.source)
        )
    }
    class_counts: dict[str, int] = {
        str(row[0]): int(row[1])
        for row in session.execute(
            select(CanonicalWork.work_type, func.count()).group_by(CanonicalWork.work_type)
        )
    }
    work_counts: dict[int, int] = {
        int(row[0]): int(row[1])
        for row in session.execute(
            select(Contribution.laureate_id, func.count()).group_by(Contribution.laureate_id)
        )
    }
    laureate_ids = session.scalars(select(Laureate.id)).all()
    zero = sum(1 for laureate_id in laureate_ids if work_counts.get(laureate_id, 0) == 0)
    one = sum(1 for count in work_counts.values() if count == 1)
    multiple = sum(1 for count in work_counts.values() if count > 1)
    review_counts: dict[str, int] = {
        str(row[0]): int(row[1])
        for row in session.execute(
            select(Contribution.review_status, func.count()).group_by(Contribution.review_status)
        )
    }
    technical_by_category_decade: Counter[str] = Counter()
    technical_rows = session.execute(
        select(CanonicalWork, PrizeAward)
        .join(Contribution, Contribution.canonical_work_id == CanonicalWork.id)
        .join(PrizeAward, PrizeAward.laureate_id == Contribution.laureate_id)
        .where(CanonicalWork.technicality_score >= 0.5)
    ).all()
    for work, award in technical_rows:
        year = work.first_publication_year
        decade = f"{year // 10 * 10}s" if year else "unknown"
        technical_by_category_decade[f"{award.category}:{decade}"] += 1
    snapshot: dict[str, object] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "laureates_by_category": category_counts,
        "unique_laureates": len(laureate_ids),
        "identity_resolution": resolution_counts,
        "laureate_work_distribution": {
            "zero": zero,
            "one": one,
            "multiple": multiple,
        },
        "verified_works": review_counts.get("verified", 0) + review_counts.get("auto_accepted", 0),
        "unreviewed_candidates": review_counts.get("needs_review", 0),
        "source_contribution_counts": source_counts,
        "duplicate_edition_clusters": session.scalar(
            select(func.count()).select_from(
                select(EditionSourceRecord.edition_id)
                .group_by(EditionSourceRecord.edition_id)
                .having(func.count() > 1)
                .subquery()
            )
        )
        or 0,
        "classification_distribution": class_counts,
        "technical_works_by_category_decade": dict(sorted(technical_by_category_decade.items())),
        "review_progress": review_counts,
        "failed_pipeline_runs": session.scalar(
            select(func.count()).select_from(PipelineRun).where(PipelineRun.status == "FAILED")
        )
        or 0,
    }
    numeric_keys = ("unique_laureates", "verified_works", "unreviewed_candidates")
    changes: dict[str, int] = {}
    for key in numeric_keys:
        current = snapshot[key]
        if not isinstance(current, int):
            raise TypeError(f"Coverage metric {key} is not numeric")
        prior = previous.get(key, 0) if previous else 0
        changes[key] = current - prior if isinstance(prior, int) else current
    snapshot["changes_from_prior_run"] = changes
    return snapshot


def export_coverage(session: Session, json_path: Path, markdown_path: Path) -> None:
    previous: dict[str, Any] | None = None
    if json_path.exists():
        loaded = json.loads(json_path.read_text(encoding="utf-8"))
        previous = loaded if isinstance(loaded, dict) else None
    document = coverage_document(session, previous)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
        newline="\n",
    )
    lines = ["# Coverage Report", ""]
    for key, value in document.items():
        lines.extend([f"## {key.replace('_', ' ').title()}", "", f"`{value}`", ""])
    markdown_path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def export_all(session: Session, output_dir: Path) -> dict[str, int]:
    export_limitations(output_dir / "limitations.json", output_dir / "LIMITATIONS.md")
    counts = {
        "works": export_works_csv(session, output_dir / "works.csv"),
        "editions": export_editions_csv(session, output_dir / "editions.csv"),
        "evidence": export_evidence_csv(session, output_dir / "evidence.csv"),
        "laureates": export_json(session, output_dir / "bibliography.json"),
        "markdown_entries": export_markdown(session, output_dir / "bibliography.md"),
    }
    export_coverage(
        session,
        output_dir / "coverage.json",
        output_dir / "coverage.md",
    )
    return counts
