"""Structured JSON logging configuration."""

import logging
import sys

import structlog


def configure_logging(level: str = "INFO") -> None:
    """Configure stdlib and structlog with JSON output."""

    logging.basicConfig(format="%(message)s", stream=sys.stderr, level=level.upper(), force=True)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )
