import csv
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import respx
from sqlalchemy import select
from sqlalchemy.orm import Session

from nobel_books.adapters.openlibrary import OpenLibraryAdapter
from nobel_books.cache import RawResponseCache
from nobel_books.db import make_engine, upgrade_database
from nobel_books.models.database import (
    Assertion,
    ExternalIdentity,
    Laureate,
    SourceAuthorCandidate,
    SourceRecord,
)
from nobel_books.pipeline.openlibrary import (
    discover_openlibrary,
    export_openlibrary_identity_review,
)


def fixture(name: str) -> dict[str, object]:
    path = Path(__file__).parents[1] / "fixtures" / "openlibrary" / name
    return json.loads(path.read_text(encoding="utf-8"))


@respx.mock
def test_openlibrary_resolution_pagination_editions_and_review(tmp_path: Path) -> None:
    works = respx.get("https://open.example/authors/OLVERIFIEDA/works.json").mock(
        side_effect=[
            httpx.Response(200, json=fixture("works_1.json")),
            httpx.Response(200, json=fixture("works_2.json")),
        ]
    )
    respx.get("https://open.example/works/OLW1W/editions.json").mock(
        return_value=httpx.Response(200, json=fixture("editions_1.json"))
    )
    respx.get("https://open.example/works/OLW2W/editions.json").mock(
        return_value=httpx.Response(200, json=fixture("editions_2.json"))
    )
    search = respx.get("https://open.example/search/authors.json").mock(
        return_value=httpx.Response(200, json=fixture("author_search.json"))
    )
    database_url = f"sqlite:///{tmp_path / 'test.sqlite3'}"
    upgrade_database(database_url)
    engine = make_engine(database_url)
    now = datetime.now(UTC)
    with Session(engine) as session:
        verified = Laureate(
            nobel_api_id="1",
            display_name="Marie Curie",
            birth_date_raw="1867-11-07",
            death_date_raw="1934-07-04",
            created_at=now,
            updated_at=now,
        )
        unresolved = Laureate(
            nobel_api_id="2",
            display_name="Ada Example",
            birth_date_raw="1900-01-01",
            created_at=now,
            updated_at=now,
        )
        session.add_all([verified, unresolved])
        session.flush()
        session.add(
            ExternalIdentity(
                laureate_id=verified.id,
                scheme="openlibrary",
                value="OLVERIFIEDA",
                canonical_url="https://openlibrary.org/authors/OLVERIFIEDA",
                resolution_status="verified",
                confidence=1.0,
                evidence_json={"method": "fixture"},
            )
        )
        session.commit()
        clock_values = iter(range(20))
        adapter = OpenLibraryAdapter(
            "https://open.example",
            "fixture-agent test@example.org",
            requests_per_second=1000,
            page_size=1,
            sleeper=lambda _: None,
            clock=lambda: float(next(clock_values)),
        )
        summary = discover_openlibrary(
            session,
            adapter,
            RawResponseCache(tmp_path / "cache"),
            max_authors=2,
        )
        records = session.scalars(
            select(SourceRecord).where(SourceRecord.source == "openlibrary")
        ).all()
        assertions = session.scalars(
            select(Assertion).join(SourceRecord).where(SourceRecord.source == "openlibrary")
        ).all()
        candidates = session.scalars(
            select(SourceAuthorCandidate).order_by(SourceAuthorCandidate.status)
        ).all()
        review_path = tmp_path / "review.csv"
        review_count = export_openlibrary_identity_review(session, review_path)

    assert works.call_count == 2
    assert search.call_count == 1
    assert summary.authors_verified == 1
    assert summary.candidates_for_review == 1
    assert summary.works == 2
    assert summary.editions == 2
    assert {record.source_entity_type for record in records} == {"work", "edition"}
    edition_records = [record for record in records if record.source_entity_type == "edition"]
    assert {record.raw_json["work_id"] for record in edition_records} == {"OLW1W", "OLW2W"}
    for record in records:
        assert set(record.raw_json) == {
            assertion.predicate
            for assertion in assertions
            if assertion.source_record_id == record.id
        }
    assert [(candidate.status, candidate.confidence) for candidate in candidates] == [
        ("review", 0.0),
        ("verified", 1.0),
    ]
    assert review_count == 1
    with review_path.open(encoding="utf-8", newline="") as handle:
        assert next(csv.DictReader(handle))["openlibrary_author_id"] == "OLFALSEA"
    assert len(list((tmp_path / "cache" / "openlibrary").glob("*.json"))) == 5
    engine.dispose()
