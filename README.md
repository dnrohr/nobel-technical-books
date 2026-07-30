# Nobel Laureate Books

A reproducible, provenance-rich bibliography of books written or edited by Nobel
laureates in Physics, Chemistry, and Physiology or Medicine.

This repository currently implements **Milestones 0–2** from [DESIGN.md](DESIGN.md):
the project scaffold, authoritative Nobel laureate ingestion, and exact Wikidata
identity resolution.

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
uv run nobel-books laureates sync
uv run nobel-books laureates list
uv run nobel-books identities resolve
uv run nobel-books identities review-export
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

## Milestone 1 behavior

`laureates sync` follows every Nobel API page, stores each raw response in the
content-addressed cache, excludes organizations, retains only Physics, Chemistry,
and Physiology or Medicine awards, and safely upserts laureates and prize records.
Its summary reports laureate totals and award counts by category and year.

## Milestone 2 behavior

`identities resolve` queries Wikidata in small cached batches using exact Nobel API
ID (`P8024`) statements. A single QID is verified at confidence 1.0; zero or
multiple QIDs are retained as unresolved or ambiguous instead of being guessed.
Verified records ingest Wikidata, ORCID, VIAF, ISNI, GND, LCNAF, and Open Library
identifiers plus exact English name variants. `identities review-export` writes
the unresolved/ambiguous queue as UTF-8 CSV.
