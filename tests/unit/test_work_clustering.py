from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nobel_books.classification.classifier import score_relationships
from nobel_books.db import make_engine, upgrade_database
from nobel_books.models.database import (
    CanonicalWork,
    Contribution,
    Edition,
    EditionSourceRecord,
    ExternalIdentity,
    Laureate,
    ManualOverride,
    PipelineRun,
    PipelineStatus,
    SourceFetch,
    SourceRecord,
    WorkRelation,
    WorkSourceRecord,
)
from nobel_books.reconciliation.works import cluster_works


def seed(session: Session) -> tuple[Edition, Edition, Edition]:
    now = datetime.now(UTC)
    run = PipelineRun(
        profile="fixture",
        status=PipelineStatus.SUCCEEDED,
        started_at=now,
    )
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
            source="openlibrary",
            source_entity_type="work",
            source_entity_id="OLWORKW",
            raw_json={"title": "Treatise on Physics"},
            source_url="https://openlibrary.org/works/OLWORKW",
        ),
        SourceRecord(
            source_fetch_id=fetch.id,
            source="wikidata",
            source_entity_type="work",
            source_entity_id="Q200",
            raw_json={"title": "Treatise on Physical Science"},
            source_url="https://wikidata.org/wiki/Q200",
        ),
        SourceRecord(
            source_fetch_id=fetch.id,
            source="openlibrary",
            source_entity_type="edition",
            source_entity_id="OLENM",
            raw_json={
                "title": "Treatise on Physics",
                "work_id": "OLWORKW",
                "language": "en",
                "series_title": "Collected Physics",
                "volume_designation": "Volume 1",
            },
            source_url="https://openlibrary.org/books/OLENM",
        ),
        SourceRecord(
            source_fetch_id=fetch.id,
            source="openlibrary",
            source_entity_type="edition",
            source_entity_id="OLFRM",
            raw_json={
                "title": "Traité de physique",
                "work_id": "OLWORKW",
                "language": "fr",
            },
            source_url="https://openlibrary.org/books/OLFRM",
        ),
        SourceRecord(
            source_fetch_id=fetch.id,
            source="wikidata",
            source_entity_type="edition",
            source_entity_id="Q201",
            raw_json={
                "title": "Treatise on Physical Science",
                "edition_of": "http://www.wikidata.org/entity/Q200",
                "language": "en",
            },
            source_url="https://wikidata.org/wiki/Q201",
        ),
    ]
    session.add_all(records)
    session.flush()
    editions = [
        Edition(
            cluster_key=key,
            title=title,
            normalized_title=title.casefold(),
            language=language,
            review_status="unreviewed",
            overall_confidence=0.8,
            merge_method="singleton",
            identifier_issues=[],
        )
        for key, title, language in (
            ("en", "Treatise on Physics", "en"),
            ("fr", "Traité de physique", "fr"),
            ("other", "Treatise on Physical Science", "en"),
        )
    ]
    session.add_all(editions)
    session.flush()
    for edition, record in zip(editions, records[2:], strict=True):
        session.add(EditionSourceRecord(source_record_id=record.id, edition_id=edition.id))
    session.commit()
    return editions[0], editions[1], editions[2]


def test_explicit_links_translations_series_and_persistent_overrides(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'test.sqlite3'}"
    upgrade_database(database_url)
    engine = make_engine(database_url)
    override_path = tmp_path / "overrides.yaml"
    review_path = tmp_path / "review.csv"
    override_path.write_text(
        """
overrides:
  - target_type: work_cluster
    target_key: "openlibrary:OLWORKW"
    action: merge
    payload:
      with: "wikidata:Q200"
    reason: "Fixture authority decision"
    reviewer: "test"
""".strip(),
        encoding="utf-8",
    )
    with Session(engine) as session:
        english, french, other = seed(session)
        first = cluster_works(session, override_path=override_path, review_path=review_path)
        session.refresh(english)
        session.refresh(french)
        session.refresh(other)
        assert english.canonical_work_id == french.canonical_work_id
        assert english.canonical_work_id == other.canonical_work_id
        assert {english.language, french.language} == {"en", "fr"}
        assert session.scalar(select(func.count()).select_from(WorkRelation)) == 1
        assert first.series_works == 1
        assert session.scalar(select(func.count()).select_from(ManualOverride)) == 1

        override_path.unlink()
        second = cluster_works(session, override_path=override_path, review_path=review_path)
        session.refresh(english)
        session.refresh(other)
        assert english.canonical_work_id == other.canonical_work_id
        assert second.overrides_applied == 1
        assert review_path.exists()
        assert session.scalar(select(func.count()).select_from(CanonicalWork)) >= 2
    engine.dispose()


def test_exact_title_and_verified_laureate_merge_independent_sources(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'cross-source.sqlite3'}"
    upgrade_database(database_url)
    engine = make_engine(database_url)
    now = datetime.now(UTC)
    review_path = tmp_path / "review.csv"
    with Session(engine) as session:
        laureate = Laureate(
            nobel_api_id="1",
            display_name="Example Laureate",
            created_at=now,
            updated_at=now,
        )
        session.add(laureate)
        session.flush()
        session.add(
            ExternalIdentity(
                laureate_id=laureate.id,
                scheme="openlibrary",
                value="OL1A",
                canonical_url="https://openlibrary.org/authors/OL1A",
                resolution_status="verified",
                confidence=1.0,
                evidence_json={},
            )
        )
        run = PipelineRun(profile="fixture", status=PipelineStatus.SUCCEEDED, started_at=now)
        session.add(run)
        session.flush()
        fetch = SourceFetch(
            pipeline_run_id=run.id,
            source="fixture",
            request_url="https://example.invalid/cross-source",
            request_key="c" * 64,
            fetched_at=now,
            status_code=200,
            content_hash="d" * 64,
            cache_path="cross-source.json",
        )
        session.add(fetch)
        session.flush()
        session.add_all(
            [
                SourceRecord(
                    source_fetch_id=fetch.id,
                    source="openlibrary",
                    source_entity_type="work",
                    source_entity_id="OL1W",
                    raw_json={
                        "title": "The Example Book",
                        "author_id": "OL1A",
                        "first_publish_date": "1950",
                    },
                    source_url="https://openlibrary.org/works/OL1W",
                ),
                SourceRecord(
                    source_fetch_id=fetch.id,
                    source="wikipedia",
                    source_entity_type="work",
                    source_entity_id="WIKI1",
                    raw_json={
                        "title": "The Example Book",
                        "year": 1950,
                        "candidate_for_laureate_id": laureate.id,
                    },
                    source_url="https://wikipedia.org/wiki/Example",
                ),
            ]
        )
        session.commit()

        summary = cluster_works(
            session, override_path=tmp_path / "none.yaml", review_path=review_path
        )
        score_relationships(session)
        links = session.scalars(select(WorkSourceRecord)).all()
        author = session.scalar(select(Contribution).where(Contribution.role == "author"))

        assert summary.works == 1
        assert len(links) == 2
        assert len({link.canonical_work_id for link in links}) == 1
        assert author is not None
        assert author.relationship_confidence == 0.85
    engine.dispose()
