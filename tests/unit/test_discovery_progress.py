from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from nobel_books.db import make_engine, upgrade_database
from nobel_books.models.database import CanonicalWork, Contribution, Laureate
from nobel_books.pipeline.progress import mark_laureate_progress, pending_laureates


def test_progress_continues_retries_and_allows_targeted_refresh(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'progress.sqlite3'}"
    upgrade_database(database_url)
    engine = make_engine(database_url)
    now = datetime.now(UTC)
    with Session(engine) as session:
        laureates = [
            Laureate(
                nobel_api_id=str(index),
                display_name=f"Person {index}",
                created_at=now,
                updated_at=now,
            )
            for index in range(1, 5)
        ]
        session.add_all(laureates)
        session.commit()

        first = pending_laureates(session, "wikipedia", 2)
        assert [item.nobel_api_id for item in first] == ["1", "2"]
        mark_laureate_progress(session, first[0], "wikipedia", "succeeded")
        mark_laureate_progress(session, first[1], "wikipedia", "failed")
        session.commit()

        second = pending_laureates(session, "wikipedia", 2)
        assert [item.nobel_api_id for item in second] == ["3", "4"]
        mark_laureate_progress(session, second[0], "wikipedia", "succeeded")
        mark_laureate_progress(session, second[1], "wikipedia", "succeeded")
        session.commit()

        third = pending_laureates(session, "wikipedia", 2)
        assert [item.nobel_api_id for item in third] == ["2"]
        targeted = pending_laureates(session, "wikipedia", 2, nobel_api_id="1")
        assert [item.nobel_api_id for item in targeted] == ["1"]
        refreshed = pending_laureates(session, "wikipedia", 2, refresh=True)
        assert [item.nobel_api_id for item in refreshed] == ["1", "2"]
    engine.dispose()


def test_zero_results_only_excludes_laureates_with_canonical_contributions(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'zero-results.sqlite3'}"
    upgrade_database(database_url)
    engine = make_engine(database_url)
    now = datetime.now(UTC)
    with Session(engine) as session:
        with_books = Laureate(
            nobel_api_id="1",
            display_name="Has Books",
            created_at=now,
            updated_at=now,
        )
        without_books = Laureate(
            nobel_api_id="2",
            display_name="No Books",
            created_at=now,
            updated_at=now,
        )
        work = CanonicalWork(
            cluster_key="existing-work",
            preferred_title="Existing Work",
            normalized_title="existing work",
            original_title=None,
            original_language=None,
            first_publication_year=None,
            work_type="unknown",
            technicality_score=None,
            audience_level=None,
            classification_confidence=None,
            classification_method=None,
            classification_reason=None,
            series_title=None,
            volume_designation=None,
            description=None,
            review_status="unreviewed",
            overall_confidence=0.0,
            created_at=now,
            updated_at=now,
        )
        session.add_all([with_books, without_books, work])
        session.flush()
        session.add(
            Contribution(
                laureate_id=with_books.id,
                canonical_work_id=work.id,
                edition_id=None,
                role="author",
                credited_name=with_books.display_name,
                position=None,
                relationship_confidence=0.65,
                review_status="needs_review",
                is_default_included=False,
                evidence_json=[],
            )
        )
        session.commit()

        selected = pending_laureates(
            session,
            "openlibrary",
            10,
            zero_results_only=True,
        )
        assert [item.nobel_api_id for item in selected] == ["2"]
        targeted = pending_laureates(
            session,
            "openlibrary",
            10,
            nobel_api_id="1",
            zero_results_only=True,
        )
        assert targeted == []
    engine.dispose()
