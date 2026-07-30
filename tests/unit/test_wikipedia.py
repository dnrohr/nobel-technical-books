from datetime import UTC, datetime
from pathlib import Path

import httpx
import respx
from sqlalchemy import select
from sqlalchemy.orm import Session

from nobel_books.adapters.wikipedia import WikipediaAdapter
from nobel_books.cache import RawResponseCache
from nobel_books.db import make_engine, upgrade_database
from nobel_books.models.database import Assertion, Laureate, SourceRecord
from nobel_books.pipeline.wikipedia import (
    discover_wikipedia,
    parse_bibliography_wikitext,
)


def test_wikitext_parser_handles_citations_lists_and_duplicates() -> None:
    candidates = parse_bibliography_wikitext(
        """
* {{cite book | title=Technical Treatise | year=1910 | publisher=Science Press | isbn=123}}
* ''Popular Essays'' (1920)
* [[Linked Book]] — 1930
* {{cite journal | title=Not a book}}
* ''Popular Essays'' (1920)
plain text
"""
    )
    assert [(item.title, item.year) for item in candidates] == [
        ("Technical Treatise", 1910),
        ("Popular Essays", 1920),
        ("Linked Book", 1930),
    ]


@respx.mock
def test_only_relevant_sections_revision_provenance_and_failure_isolation(
    tmp_path: Path,
) -> None:
    def response(request: httpx.Request) -> httpx.Response:
        page = request.url.params["page"]
        section = request.url.params.get("section")
        if page == "Broken Person":
            return httpx.Response(200, content=b"not json")
        if section is None:
            return httpx.Response(
                200,
                json={
                    "parse": {
                        "title": "Example Person",
                        "pageid": 42,
                        "revid": 123,
                        "sections": [
                            {"index": "1", "line": "Biography"},
                            {"index": "2", "line": "Selected works"},
                        ],
                    }
                },
            )
        assert section == "2"
        return httpx.Response(
            200,
            json={
                "parse": {
                    "title": "Example Person",
                    "pageid": 42,
                    "revid": 124,
                    "wikitext": (
                        "* {{cite book | title=Technical Treatise | year=1910}}\n"
                        "* ''Popular Essays'' (1920)"
                    ),
                }
            },
        )

    route = respx.get("https://wiki.example/w/api.php").mock(side_effect=response)
    database_url = f"sqlite:///{tmp_path / 'test.sqlite3'}"
    upgrade_database(database_url)
    engine = make_engine(database_url)
    now = datetime.now(UTC)
    with Session(engine) as session:
        session.add_all(
            [
                Laureate(
                    nobel_api_id="1",
                    display_name="Example Person",
                    created_at=now,
                    updated_at=now,
                ),
                Laureate(
                    nobel_api_id="2",
                    display_name="Broken Person",
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        session.commit()
        clocks = iter(range(100))
        summary = discover_wikipedia(
            session,
            WikipediaAdapter(
                "https://wiki.example/w/api.php",
                "fixture-agent",
                requests_per_second=1000,
                sleeper=lambda _: None,
                clock=lambda: float(next(clocks)),
            ),
            RawResponseCache(tmp_path / "cache"),
            headings=["bibliography", "selected works"],
            max_authors=2,
        )
        records = session.scalars(
            select(SourceRecord).where(SourceRecord.source == "wikipedia")
        ).all()
        assertions = session.scalars(
            select(Assertion).join(SourceRecord).where(SourceRecord.source == "wikipedia")
        ).all()

    assert route.call_count == 3
    assert summary.pages_with_sections == 1
    assert summary.sections_fetched == 1
    assert summary.candidates == 2
    assert summary.failures == 1
    assert {record.raw_json["revision_id"] for record in records} == {124}
    assert {record.raw_json["section_index"] for record in records} == {"2"}
    assert all(record.raw_json["review_status"] == "needs_corroboration" for record in records)
    assert all(assertion.confidence == 0.35 for assertion in assertions)
    assert all(assertion.reliability_class == "D" for assertion in assertions)
    assert len(list((tmp_path / "cache" / "wikipedia").glob("*.json"))) == 2
    engine.dispose()
