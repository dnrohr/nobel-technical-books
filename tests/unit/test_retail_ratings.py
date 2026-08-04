import csv
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_review_exports import seed

from nobel_books.db import make_engine, upgrade_database
from nobel_books.models.database import Edition, RetailRatingObservation
from nobel_books.review.ratings import (
    amazon_search_url,
    export_rating_template,
    import_ratings,
)


def _write_rating(path: Path, **overrides: object) -> None:
    row: dict[str, object] = {
        "edition_id": 1,
        "isbn": "9780000000002",
        "retailer": "amazon",
        "marketplace": "www.amazon.com",
        "product_id": "B012345678",
        "average_rating": 4.6,
        "review_count": 127,
        "observed_at": "2026-07-30T12:00:00+00:00",
        "source_url": "https://www.amazon.com/dp/B012345678",
        "match_confidence": 1.0,
        "reviewer": "Tester",
    }
    row.update(overrides)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row), lineterminator="\n")
        writer.writeheader()
        writer.writerow(row)


def test_rating_template_and_idempotent_import(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'ratings.sqlite3'}"
    upgrade_database(database_url)
    engine = make_engine(database_url)
    template = tmp_path / "template.csv"
    completed = tmp_path / "completed.csv"
    with Session(engine) as session:
        seed(session)
        edition = session.scalar(select(Edition))
        assert edition is not None
        assert amazon_search_url(edition).endswith("s?k=9780000000002")
        assert export_rating_template(session, template) == 1
        template_row = next(csv.DictReader(template.open(encoding="utf-8", newline="")))
        assert template_row["laureate_name"] == "Example Author"
        assert template_row["canonical_work_title"] == "Theory of Example Physics"
        assert template_row["edition_title"] == "Theory of Example Physics"
        _write_rating(completed, edition_id=edition.id)
        assert import_ratings(session, completed) == 1
        assert import_ratings(session, completed) == 1
        observations = session.scalars(select(RetailRatingObservation)).all()

    assert len(observations) == 1
    assert observations[0].average_rating == 4.6
    assert observations[0].review_count == 127
    assert observations[0].observed_at == datetime(2026, 7, 30, 12)
    engine.dispose()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("average_rating", 5.1, "rating must be"),
        ("review_count", -1, "cannot be negative"),
        ("match_confidence", 1.1, "match_confidence"),
        ("source_url", "https://example.com/book", "must match marketplace"),
        ("retailer", "other", "must be amazon"),
    ],
)
def test_rating_import_rejects_unreviewable_rows(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    database_url = f"sqlite:///{tmp_path / f'{field}.sqlite3'}"
    upgrade_database(database_url)
    engine = make_engine(database_url)
    path = tmp_path / f"{field}.csv"
    with Session(engine) as session:
        seed(session)
        _write_rating(path, **{field: value})
        with pytest.raises(ValueError, match=message):
            import_ratings(session, path)
    engine.dispose()
