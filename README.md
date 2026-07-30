# Nobel Laureate Books

A reproducible, provenance-rich bibliography of books written or edited by Nobel
laureates in Physics, Chemistry, and Physiology or Medicine.

This repository currently implements **Milestone 0** from [DESIGN.md](DESIGN.md):
the project scaffold, CLI, configuration, structured logging, database foundation,
and initial migration. It intentionally does not ingest live Nobel data yet.

## Requirements

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/)

## Setup

```bash
uv sync
uv run nobel-books --help
uv run nobel-books init
uv run nobel-books db upgrade
uv run nobel-books status
```

Configuration is loaded from `config/default.yaml`, then an optional `.env` file,
then environment variables prefixed with `NOBEL_BOOKS_`. Nested settings use
double underscores, for example:

```bash
NOBEL_BOOKS_PROJECT__DATABASE_URL=sqlite:///data/local.sqlite3
```

Copy `.env.example` to `.env` for local secrets. Never commit `.env`.

## Development

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
```

Tests are fixture-driven and must not call live external services.
