"""Shared typed exceptions."""


class NobelBooksError(Exception):
    """Base exception for expected application failures."""


class ConfigurationError(NobelBooksError):
    """Raised when application configuration is invalid."""


class DatabaseError(NobelBooksError):
    """Raised when database setup or access fails."""


class SourceError(NobelBooksError):
    """Base exception for source adapter failures."""


class SourceUnavailableError(SourceError):
    """Raised when a configured source cannot be reached or used."""
