"""Typed configuration loaded from YAML, dotenv, and environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from nobel_books.errors import ConfigurationError


def get_credential(name: str | None, path: Path = Path(".env")) -> str | None:
    """Read a credential from the process environment, then the local dotenv file."""

    if not name:
        return None
    import os

    process_value = os.environ.get(name)
    if process_value:
        return process_value
    dotenv_value = dotenv_values(path).get(name)
    return dotenv_value if isinstance(dotenv_value, str) and dotenv_value else None


class ProjectConfig(BaseModel):
    """Project-wide settings."""

    model_config = ConfigDict(extra="forbid")

    contact_email: str = ""
    user_agent: str = "nobel-laureate-books/0.1"
    database_url: str = "sqlite:///data/nobel_books.sqlite3"


class SourceConfig(BaseModel):
    """Common settings for an HTTP source."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = True
    base_url: str | None = None
    requests_per_second: float = 1.0
    page_size: int = 100
    max_authors_per_run: int = 10
    max_results_per_query: int = 400
    api_key_env: str | None = None
    mailto_env: str | None = None
    include_xpac: bool = False
    bibliography_headings: list[str] = Field(default_factory=list)


class ExportConfig(BaseModel):
    """Locations and switches for generated bibliography artifacts."""

    model_config = ConfigDict(extra="forbid")

    output_dir: Path = Path("data/exports")
    include_rejected: bool = False
    include_unreviewed: bool = False


class Settings(BaseSettings):
    """Application configuration."""

    model_config = SettingsConfigDict(
        env_prefix="NOBEL_BOOKS_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
    )

    project: ProjectConfig = Field(default_factory=ProjectConfig)
    categories: list[str] = Field(default_factory=lambda: ["physics", "chemistry", "medicine"])
    sources: dict[str, SourceConfig] = Field(default_factory=dict)
    exports: ExportConfig = Field(default_factory=ExportConfig)
    log_level: str = "INFO"

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Let environment and dotenv values override YAML-backed init values."""

        return env_settings, dotenv_settings, init_settings, file_secret_settings


def _yaml_settings(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigurationError(f"Configuration file not found: {path}")
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"Could not read configuration: {path}") from exc
    if not isinstance(loaded, dict):
        raise ConfigurationError(f"Configuration root must be a mapping: {path}")
    return loaded


@lru_cache(maxsize=1)
def get_settings(path: Path = Path("config/default.yaml")) -> Settings:
    """Load defaults from YAML and allow dotenv/environment overrides."""

    try:
        return Settings(**_yaml_settings(path))
    except ValueError as exc:
        raise ConfigurationError(f"Invalid configuration in {path}") from exc
