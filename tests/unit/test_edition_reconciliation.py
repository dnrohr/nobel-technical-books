from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from nobel_books.db import make_engine, upgrade_database
from nobel_books.models.database import (
    Edition,
    EditionMergeProposal,
    EditionSourceRecord,
    PipelineRun,
    PipelineStatus,
    SourceFetch,
    SourceRecord,
)
from nobel_books.reconciliation.editions import reconcile_editions


def add_records(session: Session, order: list[str]) -> None:
    run = PipelineRun(
        profile="fixture",
        status=PipelineStatus.SUCCEEDED,
        started_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
    )
    session.add(run)
    session.flush()
    fetch = SourceFetch(
        pipeline_run_id=run.id,
        source="fixture",
        request_url="https://example.invalid",
        request_key="a" * 64,
        fetched_at=run.started_at,
        status_code=200,
        content_hash="b" * 64,
        cache_path="fixture.json",
    )
    session.add(fetch)
    session.flush()
    raws = {
        "A": {
            "title": "Quantum Mechanics",
            "authors": ["Example Author"],
            "publishedDate": "1910",
            "publisher": "Science Press",
            "language": "en",
            "isbn13": "9780306406157",
        },
        "B": {
            "title": "Quantum Mechanics",
            "authors": ["Example Author"],
            "publish_date": "1910",
            "publishers": ["Science Press"],
            "languages": [{"key": "/languages/eng"}],
            "isbn_13": ["978-0-306-40615-7"],
        },
        "C": {
            "title": "Quantum Mechanics",
            "authors": ["Example Author"],
            "publishedDate": "1910",
            "publisher": "Science Press",
            "language": "en",
            "isbn13": "9780000000002",
        },
        "D": {
            "title": "Invalid Identifier Book",
            "isbn13": "9780306406158",
        },
    }
    sources = {"A": "google_books", "B": "openlibrary", "C": "wikidata", "D": "google_books"}
    for key in order:
        session.add(
            SourceRecord(
                source_fetch_id=fetch.id,
                source=sources[key],
                source_entity_type="edition",
                source_entity_id=key,
                raw_json=raws[key],
                source_url=f"https://example.invalid/{key}",
            )
        )
    session.commit()


def reconcile_snapshot(
    path: Path, order: list[str]
) -> tuple[list[tuple[str, tuple[str, ...]]], list[tuple[str, str, tuple[str, ...]]]]:
    database_url = f"sqlite:///{path}"
    upgrade_database(database_url)
    engine = make_engine(database_url)
    with Session(engine) as session:
        add_records(session, order)
        edition_count, proposal_count = reconcile_editions(session)
        editions = session.scalars(
            select(Edition).order_by(Edition.title, Edition.cluster_key)
        ).all()
        snapshot = []
        for edition in editions:
            member_ids = tuple(
                session.scalars(
                    select(SourceRecord.source_entity_id)
                    .join(EditionSourceRecord)
                    .where(EditionSourceRecord.edition_id == edition.id)
                    .order_by(SourceRecord.source_entity_id)
                ).all()
            )
            snapshot.append((edition.title, member_ids))
        proposals = session.scalars(
            select(EditionMergeProposal).order_by(
                EditionMergeProposal.left_source_record_id,
                EditionMergeProposal.right_source_record_id,
            )
        ).all()
        proposal_snapshot = []
        for proposal in proposals:
            pair = tuple(
                session.scalars(
                    select(SourceRecord.source_entity_id)
                    .where(
                        SourceRecord.id.in_(
                            (
                                proposal.left_source_record_id,
                                proposal.right_source_record_id,
                            )
                        )
                    )
                    .order_by(SourceRecord.source_entity_id)
                ).all()
            )
            proposal_snapshot.append((proposal.status, f"{proposal.confidence:.3f}", pair))
        proposal_snapshot.sort(key=lambda item: item[2])
        invalid = next(
            edition for edition in editions if edition.title == "Invalid Identifier Book"
        )
        assert invalid.identifier_issues[0]["type"] == "invalid_isbn13"
        assert edition_count == 3
        assert proposal_count >= 2
    engine.dispose()
    return snapshot, proposal_snapshot


def test_exact_isbn_merge_conflict_blocking_and_input_order_determinism(tmp_path: Path) -> None:
    forward = reconcile_snapshot(tmp_path / "forward.sqlite3", ["A", "B", "C", "D"])
    reverse = reconcile_snapshot(tmp_path / "reverse.sqlite3", ["D", "C", "B", "A"])

    assert forward == reverse
    editions, proposals = forward
    assert ("Quantum Mechanics", ("A", "B")) in editions
    assert any(
        status == "blocked" and pair in {("A", "C"), ("B", "C")} for status, _, pair in proposals
    )


def test_reconciliation_removes_stale_editions(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'stale.sqlite3'}"
    upgrade_database(database_url)
    engine = make_engine(database_url)
    with Session(engine) as session:
        add_records(session, ["A", "B"])
        reconcile_editions(session)
        session.add(
            Edition(
                cluster_key="stale",
                title="Stale edition",
                normalized_title="stale edition",
                review_status="unreviewed",
                overall_confidence=0.7,
                merge_method="singleton",
                identifier_issues=[],
            )
        )
        session.commit()

        reconcile_editions(session)

        assert session.scalar(select(Edition).where(Edition.cluster_key == "stale")) is None
        assert len(session.scalars(select(Edition)).all()) == 1
    engine.dispose()
