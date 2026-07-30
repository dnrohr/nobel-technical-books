from pathlib import Path

import pytest


@pytest.fixture()
def config_file(tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(
        """
project:
  contact_email: test@example.org
  database_url: "sqlite:///:memory:"
categories: [physics]
sources:
  nobel:
    enabled: true
    base_url: "https://example.invalid"
log_level: DEBUG
""".strip(),
        encoding="utf-8",
    )
    return path
