import csv
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import respx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nobel_books.adapters.wikidata import WikidataIdentityAdapter
from nobel_books.cache import RawResponseCache
from nobel_books.db import make_engine, upgrade_database
from nobel_books.models.database import (
    ExternalIdentity,
    IdentityResolution,
    Laureate,
    PersonNameVariant,
    SourceFetch,
)
from nobel_books.pipeline.identities import export_identity_review, resolve_identities


def fixture() -> dict[str, object]:
    path = Path(__file__).parents[1] / "fixtures" / "wikidata" / "identity_results.json"
    return json.loads(path.read_text(encoding="utf-8"))


@respx.mock
def test_exact_ambiguous_and_unresolved_identity_results(tmp_path: Path) -> None:
    route = respx.get("https://query.example/sparql").mock(
        return_value=httpx.Response(200, json=fixture())
    )
    database_url = f"sqlite:///{tmp_path / 'test.sqlite3'}"
    upgrade_database(database_url)
    engine = make_engine(database_url)
    now = datetime.now(UTC)
    with Session(engine) as session:
        session.add_all(
            [
                Laureate(
                    nobel_api_id=str(number),
                    display_name=name,
                    created_at=now,
                    updated_at=now,
                )
                for number, name in (
                    (1, "Marie Curie"),
                    (2, "Nobody Example"),
                    (3, "Ambiguous Person"),
                )
            ]
        )
        session.commit()
        summary = resolve_identities(
            session,
            WikidataIdentityAdapter("https://query.example/sparql", "test-agent", batch_size=10),
            RawResponseCache(tmp_path / "cache"),
        )
        rerun = resolve_identities(
            session,
            WikidataIdentityAdapter("https://query.example/sparql", "test-agent", batch_size=10),
            RawResponseCache(tmp_path / "cache"),
        )
        statuses = dict(
            session.execute(
                select(Laureate.nobel_api_id, IdentityResolution.status).join(IdentityResolution)
            ).all()
        )
        identity_count = session.scalar(select(func.count()).select_from(ExternalIdentity))
        resolution_count = session.scalar(select(func.count()).select_from(IdentityResolution))
        fetch_count = session.scalar(select(func.count()).select_from(SourceFetch))
        variants = session.scalars(select(PersonNameVariant)).all()
        report = tmp_path / "review.csv"
        report_count = export_identity_review(session, report)

    assert route.call_count == 2
    assert route.calls[0].request.headers["user-agent"] == "test-agent"
    assert summary.verified == 1
    assert rerun == summary
    assert summary.unresolved == 1
    assert summary.ambiguous == 1
    assert statuses == {"1": "verified", "2": "unresolved", "3": "ambiguous"}
    assert identity_count == 3
    assert resolution_count == 3
    assert fetch_count == 1
    assert {variant.name for variant in variants} == {
        "Marie Curie",
        "Marie Skłodowska-Curie",
    }
    assert report_count == 2
    with report.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert {row["status"] for row in rows} == {"unresolved", "ambiguous"}
    assert len(list((tmp_path / "cache" / "wikidata").glob("*.json"))) == 1
    engine.dispose()
