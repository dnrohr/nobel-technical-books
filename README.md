# Nobel Laureate Books

A reproducible, provenance-rich bibliography of books written or edited by Nobel
laureates in Physics, Chemistry, and Physiology or Medicine.

This repository implements **Milestones 0–13** from [DESIGN.md](DESIGN.md):
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
uv run nobel-books discover --source openalex --laureate-id 102
uv run nobel-books discover --source crossref
uv run nobel-books discover --source wikipedia --laureate-id 102
uv run nobel-books classify
uv run nobel-books score
uv run nobel-books review export
uv run nobel-books review import data/exports/review_queue.csv
uv run nobel-books export all
uv run nobel-books audit run
uv run nobel-books audit run --previous data/exports/accepted-audit.json
uv run nobel-books review serve
uv run nobel-books explore
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

## Milestone 8 behavior

OpenAlex author resolution requires a verified OpenAlex ID or exact ORCID bridge;
name-only matches are not accepted. Work requests are filtered to `type:book`,
cursor-paginated, and optionally include XPAC only when configured. Crossref
discovers currently supported book-like types and enriches existing DOI-bearing
editions through the polite pool with contact information. Coverage boundaries,
including the XPAC quality warning and the omission of general/older books, are
written to `data/exports/source_limitations.json`.

## Milestone 9 behavior

Wikipedia fallback discovery uses only the MediaWiki Action API. It first reads
section metadata, matches configurable bibliography headings, and then fetches
only those section indexes. Conservative list and `Cite book` parsing emits
low-confidence, `needs_corroboration` candidates. Each assertion records the
exact page ID, revision ID, section, and cached response. Page or section
failures increment the run summary and do not stop other laureates.

## Milestone 10 behavior

Deterministic classification combines titles, subjects, descriptions, publishers,
source types, and scholarly-source evidence into the documented taxonomy,
technicality score, audience, confidence, and a human-readable reason. Separate
laureate-work relationship confidence uses structured roles, independent-source
agreement, and stable authority linkage. Thresholds distinguish automatic,
provisional, review, and rejected relationships. Golden tests keep technical
Feynman lectures separate from memoir/anecdotal writing. Database-backed manual
classifications always take precedence over automated reruns.

## Milestone 11 behavior

The UTF-8 review queue uses stable Nobel-ID/work-cluster/role keys. Accept and
reject decisions require reasons, become first-class manual overrides, and retain
precedence over later confidence reruns. Export commands produce separate
`works.csv`, `editions.csv`, and `evidence.csv` files; nested
`bibliography.json`; a classified Markdown bibliography; and JSON/Markdown
coverage reports with prior-run deltas. Work and edition exports fail rather than
silently emitting records without source evidence. Every full export also writes
`LIMITATIONS.md` and `limitations.json`, and machine-readable/human-readable
bibliographies carry an explicit research-status warning.

## Milestone 12 behavior

`audit run` writes a stable dataset snapshot and reports added, removed, and
changed relationships, candidate-count drift, zero-book laureates, missing source
coverage, source contribution counts, stale overrides, and hand-checked regression
bibliographies. Removal or destructive modification of a previously verified
relationship exits with status 2 so it cannot pass unattended. The accepted audit
file is deliberately never updated automatically.

## Milestone 13 behavior

WorldCat Search API 2.0 support is optional, structured-JSON-only, and disabled
by default. It requires an OAuth bearer token from `WORLDCAT_ACCESS_TOKEN`; no
WorldCat HTML is scraped and credentials are never placed in URLs. The minimal
browser explorer binds to `127.0.0.1` by default and supports search and filters
across laureates, prize categories, award years, optional subfields, and book
coverage. Laureate profiles expose the Nobel award summary, canonical works,
editions, confidence, identifiers, and source provenance. Its optional review
actions write decisions through the same manual-override function as CSV import.
The full CLI remains usable without
WorldCat credentials or a running UI. See [docs/operations.md](docs/operations.md)
for deployment, audit-baseline, credential, and recovery guidance.

## Optional Amazon links and ratings

The explorer provides a non-affiliate Amazon search link for each edition. Amazon
ratings are never scraped. To add a manually verified snapshot, export a review
template, fill in the ASIN, stars, review count, observation timestamp, direct
Amazon URL, match confidence, and reviewer, then import it:

```bash
uv run nobel-books ratings export-template
uv run nobel-books ratings import data/exports/amazon_ratings_review.csv
```

Ratings are stored per edition, marketplace, ASIN, and observation time. The
explorer and JSON/edition CSV exports show the newest observation and its date.
