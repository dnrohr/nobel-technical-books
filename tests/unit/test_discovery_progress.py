from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from nobel_books.db import make_engine, upgrade_database
from nobel_books.models.database import Laureate
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
