from pathlib import Path

from nobel_books.db import database_status, upgrade_database


def test_migration_creates_initial_schema(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'test.sqlite3'}"

    upgrade_database(database_url)
    migrated, tables = database_status(database_url)

    assert migrated
    assert {"pipeline_run", "source_fetch"}.issubset(tables)
