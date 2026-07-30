from datetime import UTC, datetime
from pathlib import Path

import httpx
import respx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nobel_books.adapters.google_books import GoogleBooksAdapter
from nobel_books.cache import RawResponseCache
from nobel_books.db import make_engine, upgrade_database
from nobel_books.models.database import (
    Assertion,
    DiscoveryQuery,
    Laureate,
    SourceFetch,
    SourceRecord,
)
from nobel_books.pipeline.google_books import (
    author_query_variants,
    discover_google_books,
)


@respx.mock
def test_controlled_queries_pagination_deduplication_and_ambiguity(tmp_path: Path) -> None:
    def response(request: httpx.Request) -> httpx.Response:
        query = request.url.params["q"]
        start = int(request.url.params["startIndex"])
        assert request.url.params["printType"] == "books"
        assert int(request.url.params["maxResults"]) <= 40
        if start == 0:
            items = [
                {
                    "id": "VOL1",
                    "volumeInfo": {
                        "title": "Technical Book",
                        "authors": ["Marie Curie"],
                        "publishedDate": "1910",
                        "industryIdentifiers": [{"type": "ISBN_13", "identifier": "9780000000002"}],
                    },
                }
            ]
        else:
            items = [
                {
                    "id": "VOL2",
                    "volumeInfo": {
                        "title": f"Ambiguous Result for {query}",
                        "authors": ["Different Person"],
                        "publisher": "Fixture Press",
                    },
                }
            ]
        return httpx.Response(200, json={"totalItems": 2, "items": items})

    route = respx.get("https://books.example/volumes").mock(side_effect=response)
    database_url = f"sqlite:///{tmp_path / 'test.sqlite3'}"
    upgrade_database(database_url)
    engine = make_engine(database_url)
    now = datetime.now(UTC)
    with Session(engine) as session:
        laureate = Laureate(
            nobel_api_id="1",
            display_name="Marie Sklodowska Curie",
            given_name="Marie Sklodowska",
            family_name="Curie",
            created_at=now,
            updated_at=now,
        )
        session.add(laureate)
        session.commit()
        variants = author_query_variants(laureate)
        clock_values = iter(range(100))
        summary = discover_google_books(
            session,
            GoogleBooksAdapter(
                "https://books.example",
                "fixture-agent",
                api_key="secret-key",
                requests_per_second=1000,
                page_size=50,
                max_results_per_query=2,
                sleeper=lambda _: None,
                clock=lambda: float(next(clock_values)),
            ),
            RawResponseCache(tmp_path / "cache"),
            max_authors=1,
        )
        query_count = session.scalar(select(func.count()).select_from(DiscoveryQuery))
        records = session.scalars(
            select(SourceRecord).where(SourceRecord.source == "google_books")
        ).all()
        assertions = session.scalars(
            select(Assertion).join(SourceRecord).where(SourceRecord.source == "google_books")
        ).all()
        fetch_urls = session.scalars(
            select(SourceFetch.request_url).where(SourceFetch.source == "google_books")
        ).all()

    assert [variant.kind for variant in variants] == [
        "exact_full_name",
        "first_and_family",
        "initials_and_family",
    ]
    assert route.call_count == 6
    assert query_count == 3
    assert summary.volumes == 6
    assert summary.new_volumes == 2
    assert len(records) == 2
    assert summary.ambiguous_relationships == 3
    assert all("secret-key" not in url for url in fetch_urls)
    vol2 = next(record for record in records if record.source_entity_id == "VOL2")
    assert vol2.raw_json["relationship_status"] == "ambiguous"
    assert {
        assertion.predicate for assertion in assertions if assertion.source_record_id == vol2.id
    } >= {"title", "authors", "relationship_status", "query_variant"}
    assert len(list((tmp_path / "cache" / "google_books").glob("*.json"))) == 4
    engine.dispose()
