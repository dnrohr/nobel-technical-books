from pathlib import Path

import pytest

from nobel_books.config import get_settings
from nobel_books.errors import ConfigurationError


def test_loads_yaml_configuration(config_file: Path) -> None:
    get_settings.cache_clear()
    settings = get_settings(config_file)

    assert settings.project.contact_email == "test@example.org"
    assert settings.categories == ["physics"]
    assert settings.sources["nobel"].base_url == "https://example.invalid"


def test_missing_configuration_is_typed_error(tmp_path: Path) -> None:
    get_settings.cache_clear()

    with pytest.raises(ConfigurationError):
        get_settings(tmp_path / "missing.yaml")
