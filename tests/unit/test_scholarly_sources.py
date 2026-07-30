from datetime import UTC, datetime
from pathlib import Path

import httpx
import respx
from sqlalchemy import select
from sqlalchemy.orm import Session

from nobel_books.adapters.crossref import CrossrefAdapter
from nobel_books.adapters.openalex import OpenAlexAdapter
from nobel_books.cache import RawResponseCache
from nobel_books.db import make_engine, upgrade_database
from nobel_books.models.database import (
    Edition,
    ExternalIdentity,
    Laureate,
    SourceFetch,
    SourceRecord,
)
from nobel_books.pipeline.scholarly import (
    discover_openalex,
    enrich_crossref,
    write_source_limitations,
)


@respx.mock
def test_openalex_identifier_books_xpac_and_crossref_doi_enrichment(tmp_path: Path) -> None:
    author_route = respx.get("https://alex.example/authors").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "https://openalex.org/A1",
                        "orcid": "https://orcid.org/0000-0001",
                        "display_name": "Example Author",
                    }
                ],
                "meta": {},
            },
        )
    )
    works_route = respx.get("https://alex.example/works").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": "https://openalex.org/W1",
                            "type": "book",
                            "title": "Technical Monograph",
                            "doi": "https://doi.org/10.1000/book",
                            "publication_year": 2020,
                        }
                    ],
                    "meta": {"next_cursor": "next"},
                },
            ),
            httpx.Response(200, json={"results": [], "meta": {"next_cursor": None}}),
        ]
    )
    types_route = respx.get("https://crossref.example/types").mock(
        return_value=httpx.Response(
            200,
            json={
                "message": {
                    "items": [
                        {"id": "monograph"},
                        {"id": "edited-book"},
                        {"id": "journal-article"},
                    ]
                }
            },
        )
    )
    doi_route = respx.get("https://crossref.example/works/10.1000%2Fbook").mock(
        return_value=httpx.Response(
            200,
            json={
                "message": {
                    "DOI": "10.1000/book",
                    "type": "monograph",
                    "title": ["Technical Monograph"],
                    "publisher": "Fixture Press",
                }
            },
        )
    )
    database_url = f"sqlite:///{tmp_path / 'test.sqlite3'}"
    upgrade_database(database_url)
    engine = make_engine(database_url)
    now = datetime.now(UTC)
    with Session(engine) as session:
        laureate = Laureate(
            nobel_api_id="1",
            display_name="Example Author",
            created_at=now,
            updated_at=now,
        )
        session.add(laureate)
        session.flush()
        session.add(
            ExternalIdentity(
                laureate_id=laureate.id,
                scheme="orcid",
                value="0000-0001",
                canonical_url="https://orcid.org/0000-0001",
                resolution_status="verified",
                confidence=1.0,
                evidence_json={"method": "fixture"},
            )
        )
        edition = Edition(
            cluster_key="edition",
            title="Technical Monograph",
            normalized_title="technical monograph",
            doi="10.1000/book",
            review_status="unreviewed",
            overall_confidence=0.8,
            merge_method="singleton",
            identifier_issues=[],
        )
        session.add(edition)
        session.commit()
        clocks = iter(range(100))
        openalex = discover_openalex(
            session,
            OpenAlexAdapter(
                "https://alex.example",
                "test@example.org",
                api_key="secret-key",
                include_xpac=True,
                requests_per_second=1000,
                sleeper=lambda _: None,
                clock=lambda: float(next(clocks)),
            ),
            RawResponseCache(tmp_path / "cache"),
            max_authors=1,
        )
        crossref = enrich_crossref(
            session,
            CrossrefAdapter(
                "https://crossref.example",
                "test@example.org",
                user_agent="fixture-agent",
                requests_per_second=1000,
                sleeper=lambda _: None,
                clock=lambda: float(next(clocks)),
            ),
            RawResponseCache(tmp_path / "cache"),
        )
        records = session.scalars(
            select(SourceRecord).where(SourceRecord.source.in_(("openalex", "crossref")))
        ).all()
        openalex_urls = session.scalars(
            select(SourceFetch.request_url).where(SourceFetch.source == "openalex")
        ).all()

    assert author_route.call_count == 1
    assert works_route.call_count == 2
    assert "type%3Abook" in str(works_route.calls[0].request.url)
    assert works_route.calls[0].request.url.params["include_xpac"] == "true"
    assert types_route.call_count == 1
    assert doi_route.call_count == 1
    assert doi_route.calls[0].request.url.params["mailto"] == "test@example.org"
    assert openalex.authors_resolved == 1
    assert openalex.openalex_books == 1
    assert crossref.crossref_book_types == 2
    assert crossref.crossref_dois == 1
    assert {(record.source, record.source_entity_id) for record in records} == {
        ("openalex", "W1"),
        ("crossref", "10.1000/book"),
    }
    assert all("secret-key" not in url for url in openalex_urls)
    limitations = tmp_path / "limitations.json"
    write_source_limitations(limitations, include_xpac=True)
    assert "lower average data quality" in limitations.read_text(encoding="utf-8")
    engine.dispose()
