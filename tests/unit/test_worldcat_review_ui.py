from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_review_exports import seed

from nobel_books.adapters.worldcat import WorldCatAdapter
from nobel_books.config import ConfigurationError
from nobel_books.db import make_engine, upgrade_database
from nobel_books.models.database import Edition, ManualOverride, RetailRatingObservation
from nobel_books.review.web import create_review_app


def test_worldcat_is_disabled_without_credentials() -> None:
    with pytest.raises(ConfigurationError):
        WorldCatAdapter("https://americas.discovery.api.oclc.org", None)


@respx.mock
def test_worldcat_uses_v2_json_and_bearer_token() -> None:
    route = respx.get("https://americas.discovery.api.oclc.org/worldcat/search/v2/bibs").mock(
        return_value=httpx.Response(
            200,
            json={
                "numberOfRecords": 1,
                "briefRecords": [{"oclcNumber": "123", "title": "Example"}],
            },
        )
    )
    adapter = WorldCatAdapter(
        "https://americas.discovery.api.oclc.org",
        "secret-token",
        requests_per_second=100,
    )

    response = adapter.search("au:Example")

    assert response.number_of_records == 1
    assert route.calls[0].request.headers["Authorization"] == "Bearer secret-token"
    assert "secret-token" not in str(route.calls[0].request.url)


def test_review_ui_writes_standard_manual_override(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'ui.sqlite3'}"
    upgrade_database(database_url)
    engine = make_engine(database_url)
    with Session(engine) as session:
        contribution = seed(session)
        edition = session.scalar(select(Edition))
        assert edition is not None
        session.add(
            RetailRatingObservation(
                edition_id=edition.id,
                retailer="amazon",
                marketplace="www.amazon.com",
                product_id="B012345678",
                average_rating=4.6,
                review_count=127,
                observed_at=datetime(2026, 7, 30, tzinfo=UTC),
                source_url="https://www.amazon.com/dp/B012345678",
                match_confidence=1.0,
                reviewer="Tester",
            )
        )
        session.commit()
        key = f"1::work-key::{contribution.role}"

    client = TestClient(create_review_app(engine))
    page = client.get("/")
    assert page.status_code == 200
    assert "Nobel Books Explorer" in page.text
    assert client.get("/api/stats").json()["laureates"] == 1
    listing = client.get("/api/laureates", params={"award_year": 1950}).json()
    assert listing["total"] == 1
    assert listing["items"][0]["prizes"][0]["subfield"] == "theoretical physics"
    assert client.get("/api/laureates", params={"q": "Theory of Example"}).json()["total"] == 1
    assert (
        client.get(
            "/api/laureates", params={"award_year_from": 1949, "award_year_to": 1951}
        ).json()["total"]
        == 1
    )
    assert (
        client.get(
            "/api/laureates",
            params={"publication_year_from": 1900, "publication_year_to": 1920},
        ).json()["total"]
        == 1
    )
    assert client.get("/api/laureates", params={"edition_count": "one"}).json()["total"] == 1
    assert client.get("/api/laureates", params={"edition_count": "multiple"}).json()["total"] == 0
    assert client.get("/api/laureates", params={"source": "wikidata"}).json()["total"] == 1
    assert client.get("/api/laureates", params={"source": "google_books"}).json()["total"] == 0
    assert client.get("/api/laureates", params={"min_confidence": 0.8}).json()["total"] == 0
    filter_data = client.get("/api/filters").json()
    assert filter_data["publication_years"] == {"min": 1910, "max": 1910}
    assert filter_data["edition_counts"]["max"] == 1
    detail = client.get("/api/laureates/1").json()
    assert detail["work_total"] == 1
    assert detail["work_offset"] == 0
    assert detail["works_truncated"] is False
    next_page = client.get(
        "/api/laureates/1", params={"work_limit": 1, "work_offset": 1}
    ).json()
    assert next_page["works"] == []
    assert next_page["work_total"] == 1
    assert next_page["work_offset"] == 1
    assert detail["prizes"][0]["year"] == 1950
    assert detail["prizes"][0]["award_summary"].startswith("for foundational")
    assert detail["works"][0]["sources"][0]["source"] == "wikidata"
    assert detail["works"][0]["editions"][0]["isbn13"] == "9780000000002"
    rating = detail["works"][0]["editions"][0]["amazon_rating"]
    assert rating["stars"] == 4.6
    assert rating["review_count"] == 127

    queue = client.get("/api/review")
    assert queue.status_code == 200
    assert queue.json()[0]["review_key"] == key

    response = client.post(
        "/api/decision",
        json={
            "review_key": key,
            "decision": "accept",
            "reason": "Reviewed in local UI",
            "reviewer": "Tester",
        },
    )

    assert response.status_code == 200
    assert response.json()["target_type"] == "contribution"
    with Session(engine) as session:
        override = session.scalar(select(ManualOverride))
        assert override is not None
        assert override.action == "include"
        assert override.reason == "Reviewed in local UI"
    engine.dispose()
