"""Database engine and schema helpers."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect

from nobel_books.errors import DatabaseError


def ensure_sqlite_parent(database_url: str) -> None:
    prefix = "sqlite:///"
    if database_url.startswith(prefix):
        Path(database_url.removeprefix(prefix)).parent.mkdir(parents=True, exist_ok=True)


def make_engine(database_url: str) -> Engine:
    ensure_sqlite_parent(database_url)
    return create_engine(database_url)


def upgrade_database(database_url: str, revision: str = "head") -> None:
    try:
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", database_url)
        ensure_sqlite_parent(database_url)
        command.upgrade(config, revision)
    except Exception as exc:
        raise DatabaseError("Database migration failed") from exc


def database_status(database_url: str) -> tuple[bool, list[str]]:
    engine = make_engine(database_url)
    try:
        tables = sorted(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    return "alembic_version" in tables, tables
