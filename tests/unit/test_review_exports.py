import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from nobel_books.classification.classifier import score_relationships
from nobel_books.db import make_engine, upgrade_database
from nobel_books.export.exporters import export_all
from nobel_books.models.database import (
    Assertion,
    CanonicalWork,
    Contribution,
    Edition,
    EditionSourceRecord,
    ExternalIdentity,
    Laureate,
    PipelineRun,
    PipelineStatus,
    PrizeAward,
    SourceFetch,
    SourceRecord,
    WorkSourceRecord,
)
from nobel_books.review.workflow import (
    export_review_queue,
    import_review_decisions,
)


def seed(session: Session) -> Contribution:
    now = datetime.now(UTC)
    laureate = Laureate(
        nobel_api_id="1",
        display_name="Example Author",
        created_at=now,
        updated_at=now,
    )
    work = CanonicalWork(
        cluster_key="work-key",
        preferred_title="Theory of Example Physics",
        normalized_title="theory of example physics",
        first_publication_year=1910,
        work_type="technical_monograph",
        technicality_score=0.8,
        audience_level="graduate",
        classification_confidence=0.9,
        classification_method="deterministic_rules",
        classification_reason="technical indicator: theory of",
        review_status="needs_review",
        overall_confidence=0.8,
        created_at=now,
        updated_at=now,
    )
    session.add_all([laureate, work])
    session.flush()
    session.add(
        PrizeAward(
            laureate_id=laureate.id,
            category="physics",
            year=1950,
            motivation=None,
            share="1",
            source_fetch_id=1,
        )
    )
    run = PipelineRun(profile="fixture", status=PipelineStatus.SUCCEEDED, started_at=now)
    session.add(run)
    session.flush()
    fetch = SourceFetch(
        id=1,
        pipeline_run_id=run.id,
        source="wikidata",
        request_url="https://example.invalid",
        request_key="a" * 64,
        fetched_at=now,
        status_code=200,
        content_hash="b" * 64,
        cache_path="fixture.json",
    )
    session.add(fetch)
    session.flush()
    session.add(
        ExternalIdentity(
            laureate_id=laureate.id,
            scheme="wikidata",
            value="Q1",
            canonical_url="https://wikidata.org/wiki/Q1",
            resolution_status="verified",
            confidence=1.0,
            evidence_json={},
        )
    )
    work_record = SourceRecord(
        source_fetch_id=fetch.id,
        source="wikidata",
        source_entity_type="work",
        source_entity_id="QWORK",
        raw_json={
            "title": "Theory of Example Physics",
            "person": "https://wikidata.org/entity/Q1",
            "role": "author",
        },
        source_url="https://wikidata.org/wiki/QWORK",
    )
    edition_record = SourceRecord(
        source_fetch_id=fetch.id,
        source="wikidata",
        source_entity_type="edition",
        source_entity_id="QEDITION",
        raw_json={"title": "Theory of Example Physics", "isbn13": "9780000000002"},
        source_url="https://wikidata.org/wiki/QEDITION",
    )
    session.add_all([work_record, edition_record])
    session.flush()
    session.add_all(
        [
            Assertion(
                subject_type="work",
                subject_id=work_record.id,
                predicate="title",
                value_json="Theory of Example Physics",
                value_hash="c" * 64,
                source_record_id=work_record.id,
                reliability_class="B",
                confidence=0.9,
                is_selected=True,
                is_contradicted=False,
            ),
            Assertion(
                subject_type="edition",
                subject_id=edition_record.id,
                predicate="isbn13",
                value_json="9780000000002",
                value_hash="d" * 64,
                source_record_id=edition_record.id,
                reliability_class="B",
                confidence=0.9,
                is_selected=True,
                is_contradicted=False,
            ),
        ]
    )
    edition = Edition(
        cluster_key="edition-key",
        canonical_work_id=work.id,
        title="Theory of Example Physics",
        normalized_title="theory of example physics",
        language="en",
        publication_year=1910,
        isbn13="9780000000002",
        wikidata_qid="QEDITION",
        review_status="auto_accepted",
        overall_confidence=0.9,
        merge_method="exact_isbn13",
        identifier_issues=[],
    )
    session.add(edition)
    session.flush()
    session.add_all(
        [
            WorkSourceRecord(source_record_id=work_record.id, canonical_work_id=work.id),
            EditionSourceRecord(source_record_id=edition_record.id, edition_id=edition.id),
        ]
    )
    contribution = Contribution(
        laureate_id=laureate.id,
        canonical_work_id=work.id,
        role="author",
        relationship_confidence=0.65,
        review_status="needs_review",
        is_default_included=False,
        evidence_json=[{"source": "wikidata", "source_record_id": work_record.id}],
    )
    session.add(contribution)
    session.commit()
    return contribution


def write_decision(path: Path, decision: str, reason: str) -> None:
    rows = list(csv.DictReader(path.open(encoding="utf-8", newline="")))
    rows[0]["reviewer_decision"] = decision
    rows[0]["reviewer_reason"] = reason
    rows[0]["reviewer"] = "tester"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_review_roundtrip_manual_precedence_and_all_exports(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'test.sqlite3'}"
    upgrade_database(database_url)
    engine = make_engine(database_url)
    review_path = tmp_path / "review.csv"
    output_dir = tmp_path / "exports"
    with Session(engine) as session:
        contribution = seed(session)
        assert export_review_queue(session, review_path) == 1
        write_decision(review_path, "accept", "Verified against title page")
        assert import_review_decisions(session, review_path) == 1
        score_relationships(session)
        session.refresh(contribution)
        assert contribution.review_status == "verified"
        assert contribution.is_default_included

        write_decision(review_path, "reject", "Different author")
        assert import_review_decisions(session, review_path) == 1
        score_relationships(session)
        session.refresh(contribution)
        assert contribution.review_status == "rejected"
        assert not contribution.is_default_included

        write_decision(review_path, "accept", "Final reviewed decision")
        assert import_review_decisions(session, review_path) == 1
        score_relationships(session)
        counts = export_all(session, output_dir)
        session.refresh(contribution)

    assert contribution.review_status == "verified"
    assert counts["works"] == 1
    assert counts["editions"] == 1
    assert counts["evidence"] == 2
    for name in (
        "works.csv",
        "editions.csv",
        "evidence.csv",
        "bibliography.json",
        "bibliography.md",
        "coverage.json",
        "coverage.md",
        "limitations.json",
        "LIMITATIONS.md",
    ):
        assert (output_dir / name).exists()
    document = json.loads((output_dir / "bibliography.json").read_text(encoding="utf-8"))
    assert "limitations" in document
    exported_work = document["laureates"][0]["works"][0]
    assert exported_work["evidence"]
    assert exported_work["editions"][0]["isbn13"] == "9780000000002"
    markdown = (output_dir / "bibliography.md").read_text(encoding="utf-8")
    assert "#### Technical works" in markdown
    assert "#### Memoir and essays" in markdown
    coverage = json.loads((output_dir / "coverage.json").read_text(encoding="utf-8"))
    assert coverage["unique_laureates"] == 1
    engine.dispose()
