import copy
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session
from test_review_exports import seed

from nobel_books.audit.report import audit_document, dataset_snapshot, differential_report
from nobel_books.db import make_engine, upgrade_database
from nobel_books.models.database import ManualOverride


@pytest.fixture()
def session(tmp_path: Path) -> Iterator[Session]:
    database_url = f"sqlite:///{tmp_path / 'audit.sqlite3'}"
    engine = make_engine(database_url)
    upgrade_database(database_url)
    with Session(engine) as database_session:
        yield database_session
    engine.dispose()


def test_audit_reports_gaps_sources_and_stale_overrides(session: Session) -> None:
    seed(session)
    session.add(
        ManualOverride(
            target_type="contribution",
            target_key="missing::work::author",
            action="include",
            payload_json={},
            reason="Legacy decision",
            created_at=datetime.now(UTC),
        )
    )
    session.commit()

    report = audit_document(
        session,
        {"wikidata", "openlibrary"},
        regression_path=Path("tests/golden/regression_bibliographies.yaml"),
    )

    assert report["source_contribution_analysis"] == {"wikidata": 2}
    assert "openalex" in report["source_limitations"]
    assert len(report["stale_overrides"]) == 1
    gaps = report["suspicious_gaps"]
    assert isinstance(gaps, dict)
    assert gaps["incomplete_source_coverage"][0]["missing_sources"] == [
        "openlibrary",
        "wikidata",
    ]
    assert report["incomplete_summary"]["failed_regressions"] > 0


def test_differential_blocks_verified_removal_and_metadata_drift(session: Session) -> None:
    contribution = seed(session)
    contribution.review_status = "verified"
    contribution.is_default_included = True
    session.commit()
    previous = dataset_snapshot(session)

    changed = copy.deepcopy(previous)
    works = changed["works"]
    assert isinstance(works, dict)
    record = next(iter(works.values()))
    assert isinstance(record, dict)
    record["title"] = "Changed title"
    report = differential_report(changed, previous)
    assert report["blocking_changes"][0]["kind"] == "changed_verified"

    empty = copy.deepcopy(previous)
    empty["works"] = {}
    empty["candidate_counts"] = {}
    removed = differential_report(empty, previous)
    assert removed["removed"]
    assert removed["blocking_changes"][0]["kind"] == "removed_verified"
