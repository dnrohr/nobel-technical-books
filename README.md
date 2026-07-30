# Nobel Laureate Books

A reproducible, provenance-rich bibliography of books written or edited by Nobel
laureates in Physics, Chemistry, and Physiology or Medicine.

This repository currently implements **Milestones 0–7** from [DESIGN.md](DESIGN.md):
the project scaffold, authoritative Nobel laureate ingestion, exact Wikidata
identity resolution, Wikidata and Google Books discovery, and cautious Open
Library enrichment.

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
uv run nobel-books discover --source wikidata
uv run nobel-books discover --source openlibrary
uv run nobel-books discover --source google-books --laureate-id 102
uv run nobel-books normalize
uv run nobel-books reconcile editions
uv run nobel-books reconcile works
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

## Milestone 3 behavior

`discover --source wikidata` queries verified QIDs for both author (`P50`) and
editor (`P98`) relationships. Results remain source-native records: an
`edition of` (`P629`) statement marks an edition, while unlinked candidates stay
works. Roles, broad instance types, dates, ISBNs, OCLC numbers, titles, and
work/edition links become individual assertions tied to the raw cached response.
No canonical merge occurs during discovery.

## Milestone 4 behavior

Open Library discovery requires `project.contact_email`, sends an identifying
User-Agent, enforces the configured low request rate, and limits each run to a
small configured author cohort. Verified Open Library authority IDs are trusted
at confidence 1.0. Name-search results remain scored review candidates and are
never guessed into verified identities. Author-work and work-edition pages are
fully traversed, cached, and retained as source-native records with edition-to-work
links and field-level assertions. The review queue is written to
`data/exports/openlibrary_identity_review.csv`.

## Milestone 5 behavior

Google Books discovery logs exact-full-name, first-name/surname, and
initials/surname author variants. Every request uses `printType=books`, pages with
`startIndex`, respects the configured per-query result ceiling, caches raw JSON,
and redacts API keys from provenance URLs. Volume IDs are idempotent across query
variants. Contributor strings are evaluated conservatively; unsupported matches
remain `needs_review` candidates with an explicit ambiguous-relationship assertion.

## Milestone 6 behavior

Edition normalization preserves exact source values while producing deterministic
comparison keys for titles, partial dates, languages, contributor roles, ISBNs,
OCLC numbers, and DOIs. ISBN-10/13 checksums are validated and valid ISBN-10
values gain their ISBN-13 equivalent; invalid identifiers remain attached as
issues. Exact ISBN, OCLC, or DOI matches auto-merge. Fuzzy evidence creates
scored proposals, but conflicting valid identifiers always block fuzzy merging.
Cluster membership and selected metadata are stable regardless of input order.

## Milestone 7 behavior

Canonical work clustering prioritizes explicit Open Library work IDs and Wikidata
`edition of` links, then retains unlinked editions as stable work candidates.
Translations remain separate edition rows with their own titles and languages.
Series-level works and volume works coexist through typed `volume` relations.
Potential merges and suspicious splits are exported to
`data/exports/work_review_queue.csv`. Stable YAML merge/split decisions are
stored as first-class database overrides and continue to apply when the YAML file
is absent on later runs.
