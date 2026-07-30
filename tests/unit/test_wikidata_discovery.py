import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import httpx
import respx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nobel_books.adapters.wikidata import WikidataBookAdapter
from nobel_books.cache import RawResponseCache
from nobel_books.db import make_engine, upgrade_database
from nobel_books.models.database import (
    Assertion,
    ExternalIdentity,
    Laureate,
    SourceRecord,
)
from nobel_books.pipeline.discovery import discover_wikidata_candidates


def fixture() -> dict[str, object]:
    path = Path(__file__).parents[1] / "fixtures" / "wikidata" / "book_results.json"
    return json.loads(path.read_text(encoding="utf-8"))


@respx.mock
def test_discovery_preserves_roles_editions_and_field_provenance(tmp_path: Path) -> None:
    route = respx.get("https://query.example/sparql").mock(
        return_value=httpx.Response(200, json=fixture())
    )
    database_url = f"sqlite:///{tmp_path / 'test.sqlite3'}"
    upgrade_database(database_url)
    engine = make_engine(database_url)
    now = datetime.now(UTC)
    with Session(engine) as session:
        laureate = Laureate(
            nobel_api_id="1",
            display_name="Marie Curie",
            created_at=now,
            updated_at=now,
        )
        session.add(laureate)
        session.flush()
        session.add(
            ExternalIdentity(
                laureate_id=laureate.id,
                scheme="wikidata",
                value="Q7186",
                canonical_url="https://www.wikidata.org/wiki/Q7186",
                resolution_status="verified",
                confidence=1.0,
                evidence_json={"method": "fixture"},
            )
        )
        session.commit()
        summary = discover_wikidata_candidates(
            session,
            WikidataBookAdapter("https://query.example/sparql", "test-agent", batch_size=10),
            RawResponseCache(tmp_path / "cache"),
        )
        records = session.scalars(
            select(SourceRecord).order_by(SourceRecord.source_entity_id)
        ).all()
        assertions = session.scalars(select(Assertion)).all()
        record_types = [record.source_entity_type for record in records]
        roles = {
            cast(dict[str, str], assertion.value_json)["value"]
            for assertion in assertions
            if assertion.predicate == "role"
        }
        provenance_sets = [
            (
                set(record.raw_json),
                {
                    assertion.predicate
                    for assertion in assertions
                    if assertion.source_record_id == record.id
                },
            )
            for record in records
        ]
        rerun = discover_wikidata_candidates(
            session,
            WikidataBookAdapter("https://query.example/sparql", "test-agent", batch_size=10),
            RawResponseCache(tmp_path / "cache"),
        )
        stored_assertions = session.scalar(select(func.count()).select_from(Assertion))

    assert route.call_count == 2
    assert summary.records == 2
    assert summary.works == 1
    assert summary.editions == 1
    assert record_types == ["work", "edition"]
    assert roles == {"author", "editor"}
    assert all(raw_fields == predicates for raw_fields, predicates in provenance_sets)
    assert rerun.assertions == 0
    assert stored_assertions == len(assertions)
    assert len(list((tmp_path / "cache" / "wikidata").glob("*.json"))) == 1
    engine.dispose()
