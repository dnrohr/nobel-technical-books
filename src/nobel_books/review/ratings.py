"""Reviewed retailer-rating CSV workflow; no retailer pages are scraped."""

import csv
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus, urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from nobel_books.models.database import (
    CanonicalWork,
    Contribution,
    Edition,
    Laureate,
    RetailRatingObservation,
)

RATING_FIELDS = [
    "laureate_name",
    "nobel_api_id",
    "canonical_work_title",
    "edition_title",
    "publication_year",
    "edition_id",
    "isbn",
    "retailer",
    "marketplace",
    "product_id",
    "average_rating",
    "review_count",
    "observed_at",
    "source_url",
    "match_confidence",
    "reviewer",
]


def amazon_search_url(edition: Edition, marketplace: str = "www.amazon.com") -> str:
    """Create a non-affiliate Amazon search link from the strongest edition identifier."""

    query = edition.isbn13 or edition.isbn10 or edition.title
    return f"https://{marketplace}/s?k={quote_plus(query)}"


def export_rating_template(session: Session, path: Path) -> int:
    """Export ISBN-bearing editions as an empty, human-reviewable ratings template."""

    editions = session.scalars(
        select(Edition)
        .where((Edition.isbn13.is_not(None)) | (Edition.isbn10.is_not(None)))
        .order_by(Edition.title, Edition.id)
    ).all()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RATING_FIELDS, lineterminator="\n")
        writer.writeheader()
        for edition in editions:
            work = (
                session.get(CanonicalWork, edition.canonical_work_id)
                if edition.canonical_work_id is not None
                else None
            )
            laureates = (
                session.execute(
                    select(Laureate.display_name, Laureate.nobel_api_id)
                    .join(Contribution, Contribution.laureate_id == Laureate.id)
                    .where(Contribution.canonical_work_id == work.id)
                    .distinct()
                    .order_by(Laureate.display_name)
                ).all()
                if work is not None
                else []
            )
            writer.writerow(
                {
                    "laureate_name": " | ".join(name for name, _ in laureates),
                    "nobel_api_id": " | ".join(nobel_id for _, nobel_id in laureates),
                    "canonical_work_title": work.preferred_title if work else "",
                    "edition_title": edition.title,
                    "publication_year": edition.publication_year or "",
                    "edition_id": edition.id,
                    "isbn": edition.isbn13 or edition.isbn10 or "",
                    "retailer": "amazon",
                    "marketplace": "www.amazon.com",
                    "source_url": amazon_search_url(edition),
                }
            )
    return len(editions)


def _edition_for_row(session: Session, row: dict[str, str]) -> Edition:
    raw_id = row.get("edition_id", "").strip()
    isbn = row.get("isbn", "").replace("-", "").strip()
    edition = session.get(Edition, int(raw_id)) if raw_id else None
    if edition is None and isbn:
        edition = session.scalar(
            select(Edition).where((Edition.isbn13 == isbn) | (Edition.isbn10 == isbn))
        )
    if edition is None:
        raise ValueError(f"No edition matches edition_id={raw_id!r}, isbn={isbn!r}")
    if raw_id and isbn and isbn not in {edition.isbn10, edition.isbn13}:
        raise ValueError(f"Edition {edition.id} does not have ISBN {isbn}")
    return edition


def import_ratings(session: Session, path: Path) -> int:
    """Validate and import manually reviewed Amazon rating observations."""

    imported = 0
    with path.open(encoding="utf-8", newline="") as handle:
        for line_number, row in enumerate(csv.DictReader(handle), start=2):
            product_id = row.get("product_id", "").strip().upper()
            if not product_id:
                continue
            try:
                edition = _edition_for_row(session, row)
                retailer = row.get("retailer", "amazon").strip().casefold()
                marketplace = row.get("marketplace", "").strip().casefold()
                rating = float(row.get("average_rating", ""))
                review_count = int(row.get("review_count", ""))
                observed_at = datetime.fromisoformat(
                    row.get("observed_at", "").strip().replace("Z", "+00:00")
                )
                source_url = row.get("source_url", "").strip()
                match_confidence = float(row.get("match_confidence", ""))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid ratings row {line_number}: {exc}") from exc
            if retailer != "amazon":
                raise ValueError(f"Invalid ratings row {line_number}: retailer must be amazon")
            if not marketplace.startswith("www.amazon."):
                raise ValueError(f"Invalid ratings row {line_number}: invalid Amazon marketplace")
            if not (0 <= rating <= 5):
                raise ValueError(f"Invalid ratings row {line_number}: rating must be from 0 to 5")
            if review_count < 0:
                raise ValueError(
                    f"Invalid ratings row {line_number}: review_count cannot be negative"
                )
            if not (0 <= match_confidence <= 1):
                raise ValueError(
                    f"Invalid ratings row {line_number}: match_confidence must be from 0 to 1"
                )
            parsed_url = urlparse(source_url)
            if parsed_url.scheme != "https" or parsed_url.hostname != marketplace:
                raise ValueError(
                    f"Invalid ratings row {line_number}: source_url must match marketplace"
                )
            existing = session.scalar(
                select(RetailRatingObservation).where(
                    RetailRatingObservation.edition_id == edition.id,
                    RetailRatingObservation.retailer == retailer,
                    RetailRatingObservation.marketplace == marketplace,
                    RetailRatingObservation.product_id == product_id,
                    RetailRatingObservation.observed_at == observed_at,
                )
            )
            if existing is None:
                existing = RetailRatingObservation(
                    edition_id=edition.id,
                    retailer=retailer,
                    marketplace=marketplace,
                    product_id=product_id,
                    observed_at=observed_at,
                )
                session.add(existing)
            existing.average_rating = rating
            existing.review_count = review_count
            existing.source_url = source_url
            existing.match_confidence = match_confidence
            existing.reviewer = row.get("reviewer", "").strip() or None
            imported += 1
    session.commit()
    return imported
