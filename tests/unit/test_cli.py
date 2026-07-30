from pathlib import Path

from typer.testing import CliRunner

from nobel_books.cli import app

runner = CliRunner()


def test_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "provenance-rich bibliography" in result.stdout


def test_init_creates_directories(tmp_path: Path, monkeypatch: object) -> None:
    # typer's isolated filesystem is not used so paths mirror real CLI behavior.
    current = Path.cwd()
    try:
        import os

        os.chdir(tmp_path)
        result = runner.invoke(app, ["init"])
    finally:
        os.chdir(current)

    assert result.exit_code == 0
    assert (tmp_path / "data/cache").is_dir()
    assert (tmp_path / "data/exports").is_dir()
