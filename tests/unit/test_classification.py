from datetime import UTC, datetime
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from nobel_books.classification.classifier import (
    classify_metadata,
    classify_works,
    load_rules,
    score_relationships,
)
from nobel_books.db import make_engine, upgrade_database
from nobel_books.models.database import (
    CanonicalWork,
    Contribution,
    ExternalIdentity,
    Laureate,
    ManualOverride,
    PipelineRun,
    PipelineStatus,
    SourceFetch,
    SourceRecord,
    WorkSourceRecord,
)


def test_golden_technical_and_memoir_cases() -> None:
    rules = load_rules()
    path = Path(__file__).parents[1] / "golden" / "classification_cases.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    for case in document["cases"]:
        result = classify_metadata(case["title"], case["metadata"], set(case["sources"]), rules)
        assert result.work_type == case["expected_class"]
        assert result.reason
        if "minimum_technicality" in case:
            assert result.technicality_score >= case["minimum_technicality"]
        if "maximum_technicality" in case:
            assert result.technicality_score <= case["maximum_technicality"]


def test_manual_classification_and_relationship_thresholds(tmp_path: Path) -> None:
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
        work = CanonicalWork(
            cluster_key="work",
            preferred_title="Collected Thoughts",
            normalized_title="collected thoughts",
            work_type="unknown",
            review_status="unreviewed",
            overall_confidence=0.8,
            created_at=now,
            updated_at=now,
        )
        session.add_all([laureate, work])
        session.flush()
        session.add_all(
            [
                ExternalIdentity(
                    laureate_id=laureate.id,
                    scheme=scheme,
                    value=value,
                    canonical_url=None,
                    resolution_status="verified",
                    confidence=1.0,
                    evidence_json={},
                )
                for scheme, value in (
                    ("wikidata", "Q1"),
                    ("openlibrary", "OL1A"),
                )
            ]
        )
        run = PipelineRun(profile="fixture", status=PipelineStatus.SUCCEEDED, started_at=now)
        session.add(run)
        session.flush()
        fetch = SourceFetch(
            pipeline_run_id=run.id,
            source="fixture",
            request_url="https://example.invalid",
            request_key="a" * 64,
            fetched_at=now,
            status_code=200,
            content_hash="b" * 64,
            cache_path="fixture.json",
        )
        session.add(fetch)
        session.flush()
        records = [
            SourceRecord(
                source_fetch_id=fetch.id,
                source="wikidata",
                source_entity_type="work",
                source_entity_id="QWORK",
                raw_json={
                    "title": "Collected Thoughts",
                    "person": "https://www.wikidata.org/entity/Q1",
                    "role": "author",
                },
                source_url="https://wikidata.org/wiki/QWORK",
            ),
            SourceRecord(
                source_fetch_id=fetch.id,
                source="openlibrary",
                source_entity_type="work",
                source_entity_id="OLWORKW",
                raw_json={
                    "title": "Collected Thoughts",
                    "author_id": "OL1A",
                },
                source_url="https://openlibrary.org/works/OLWORKW",
            ),
            SourceRecord(
                source_fetch_id=fetch.id,
                source="wikipedia",
                source_entity_type="work",
                source_entity_id="WIKI1",
                raw_json={
                    "title": "Collected Thoughts",
                    "candidate_for_laureate_id": laureate.id,
                    "review_status": "needs_corroboration",
                },
                source_url="https://wikipedia.org/?oldid=1",
            ),
        ]
        session.add_all(records)
        session.flush()
        session.add_all(
            [
                WorkSourceRecord(source_record_id=record.id, canonical_work_id=work.id)
                for record in records
            ]
        )
        session.add(
            ManualOverride(
                target_type="canonical_work",
                target_key="work",
                action="classify",
                payload_json={
                    "class": "popular_science",
                    "score": 0.3,
                    "audience": "general",
                },
                reason="Reviewed fixture",
                reviewer="test",
                created_at=now,
            )
        )
        session.commit()
        classification = classify_works(session, load_rules())
        relationships = score_relationships(session)
        session.refresh(work)
        contributions = session.scalars(select(Contribution)).all()

    assert classification.manual == 1
    assert work.work_type == "popular_science"
    assert work.classification_method == "manual"
    assert work.classification_reason == "Manual override: Reviewed fixture"
    assert relationships.contributions == 2
    assert len(contributions) == 2
    author = next(item for item in contributions if item.role == "author")
    unknown = next(item for item in contributions if item.role == "unknown")
    assert author.relationship_confidence == 0.85
    assert {item["source"] for item in author.evidence_json} == {
        "wikidata",
        "openlibrary",
        "wikipedia",
    }
    assert author.review_status == "provisional"
    assert author.is_default_included
    assert unknown.relationship_confidence == 0.0
    assert unknown.review_status == "rejected"
    assert not unknown.is_default_included
    engine.dispose()
