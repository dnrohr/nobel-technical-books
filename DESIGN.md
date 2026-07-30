# Nobel Laureate Book Bibliography
## Engineering Design and Codex Implementation Plan

**Status:** Initial design  
**Last updated:** 2026-07-30  
**Primary language:** Python  
**Primary output:** A provenance-rich bibliography of books written or edited by Nobel laureates in Physics, Chemistry, and Physiology or Medicine

---

## 1. Executive summary

This project will construct a reproducible bibliography of books associated with every individual Nobel laureate in:

- Physics
- Chemistry
- Physiology or Medicine

The system should discover **all plausible books**, not merely technical books, and then classify each work so that technical monographs, textbooks, treatises, and reference works can be isolated from popular science, memoir, essays, fiction, edited proceedings, and other material.

The project must not assume that any one bibliographic database is complete. NobelPrize.org is authoritative for the laureate population, but it does not provide complete bibliographies. Wikidata, Open Library, Google Books, OpenAlex, Crossref, Wikipedia, and library catalogs all have different coverage and failure modes. The system therefore uses a **multi-source candidate-generation pipeline**, records the provenance of every assertion, reconciles duplicates at both the work and edition levels, assigns confidence scores, and produces a human-review queue for ambiguous cases.

The recommended final product has two related views:

1. **Canonical works:** one row per distinct intellectual work, such as *The Feynman Lectures on Physics*.
2. **Editions and translations:** separate publication records linked to the canonical work.

This distinction is essential. A book with many revised editions and translations should not be counted as many different books written by the laureate, but its editions should remain available for verification and bibliographic detail.

The implementation should be incremental. The first useful release can rely on the Nobel API, Wikidata, Open Library, and Google Books, with manual review and CSV/Markdown export. OpenAlex, Crossref, Wikipedia bibliography parsing, WorldCat, national-library catalogs, and a review interface can be added afterward.

---

## 2. Problem statement

The desired research question is:

> What books were written, co-written, or edited by every Nobel laureate in Physics, Chemistry, and Physiology or Medicine, and which of those books are technical?

This is not equivalent to querying a single `author = laureate` database field. Difficulties include:

- Laureates may have multiple names, transliterations, initials, married names, pen names, and diacritics.
- Older works may have no ISBN.
- A database may confuse a book **about** a laureate with a book **by** that laureate.
- A laureate may be only a foreword writer, interview subject, translator, or chapter contributor.
- The same work may appear as many editions, translations, reprints, or split volumes.
- A multi-volume treatise may be represented as a series, a set, individual volumes, or all three.
- Edited proceedings may look like authored monographs.
- Open scholarly indexes often cover technical monographs but omit memoirs and popular books.
- General book catalogs often cover popular books well but incompletely identify technical authors.
- Wikipedia bibliographies are useful but inconsistent and unstructured.
- “Technical” is a classification judgment, not a universally available metadata field.
- Some laureates may genuinely have written no books, while others merely appear to have none because of incomplete source coverage.

The system must therefore be designed as a **bibliographic reconciliation and review system**, not a one-shot scraper.

---

## 3. Goals

### 3.1 Primary goals

The system shall:

1. Retrieve the complete, current set of individual laureates in the three target Nobel categories.
2. Preserve every prize event for laureates who won more than once or in more than one category.
3. Resolve each laureate to stable external identifiers whenever possible.
4. Query multiple bibliographic sources for candidate books.
5. Preserve raw source responses and field-level provenance.
6. Distinguish author, coauthor, editor, translator, contributor, foreword writer, and subject relationships.
7. Distinguish a conceptual work from its editions, translations, volumes, and reprints.
8. Merge duplicate records without discarding source-specific evidence.
9. Classify works by genre and technicality.
10. Assign confidence and review status to each work-author relationship.
11. Support manual corrections and exclusions that survive future pipeline runs.
12. Export machine-readable and human-readable bibliographies.
13. Report unresolved identities, suspiciously empty bibliographies, and other coverage gaps.
14. Make every pipeline stage reproducible and idempotent.

### 3.2 Secondary goals

The architecture should make it straightforward to add:

- Nobel laureates in Economics, Literature, or Peace
- Turing Award recipients
- Fields Medalists
- Abel Prize recipients
- Lasker Award recipients
- National library catalogs
- ORCID or institutional-profile enrichment
- A browser-based review interface
- LLM-assisted classification, with deterministic fallback and explicit provenance

---

## 4. Non-goals

The initial project will not:

- Download or redistribute copyrighted book text.
- Attempt to prove mathematical completeness in the strict sense.
- Treat retailer inventories as authoritative bibliographic sources.
- Scrape Google search results, WorldCat HTML pages, Amazon, or other interfaces whose terms or structure make automated scraping unsuitable.
- Count every unchanged reprint as a distinct authored work.
- Infer authorship merely because the laureate’s name appears in a title or description.
- Treat journal articles, patents, book chapters, dissertations, or Nobel lectures as books unless they were independently published in book form.
- Automatically publish low-confidence records without retaining a review state.
- Use an LLM as the sole authority for authorship, dates, identifiers, or deduplication.

---

## 5. Scope and terminology

### 5.1 Laureate population

Include individual laureates with at least one Nobel Prize in:

- Physics
- Chemistry
- Physiology or Medicine

Do not include organizations. The official Nobel API is the authority for whether a person belongs to the target population.

A laureate is represented once as a person even when that person:

- received the prize more than once;
- received prizes in two target categories;
- received both a target-category prize and a non-target prize.

Prize events are stored separately from people.

### 5.2 Canonical work

A **canonical work** is the intellectual content normally meant when a reader names a book. Examples:

- a textbook;
- a scientific monograph;
- an autobiography;
- a collection of essays assembled as a book;
- an edited reference volume;
- a multi-volume treatise considered either as a series-level work or as separately titled volume works, depending on bibliographic evidence.

A canonical work is not identified solely by ISBN. ISBNs normally identify editions or formats.

### 5.3 Edition

An **edition** is a particular publication manifestation or bibliographic edition of a work. It may have:

- an ISBN-10 or ISBN-13;
- a publisher;
- a publication date;
- a language;
- an edition statement;
- a format;
- a translated title;
- an OCLC number;
- an Open Library edition ID;
- a Google Books volume ID.

The system should retain all discovered editions but present canonical works as the default bibliography.

### 5.4 Contribution role

Every person-work association must have a role:

- `author`
- `coauthor`
- `editor`
- `coeditor`
- `series_editor`
- `translator`
- `compiler`
- `annotator`
- `foreword`
- `introduction`
- `interviewer`
- `contributor`
- `subject`
- `unknown`

Only `author`, `coauthor`, `editor`, and `coeditor` are included in the default bibliography. Other roles remain discoverable and can be included in a supplemental export.

### 5.5 Book inclusion policy

#### Core inclusion

Include:

- authored or coauthored technical monographs;
- textbooks;
- treatises;
- handbooks and reference works;
- general-audience science books;
- memoirs and autobiographies;
- essay and lecture collections published as books;
- history or philosophy books authored by the laureate;
- fiction authored by the laureate;
- edited or coedited books and proceedings, clearly labeled as edited;
- independently published Nobel lectures or lecture series when cataloged as books;
- multi-volume works, preserving both series and volume structure where possible.

#### Supplemental inclusion

Retain but exclude from the default list unless configured otherwise:

- books with only a foreword or introduction by the laureate;
- festschrifts honoring the laureate;
- interviews published in book form when the laureate is primarily an interview subject;
- translated books where the laureate served only as translator;
- collected papers edited after the laureate’s death by someone else;
- exhibition catalogs;
- pamphlets and offprints that library catalogs treat as monographs;
- course notes with uncertain publication status;
- separately cataloged book chapters.

#### Exclusion

Exclude from authored-book counts:

- biographies about the laureate;
- books merely named after the laureate;
- journal issues;
- journal articles;
- book reviews;
- patents;
- theses unless later published as a book;
- conference papers that were not published as a book or proceedings volume;
- records where the laureate is only the subject;
- duplicate reprints with no bibliographically meaningful change.

### 5.6 Technical classification

Each canonical work should receive one primary class:

- `technical_monograph`
- `textbook`
- `technical_treatise`
- `reference_handbook`
- `collected_technical_works`
- `edited_technical_volume`
- `conference_proceedings`
- `popular_science`
- `scientific_memoir`
- `general_memoir_autobiography`
- `essays_lectures`
- `history_philosophy_policy`
- `fiction`
- `correspondence`
- `other_nontechnical`
- `unknown`

Also store:

- `technicality_score`: float from `0.0` to `1.0`
- `audience_level`: `specialist`, `graduate`, `undergraduate`, `general`, `mixed`, or `unknown`
- `classification_method`: `rule`, `manual`, `source_metadata`, or `llm_assisted`
- `classification_reason`: concise human-readable explanation
- `classification_confidence`: float from `0.0` to `1.0`

Suggested interpretation:

| Score | Meaning |
|---:|---|
| 0.90–1.00 | Specialist technical work, textbook, treatise, or reference work |
| 0.70–0.89 | Substantially technical but accessible beyond specialists |
| 0.40–0.69 | Mixed technical and general material |
| 0.10–0.39 | Popular science, scientific memoir, or broad intellectual work |
| 0.00–0.09 | Nontechnical memoir, fiction, correspondence, or unrelated edited material |

Technicality must not determine whether a work is retained. It determines how the bibliography can be filtered.

---

## 6. Completeness model

No source should be described as complete. Instead, the system should measure **evidence coverage**.

### 6.1 Candidate recall

A work enters the pipeline when at least one source suggests an eligible relationship between a laureate and a book-like record.

High recall is preferred during discovery. False positives are removed later.

### 6.2 Verification strength

A candidate becomes `verified` when one of the following is true:

- two independent bibliographic sources agree on title and contribution role;
- one authoritative catalog provides a strong, structured authorship record;
- a publisher, title page, institutional bibliography, or manually reviewed scan confirms the relationship;
- a trusted manual override confirms it.

### 6.3 Coverage tiers

Assign each laureate a coverage status:

- `tier_0_unprocessed`
- `tier_1_identity_resolved`
- `tier_2_structured_sources_queried`
- `tier_3_fallback_sources_queried`
- `tier_4_human_reviewed`
- `tier_5_bibliography_audited`

A project-wide claim of “complete” should be avoided until every laureate reaches at least Tier 4 and suspicious gaps have been audited.

### 6.4 Suspicious gap rules

Create a review alert when:

- a laureate has zero candidate books;
- identity resolution is unresolved or ambiguous;
- Wikipedia has a bibliography section but no structured-source candidates were found;
- one source reports more than a configurable threshold of works while others report none;
- a candidate has no publication year and no stable identifier;
- a highly cited OpenAlex author is resolved but no book-type works are returned;
- the laureate has a known teaching career but no textbook or lecture-book candidates;
- the candidate count changes sharply between runs;
- a record is supported by only a retailer or weak text match;
- an author-name collision is likely.

These are review triggers, not proof that a book is missing.

---

## 7. Source strategy

### 7.1 Source priority

Use sources in the following order.

#### Source A: Nobel Prize API — authoritative laureate population

Purpose:

- retrieve laureate IDs;
- retrieve names and dates;
- retrieve prize categories and years;
- preserve prize motivations and affiliations where useful for identity resolution.

Base endpoint:

```text
https://api.nobelprize.org/2.1/
```

Relevant endpoint:

```text
GET /laureates
```

The pipeline should filter prize events to category codes corresponding to Physics, Chemistry, and Physiology or Medicine. Do not hardcode the current last prize year. Fetch whatever the API currently returns.

Store the Nobel Laureate API ID as the primary external identifier for population membership.

#### Source B: Wikidata — identifier bridge and structured candidate source

Purpose:

- map Nobel IDs to Wikidata QIDs using `P8024` (Nobel Laureate API ID);
- collect name variants, birth/death dates, ORCID, VIAF, ISNI, Library of Congress, GND, and other authority identifiers;
- discover authored works using `P50` (author);
- discover edited works using `P98` (editor);
- connect editions to works using `P629` (edition or translation of);
- retrieve ISBN-13 `P212`, ISBN-10 `P957`, OCLC `P243`, publication dates, languages, publishers, and titles.

Important modeling rule:

> Wikidata commonly models the abstract work separately from each edition or translation. The pipeline must not flatten these into one undifferentiated record set.

Do not run one enormous SPARQL query for the entire project. Query in small batches, cache results, use an identifying User-Agent, and retry conservatively.

Example Nobel-ID-to-QID query:

```sparql
SELECT ?person WHERE {
  ?person wdt:P8024 "NOBEL_ID_HERE" .
}
```

Example candidate query, deliberately broad to maximize recall:

```sparql
SELECT DISTINCT
  ?item
  ?itemLabel
  ?instance
  ?instanceLabel
  ?role
  ?publicationDate
  ?isbn13
  ?isbn10
  ?oclc
  ?editionOf
  ?editionOfLabel
WHERE {
  VALUES ?person { wd:PERSON_QID }

  {
    ?item wdt:P50 ?person .
    BIND("author" AS ?role)
  }
  UNION
  {
    ?item wdt:P98 ?person .
    BIND("editor" AS ?role)
  }

  OPTIONAL { ?item wdt:P31 ?instance . }
  OPTIONAL { ?item wdt:P577 ?publicationDate . }
  OPTIONAL { ?item wdt:P212 ?isbn13 . }
  OPTIONAL { ?item wdt:P957 ?isbn10 . }
  OPTIONAL { ?item wdt:P243 ?oclc . }
  OPTIONAL { ?item wdt:P629 ?editionOf . }

  SERVICE wikibase:label {
    bd:serviceParam wikibase:language "en,[AUTO_LANGUAGE]".
  }
}
```

Filtering to “books” should happen after retrieval because imperfect `instance of` data can otherwise cause false negatives.

#### Source C: Open Library — work/edition catalog

Purpose:

- resolve author records;
- retrieve works associated with an Open Library author;
- retrieve editions and identifiers;
- obtain subjects, alternate titles, publishers, languages, and first-publication years.

Use structured APIs, not HTML scraping.

Important operational constraints:

- send a descriptive User-Agent and contact information;
- use the API at low volume;
- cache every response;
- do not use the public API for bulk downloads;
- use Open Library data dumps if project scale or repeated full rebuilds justify them.

Identity resolution should prefer authority identifiers and biographical agreement over name alone.

#### Source D: Google Books API — broad candidate discovery and edition enrichment

Purpose:

- find editions omitted from other sources;
- obtain ISBNs, publisher, publication date, categories, descriptions, and contributor strings;
- discover popular books and memoirs that scholarly indexes omit.

Use:

```text
GET https://www.googleapis.com/books/v1/volumes
```

Typical parameters:

```text
q=<author-oriented query>
printType=books
projection=full
maxResults=40
startIndex=<page offset>
```

The API limits a response page to at most 40 records, so paginate until results are exhausted or a safety limit is reached.

Google Books results are candidate evidence, not definitive authorship proof. Names may be ambiguous, contributor roles may be flattened, and result counts may be unstable.

#### Source E: OpenAlex — technical and scholarly books

Purpose:

- discover scholarly works classified as `book`;
- identify technical monographs and books with DOI metadata;
- obtain topics, citation context, publication dates, and author identifiers.

Resolve the author first, preferably via ORCID or another stable identifier. Then query works by the resolved OpenAlex author ID and filter to book-like work types.

Example pattern:

```text
GET /authors?search=<name>
GET /works?filter=authorships.author.id:<OPENALEX_AUTHOR_ID>,type:book
```

OpenAlex should not be expected to cover memoirs, popular books, older non-digitized monographs, or all editions.

Include `include_xpac=true` only as an explicitly configurable recall-enhancement mode because OpenAlex documents lower average data quality for XPAC records.

#### Source F: Crossref — DOI-registered books and monographs

Purpose:

- retrieve monographs, edited books, reference works, and book sets with DOIs;
- confirm publisher metadata and contributor roles;
- link books and chapters;
- enrich existing DOI-bearing records.

Use the polite pool by supplying contact information. Query relevant Crossref work types, including `monograph`, `book`, `edited-book`, `reference-book`, `book-set`, and related types present in the live `/types` endpoint.

Crossref is an enrichment and corroboration source. It is not expected to cover most older books or books without DOIs.

#### Source G: Wikipedia / MediaWiki Action API — fallback bibliography extraction

Purpose:

- identify named bibliography or works sections;
- extract candidate titles for poorly covered laureates;
- obtain citations and external links that lead to stronger sources.

Use the MediaWiki Action API:

1. retrieve section metadata using `action=parse&prop=sections`;
2. identify sections with normalized headings such as:
   - Bibliography
   - Books
   - Selected works
   - Publications
   - Works
   - Major works
3. retrieve only the relevant section’s wikitext or parsed HTML;
4. parse list items and citations into candidate records.

Never treat a Wikipedia list item as final proof. Record the exact page revision ID and section as provenance.

Wikipedia parsing should be optional and isolated because page structure varies substantially.

#### Source H: WorldCat Search API v2 — optional catalog authority

Purpose:

- high-value edition and authority verification;
- OCLC identifiers;
- publication history;
- difficult older or multilingual works.

WorldCat access may require eligible institutional credentials. The old WorldCat Search API 1.0 reached end of support in 2024; implement only against current v2 documentation.

Do not scrape WorldCat.org search-result pages. Make the adapter optional and disabled by default when credentials are absent.

#### Source I: national libraries and authoritative bibliographies — later extensions

Potential adapters:

- Library of Congress
- British Library
- Bibliothèque nationale de France
- Deutsche Nationalbibliothek
- National Diet Library
- Nobel laureate institutional pages
- publisher catalogs
- official collected-works bibliographies
- VIAF-linked national authority records

These are especially valuable for older books, non-English works, and authors with inconsistent romanization.

### 7.2 Source reliability classes

Assign each evidence record a reliability class:

| Class | Examples | Normal use |
|---|---|---|
| A | national library record, title page, publisher metadata, manually verified scan | definitive verification |
| B | Wikidata with references, Open Library authority-linked record, WorldCat, Crossref | strong structured evidence |
| C | Google Books, OpenAlex, institutional bibliography | useful corroboration |
| D | Wikipedia bibliography, unverified catalog aggregation | candidate generation |
| E | retailer listing, free-text web mention | review lead only |

The class is assigned to the evidence, not permanently to an entire source. A source can contain records of varying quality.

---

## 8. System architecture

### 8.1 Recommended stack

- Python 3.12 or newer
- `uv` for dependency and environment management
- `Typer` for the command-line interface
- `httpx` for HTTP
- `tenacity` for retries and backoff
- `pydantic` for source-response and domain models
- `SQLAlchemy 2.x` plus Alembic for persistence and migrations
- SQLite for the initial implementation
- PostgreSQL-compatible schema design where practical
- `rapidfuzz` for title and name comparison
- `unidecode` only for secondary matching keys, never display text
- `python-dateutil` for partial and uncertain dates
- `pytest`, `pytest-cov`, and `respx` for tests
- `ruff` for linting and formatting
- `mypy` or `pyright` for static type checking
- `structlog` or standard structured JSON logging
- `PyYAML` for manual overrides and configuration
- optional `FastAPI` plus a minimal HTML interface for later review tooling

Avoid a frontend in the MVP. A CLI, SQLite database, review CSV, and Markdown reports are enough to validate the research method before building a UI.

### 8.2 Architectural components

```text
Official Nobel API
        |
        v
Laureate Ingestion
        |
        v
Identity Resolution <---------------------------+
        |                                       |
        v                                       |
Source Adapters                                 |
(Wikidata, Open Library, Google Books,          |
 OpenAlex, Crossref, Wikipedia, WorldCat)       |
        |                                       |
        v                                       |
Raw Source Records + Candidate Assertions       |
        |                                       |
        v                                       |
Normalization                                   |
        |                                       |
        v                                       |
Work/Edition Reconciliation                     |
        |                                       |
        v                                       |
Role Verification + Classification              |
        |                                       |
        v                                       |
Human Review / Manual Overrides ----------------+
        |
        v
CSV / JSON / Markdown / Coverage Reports
```

### 8.3 Adapter interface

Every source adapter should implement a common protocol:

```python
from typing import Protocol, Iterable

class SourceAdapter(Protocol):
    name: str

    def healthcheck(self) -> None:
        """Raise a typed error if the source cannot be used."""

    def discover_for_person(
        self,
        person: "Laureate",
        identities: list["ExternalIdentity"],
    ) -> Iterable["RawCandidate"]:
        """Yield source-native book candidates for one person."""

    def enrich_edition(
        self,
        edition: "Edition",
    ) -> Iterable["RawCandidate"]:
        """Optionally enrich a known edition by ISBN, DOI, or source ID."""
```

Adapters must not write directly to canonical work tables. They write:

- immutable raw fetch records;
- parsed source records;
- candidate assertions;
- source identifiers.

Normalization and reconciliation happen in separate services.

### 8.4 Pipeline stages

1. `sync_laureates`
2. `resolve_identities`
3. `discover_candidates`
4. `parse_raw_records`
5. `normalize_candidates`
6. `resolve_contributions`
7. `cluster_editions`
8. `cluster_works`
9. `classify_works`
10. `score_confidence`
11. `generate_review_queue`
12. `apply_manual_overrides`
13. `export_results`
14. `generate_coverage_report`

Every stage must be:

- resumable;
- idempotent;
- independently testable;
- safe to rerun after code or source-data changes.

---

## 9. Repository layout

```text
nobel-laureate-books/
├── AGENTS.md
├── DESIGN.md
├── README.md
├── pyproject.toml
├── uv.lock
├── .env.example
├── alembic.ini
├── migrations/
├── config/
│   ├── default.yaml
│   ├── classification_rules.yaml
│   └── source_reliability.yaml
├── data/
│   ├── manual/
│   │   ├── person_identity_overrides.yaml
│   │   ├── work_overrides.yaml
│   │   ├── exclusions.yaml
│   │   └── regression_bibliographies.yaml
│   ├── exports/
│   └── cache/
├── src/
│   └── nobel_books/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── db.py
│       ├── logging.py
│       ├── models/
│       │   ├── database.py
│       │   ├── domain.py
│       │   └── source.py
│       ├── adapters/
│       │   ├── base.py
│       │   ├── nobel.py
│       │   ├── wikidata.py
│       │   ├── openlibrary.py
│       │   ├── google_books.py
│       │   ├── openalex.py
│       │   ├── crossref.py
│       │   ├── wikipedia.py
│       │   └── worldcat.py
│       ├── identity/
│       │   ├── resolver.py
│       │   ├── scoring.py
│       │   └── names.py
│       ├── normalization/
│       │   ├── titles.py
│       │   ├── names.py
│       │   ├── identifiers.py
│       │   ├── dates.py
│       │   └── roles.py
│       ├── reconciliation/
│       │   ├── editions.py
│       │   ├── works.py
│       │   ├── series.py
│       │   └── confidence.py
│       ├── classification/
│       │   ├── rules.py
│       │   ├── classifier.py
│       │   └── taxonomy.py
│       ├── review/
│       │   ├── queue.py
│       │   ├── overrides.py
│       │   └── audit.py
│       ├── export/
│       │   ├── csv_export.py
│       │   ├── json_export.py
│       │   ├── markdown_export.py
│       │   └── reports.py
│       └── pipeline/
│           ├── runner.py
│           └── stages.py
└── tests/
    ├── fixtures/
    ├── unit/
    ├── integration/
    ├── contract/
    └── golden/
```

---

## 10. Data model

The database should preserve both canonical entities and source-native evidence.

### 10.1 `laureate`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID/integer | Internal stable ID |
| `nobel_api_id` | text, unique | Authoritative Nobel identifier |
| `display_name` | text | Preferred display form |
| `given_name` | text nullable | |
| `family_name` | text nullable | |
| `full_name_native` | text nullable | |
| `gender` | text nullable | Source value, not required for bibliography |
| `birth_date_raw` | text nullable | Preserve partial date |
| `death_date_raw` | text nullable | |
| `is_organization` | boolean | Organizations excluded from target population |
| `created_at` | timestamp | |
| `updated_at` | timestamp | |

### 10.2 `prize_award`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID/integer | |
| `laureate_id` | FK | |
| `category` | enum | `physics`, `chemistry`, `medicine` |
| `year` | integer | |
| `motivation` | text nullable | |
| `share` | text nullable | Preserve source representation |
| `source_record_id` | FK | Nobel raw record |
| unique constraint | | laureate, category, year |

### 10.3 `person_name_variant`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID/integer | |
| `laureate_id` | FK | |
| `name` | text | Exact variant |
| `normalized_name` | text | Matching-only key |
| `language` | text nullable | |
| `script` | text nullable | |
| `source` | text | |
| `is_preferred` | boolean | |
| `confidence` | float | |

### 10.4 `external_identity`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID/integer | |
| `laureate_id` | FK | |
| `scheme` | enum/text | Wikidata, ORCID, VIAF, ISNI, OpenLibrary, OpenAlex, LCNAF, GND, etc. |
| `value` | text | |
| `canonical_url` | text nullable | |
| `resolution_status` | enum | proposed, verified, rejected, manual |
| `confidence` | float | |
| `evidence_json` | JSON | |
| unique constraint | | scheme, value |

### 10.5 `canonical_work`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | |
| `preferred_title` | text | |
| `normalized_title` | text | Matching key |
| `original_title` | text nullable | |
| `original_language` | text nullable | |
| `first_publication_year` | integer nullable | |
| `work_type` | taxonomy enum | |
| `technicality_score` | float nullable | |
| `audience_level` | enum nullable | |
| `classification_confidence` | float nullable | |
| `classification_method` | text nullable | |
| `classification_reason` | text nullable | |
| `series_title` | text nullable | |
| `volume_designation` | text nullable | |
| `description` | text nullable | Must retain source/provenance |
| `review_status` | enum | unreviewed, auto_accepted, needs_review, verified, rejected |
| `overall_confidence` | float | |
| `created_at` | timestamp | |
| `updated_at` | timestamp | |

### 10.6 `edition`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | |
| `canonical_work_id` | FK nullable | Null until clustered |
| `title` | text | |
| `subtitle` | text nullable | |
| `normalized_title` | text | |
| `language` | text nullable | |
| `publication_date_raw` | text nullable | |
| `publication_year` | integer nullable | |
| `edition_statement` | text nullable | |
| `publisher` | text nullable | |
| `publication_place` | text nullable | |
| `format` | text nullable | hardcover, paperback, ebook, etc. |
| `page_count` | integer nullable | |
| `isbn10` | text nullable | normalized |
| `isbn13` | text nullable | normalized |
| `doi` | text nullable | |
| `oclc` | text nullable | |
| `wikidata_qid` | text nullable | |
| `openlibrary_edition_id` | text nullable | |
| `google_books_id` | text nullable | |
| `review_status` | enum | |
| `overall_confidence` | float | |

Identifiers should ultimately also be normalized into a generic identifier table; convenience columns are acceptable in the MVP.

### 10.7 `contribution`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | |
| `laureate_id` | FK | |
| `canonical_work_id` | FK nullable | |
| `edition_id` | FK nullable | |
| `role` | enum | |
| `credited_name` | text nullable | Exact source string |
| `position` | integer nullable | Contributor ordering |
| `relationship_confidence` | float | |
| `review_status` | enum | |
| `is_default_included` | boolean | |
| constraint | | work or edition must be present |

### 10.8 `source_fetch`

Immutable record of an HTTP transaction.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | |
| `source` | text | |
| `request_url` | text | Redact secrets |
| `request_method` | text | |
| `request_params_json` | JSON | Redact API keys |
| `retrieved_at` | timestamp | |
| `status_code` | integer | |
| `etag` | text nullable | |
| `last_modified` | text nullable | |
| `response_sha256` | text | |
| `response_body_path` | text or blob reference | |
| `parser_version` | text nullable | |
| `error_type` | text nullable | |
| `error_message` | text nullable | |

### 10.9 `source_record`

Parsed source-native entity.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | |
| `source_fetch_id` | FK | |
| `source` | text | |
| `source_entity_type` | text | author, work, edition, volume, page section |
| `source_entity_id` | text nullable | |
| `raw_json` | JSON | Parsed subset or full native object |
| `source_url` | text nullable | |
| unique constraint | | source + entity type + entity ID + fetch version as appropriate |

### 10.10 `assertion`

Field-level provenance and contradiction tracking.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | |
| `subject_type` | text | laureate, work, edition, contribution |
| `subject_id` | UUID | |
| `predicate` | text | title, author, editor, date, ISBN, etc. |
| `value_json` | JSON | |
| `source_record_id` | FK | |
| `reliability_class` | enum | A–E |
| `confidence` | float | |
| `is_selected` | boolean | Chosen canonical value |
| `is_contradicted` | boolean | |
| `notes` | text nullable | |

### 10.11 `manual_override`

Manual decisions must be first-class data.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | |
| `target_type` | text | |
| `target_key` | text | Stable selector |
| `action` | enum | set, merge, split, include, exclude, verify, reject |
| `payload_json` | JSON | |
| `reason` | text | Required |
| `reviewer` | text nullable | |
| `created_at` | timestamp | |
| `supersedes_id` | FK nullable | |

Manual overrides are applied after automated reconciliation and before export. They must never be silently overwritten by a later run.

### 10.12 `pipeline_run`

Track reproducibility:

- run ID;
- git commit;
- configuration hash;
- start/end timestamps;
- enabled adapters;
- source versions where available;
- counts by stage;
- warning/error summary;
- export paths.

---

## 11. Identity resolution

Identity errors are more damaging than missing metadata. Resolve people before harvesting books.

### 11.1 Resolution order

1. Nobel API ID to Wikidata `P8024`
2. Wikidata to ORCID, VIAF, ISNI, GND, LCNAF, Open Library, and other authority IDs
3. ORCID to OpenAlex when available
4. Authority-ID links to Open Library or national catalogs
5. Name/date/affiliation matching only when stable identifiers are absent
6. Manual review for unresolved or multiple plausible matches

### 11.2 Name normalization

Preserve exact display names. Generate matching keys separately:

- Unicode NFKC normalization;
- case folding;
- punctuation normalization;
- whitespace collapse;
- optional diacritic-stripped key;
- initial expansion/contraction forms;
- surname particles handled conservatively;
- alternate transliterations stored as explicit variants.

Never discard the original spelling.

### 11.3 Identity score

A possible deterministic score:

| Evidence | Weight |
|---|---:|
| Exact Nobel ID bridge | +1.00 |
| Exact ORCID match | +1.00 |
| Exact VIAF/ISNI/LCNAF/GND match | +0.90 |
| Birth date exact | +0.35 |
| Death date exact | +0.25 |
| Full normalized name exact | +0.25 |
| Affiliation overlap | +0.20 |
| Research-topic overlap | +0.15 |
| Country overlap | +0.05 |
| Conflicting birth year | −0.80 |
| Conflicting death year | −0.60 |
| Clearly different discipline | −0.30 |
| Name-only match | maximum total confidence 0.55 |

Suggested thresholds:

- `>= 0.90`: auto-verify
- `0.70–0.89`: accept provisionally and review if consequential
- `0.50–0.69`: needs review
- `< 0.50`: unresolved or rejected

The exact formula should be configurable and validated against a regression set.

---

## 12. Candidate discovery

### 12.1 Query strategy per laureate

For each resolved laureate:

1. Query Wikidata by QID for author and editor relationships.
2. Query Open Library by verified author ID, or resolve author candidates.
3. Query Google Books using several exact and variant name forms.
4. Query OpenAlex by ORCID or verified OpenAlex author ID.
5. Query Crossref using stable IDs or constrained bibliographic searches.
6. Parse a relevant Wikipedia bibliography section when available.
7. Query WorldCat or national-library adapters when configured.
8. Add manually curated candidate records.

Do not rely on a single broad name query. Name variants should be scored and results reconciled.

### 12.2 Candidate query variants

Generate controlled queries such as:

- exact full name;
- full name without middle names;
- initials plus surname;
- native-script name;
- alternate transliteration;
- married or former name;
- name plus known technical subject;
- name plus known publisher only as a fallback.

Every query variant must be logged so a reviewer can understand why a candidate appeared.

### 12.3 Candidate rejection heuristics

Automatically lower confidence when:

- the laureate name appears only in the title;
- the source labels the laureate as subject;
- the publication date precedes the laureate’s plausible writing age;
- the book’s author has incompatible birth/death or affiliation data;
- an exact identifier points to a different authority record;
- the contributor string contains only “foreword by,” “introduction by,” or “interview with”;
- the title is a biography pattern such as `Life of <laureate>` and no author role is present;
- the record is a journal article or chapter;
- the record is a duplicate edition masquerading as a work.

Do not permanently delete these records. Mark them rejected with evidence.

---

## 13. Normalization

### 13.1 Titles

Store:

- exact source title;
- subtitle separately when possible;
- normalized comparison title;
- original-language title;
- translated title;
- title variants.

Suggested comparison normalization:

1. Unicode normalization
2. case folding
3. normalize punctuation and whitespace
4. convert Roman numerals only in tightly controlled volume contexts
5. optionally remove leading articles for a secondary key
6. retain mathematical symbols and meaningful scientific notation
7. do not remove stop words from the canonical key
8. create a separate “series-stripped” key for edition matching

### 13.2 ISBNs

- remove hyphens and spaces for comparison;
- validate checksums;
- convert ISBN-10 to corresponding ISBN-13 when possible;
- retain source formatting separately;
- treat ISBN as edition-level evidence;
- flag invalid source ISBNs rather than silently repairing uncertain digits.

### 13.3 Dates

Support:

- full dates;
- year-month;
- year only;
- ranges;
- circa dates;
- unknown dates.

Store raw source text plus parsed lower/upper bounds if useful.

### 13.4 Contributor roles

Normalize role strings from every source. A contributor without an explicit role should be `unknown`, not automatically `author`, unless the source’s field semantics guarantee authorship.

### 13.5 Languages

Use BCP 47 or ISO 639-compatible normalized codes while preserving source labels. A translation is normally an edition of the same canonical work unless the content differs substantially.

---

## 14. Edition and work reconciliation

### 14.1 Edition matching hierarchy

Merge edition records when supported by:

1. exact normalized ISBN-13;
2. exact normalized ISBN-10 or ISBN-10/13 conversion;
3. exact OCLC or source-linked edition ID;
4. exact DOI;
5. explicit Wikidata `P629` and shared edition identifiers;
6. exact normalized title + contributor set + publisher + publication year;
7. strong fuzzy title + contributor set + compatible date/language;
8. manual merge.

Never merge solely because titles are similar.

### 14.2 Work clustering hierarchy

Cluster editions into a canonical work using:

1. explicit work-edition relationships from Wikidata or Open Library;
2. shared source work IDs;
3. normalized original title + author set;
4. translated-title relationships;
5. edition statements;
6. publication chronology;
7. series and volume metadata;
8. manual decisions.

### 14.3 Multi-volume works

Represent both levels when useful:

```text
Series-level work: Course of Theoretical Physics
  Volume work: Mechanics
  Volume work: The Classical Theory of Fields
  ...
```

A laureate’s contribution may differ by volume. Do not automatically assign authorship of every volume in a series to every series author.

### 14.4 Revised and retitled works

Create separate canonical works only when the intellectual content is substantially different or bibliographic authorities treat them as separate works. Otherwise link revised editions to the same work and record the edition statement.

### 14.5 Fuzzy matching constraints

Use fuzzy matching only to propose clusters. Auto-merge requires multiple agreeing features.

Example scoring:

```text
0.45 title similarity
0.20 contributor-set similarity
0.10 publication-year compatibility
0.10 publisher compatibility
0.10 language/translation evidence
0.05 series/volume compatibility
```

Suggested behavior:

- `>= 0.92`: auto-merge when no hard conflict exists
- `0.82–0.91`: review proposed merge
- `< 0.82`: keep separate

A conflicting ISBN-to-title mapping, incompatible contributor set, or explicit separate-work link should block auto-merge.

---

## 15. Classification

### 15.1 Deterministic first pass

Classification should initially use deterministic features:

- source work type;
- title keywords;
- subjects/categories;
- publisher and series;
- description terms;
- audience labels;
- DOI type;
- OpenAlex topics;
- library classification;
- page count and edition pattern only as weak features.

Examples of technical indicators:

- “treatise”
- “principles of”
- “theory of”
- “quantum”
- “thermodynamics”
- “biochemistry”
- “molecular”
- “clinical”
- “handbook”
- “textbook”
- “lectures on”
- “advanced”
- “graduate”
- “monograph”
- established academic series

Examples of nontechnical indicators:

- autobiography
- memoir
- letters
- correspondence
- reminiscences
- adventures
- fiction
- novel

Keyword rules are not sufficient by themselves. *Surely You’re Joking, Mr. Feynman!* should remain in the full bibliography but classify as memoir/anecdotal writing with a low technicality score.

### 15.2 Optional LLM-assisted pass

An LLM may classify ambiguous works using only supplied metadata:

- title;
- subtitle;
- subjects;
- publisher;
- description;
- table of contents when legally and technically available;
- source classifications.

The prompt must demand structured JSON and include the allowed taxonomy. Store:

- model name and version;
- prompt version;
- input hash;
- output;
- confidence;
- explanation.

LLM output never overrides a manual decision and should not create a book candidate that no bibliographic source supports.

### 15.3 Manual classification

A reviewer can set:

- class;
- score;
- audience;
- inclusion state;
- reason.

Manual classifications take precedence and remain stable across reruns.

---

## 16. Confidence scoring

Compute separate confidence values for:

1. identity resolution;
2. person-work relationship;
3. edition metadata;
4. work clustering;
5. classification;
6. overall exported record.

### 16.1 Relationship confidence example

```text
+0.55 authoritative structured author/editor field
+0.20 second independent source agrees
+0.10 stable authority-ID linkage
+0.10 exact title-page or publisher confirmation
+0.05 compatible dates and discipline
-0.40 contributor role unclear
-0.50 source says subject rather than author
-0.35 name collision risk
-0.25 only one weak source
```

Clamp to `0.0–1.0`.

### 16.2 Review thresholds

- `>= 0.90`: eligible for automatic inclusion
- `0.75–0.89`: include provisionally, highlight in audit
- `0.50–0.74`: review required
- `< 0.50`: excluded from default export unless manually approved

Edited books should require explicit editor evidence; otherwise they remain under review.

---

## 17. Manual review workflow

### 17.1 MVP review format

Generate `review_queue.csv` with:

- laureate;
- Nobel ID;
- candidate title;
- candidate role;
- source count;
- source URLs;
- publication year;
- identifiers;
- proposed work cluster;
- proposed classification;
- confidence;
- warning flags;
- reviewer decision;
- reviewer reason.

Import decisions into YAML or the database with a stable candidate key.

### 17.2 Stable review keys

A stable key might be:

```text
<laureate_nobel_id>::<normalized_title>::<earliest_year>::<role>
```

Prefer stable source IDs or ISBNs when available. Handle key migrations explicitly when records merge.

### 17.3 Review actions

- accept;
- reject;
- change role;
- merge with work;
- split from work;
- classify;
- mark as translation;
- mark as volume;
- mark as only foreword/introduction;
- request further evidence;
- verify laureate identity;
- add a missing work manually.

### 17.4 Later review UI

A later FastAPI interface may show:

- candidates grouped by laureate;
- side-by-side source evidence;
- proposed duplicate clusters;
- title/author/date conflicts;
- one-click accept/reject/merge;
- progress by category and year;
- coverage alerts.

The UI must write the same manual-override format used by the CLI.

---

## 18. CLI design

Proposed commands:

```bash
nobel-books init
nobel-books db upgrade

nobel-books laureates sync
nobel-books laureates list
nobel-books identities resolve
nobel-books identities review-export

nobel-books discover --source wikidata
nobel-books discover --source openlibrary
nobel-books discover --source google-books
nobel-books discover --all
nobel-books discover --laureate-id 123

nobel-books normalize
nobel-books reconcile editions
nobel-books reconcile works
nobel-books classify
nobel-books score

nobel-books review export
nobel-books review import data/manual/review_decisions.csv
nobel-books audit

nobel-books export csv
nobel-books export json
nobel-books export markdown
nobel-books export all

nobel-books pipeline run --profile mvp
nobel-books pipeline resume <run-id>
nobel-books status
```

Useful options:

```text
--category physics|chemistry|medicine
--year-from
--year-to
--laureate-id
--source
--refresh
--offline
--max-workers
--rate-limit
--include-xpac
--include-supplemental-roles
--min-confidence
```

The default worker count should be conservative. Each adapter owns its own rate limit.

---

## 19. Configuration

Example `config/default.yaml`:

```yaml
project:
  contact_email: ""
  user_agent: "nobel-laureate-books/0.1 (+contact email required)"
  database_url: "sqlite:///data/nobel_books.sqlite3"

categories:
  - physics
  - chemistry
  - medicine

sources:
  nobel:
    enabled: true
    base_url: "https://api.nobelprize.org/2.1"
  wikidata:
    enabled: true
    endpoint: "https://query.wikidata.org/sparql"
    requests_per_second: 0.5
  openlibrary:
    enabled: true
    base_url: "https://openlibrary.org"
    requests_per_second: 0.5
  google_books:
    enabled: true
    api_key_env: "GOOGLE_BOOKS_API_KEY"
    requests_per_second: 2.0
    max_results_per_query: 400
  openalex:
    enabled: true
    api_key_env: "OPENALEX_API_KEY"
    include_xpac: false
  crossref:
    enabled: true
    mailto_env: "CROSSREF_MAILTO"
  wikipedia:
    enabled: true
    language: "en"
  worldcat:
    enabled: false
    api_key_env: "WORLDCAT_API_KEY"

matching:
  auto_merge_edition_threshold: 0.92
  review_merge_threshold: 0.82
  auto_identity_threshold: 0.90

review:
  auto_include_relationship_threshold: 0.90
  provisional_include_threshold: 0.75

exports:
  output_dir: "data/exports"
  include_supplemental_roles: false
  include_rejected: false
```

Secrets belong in `.env`, never in committed configuration.

---

## 20. Caching, rate limiting, and reproducibility

### 20.1 HTTP client policy

Create one shared client layer with:

- descriptive User-Agent;
- source-specific authentication;
- timeout;
- exponential backoff with jitter;
- `Retry-After` support;
- source-specific concurrency limits;
- ETag and `If-Modified-Since` support where available;
- normalized error types;
- raw-response storage;
- request fingerprinting.

### 20.2 Cache key

A cache key should include:

- HTTP method;
- normalized URL;
- normalized query parameters;
- request body hash;
- relevant headers;
- adapter version.

Do not include API keys in logs or cache filenames.

### 20.3 Refresh policy

Modes:

- `offline`: use cache only;
- `normal`: use fresh-enough cache and conditional requests;
- `refresh`: refetch;
- `immutable`: use a pinned run snapshot.

### 20.4 Idempotence

Use upserts keyed by stable source IDs. A rerun should update evidence and canonical selections without duplicating entities.

### 20.5 Source drift

Store parser version and raw responses. If an API changes, old responses can be reparsed without refetching.

---

## 21. Exports

### 21.1 `works.csv`

One row per laureate-work relationship:

- laureate_name
- nobel_api_id
- prize_categories
- prize_years
- preferred_title
- original_title
- first_publication_year
- role
- coauthors_or_coeditors
- work_type
- technicality_score
- audience_level
- review_status
- relationship_confidence
- overall_confidence
- edition_count
- languages
- isbn13s
- dois
- oclc_numbers
- wikidata_qid
- openlibrary_work_id
- source_count
- source_urls
- notes

A coauthored work appears once for each laureate associated with it in the flat CSV. The JSON export should represent the relationship without duplicating the work object.

### 21.2 `editions.csv`

One row per edition:

- canonical_work_id
- edition_title
- language
- publication_date
- publisher
- edition_statement
- format
- ISBN-10
- ISBN-13
- DOI
- OCLC
- source IDs
- confidence
- source URLs

### 21.3 `evidence.csv`

One row per assertion or evidence item:

- target record;
- field;
- asserted value;
- source;
- source entity ID;
- source URL;
- retrieval date;
- reliability class;
- confidence;
- selected/contradicted flags.

### 21.4 `bibliography.json`

Nested structure:

```json
{
  "generated_at": "ISO-8601 timestamp",
  "pipeline_run": "run-id",
  "laureates": [
    {
      "nobel_api_id": "123",
      "name": "Example Laureate",
      "prizes": [],
      "identifiers": {},
      "coverage": {},
      "works": [
        {
          "id": "uuid",
          "title": "Example Work",
          "roles": [],
          "classification": {},
          "editions": [],
          "evidence": []
        }
      ]
    }
  ]
}
```

### 21.5 Markdown report

Produce:

```text
# Nobel Laureate Books

## Physics
### Laureate Name
#### Technical works
#### Popular science
#### Memoir and essays
#### Edited works
#### Unresolved candidates

## Chemistry
...

## Physiology or Medicine
...
```

Each listed work should include year, role, classification, confidence, and compact source links.

### 21.6 Coverage report

Include:

- total laureates by category;
- unique laureates;
- resolved/unresolved identities;
- laureates with zero, one, or multiple candidate works;
- verified works;
- unreviewed candidates;
- source contribution counts;
- duplicate clusters;
- classification distribution;
- technical works by category and decade;
- review progress;
- errors and skipped adapters;
- changes from the prior run.

---

## 22. Audit and quality assurance

### 22.1 Regression laureates

Maintain hand-checked regression bibliographies for a small, difficult sample:

- **Marie Curie:** multiple target-category prizes, older multilingual records
- **Richard Feynman:** technical texts plus memoir/anecdotal books
- **Lev Landau:** multi-volume technical series and coauthorship
- **Linus Pauling:** target and non-target Nobel prizes, many books
- **Frederick Sanger:** multiple prizes in one category
- **Albert Einstein:** numerous editions, translations, popular and technical works
- **A modern medicine laureate with few or no books:** tests true-empty versus missing coverage

Do not hardcode these bibliographies into production logic. Use them as golden test data and audit references.

### 22.2 Invariants

Examples:

- every exported laureate exists in the Nobel source snapshot;
- organizations are absent from the target export;
- each prize award belongs to a target category;
- a laureate appears once in the person table;
- a canonical work may have many editions;
- a validated ISBN belongs to no more than one edition unless explicitly documented;
- every exported relationship has at least one evidence record or manual override;
- rejected relationships do not appear in the default export;
- a manual decision is never silently replaced;
- all source URLs and retrieval timestamps are retained;
- no API key appears in logs or exports.

### 22.3 Differential audit

On each full run, compare with the previous accepted dataset:

- added works;
- removed works;
- changed roles;
- changed canonical titles;
- merged or split works;
- changed classification;
- lost identifiers;
- candidate-count changes per laureate.

Require explicit review for destructive changes to previously verified records.

---

## 23. Testing strategy

### 23.1 Unit tests

Test:

- name normalization;
- ISBN validation and conversion;
- date parsing;
- title normalization;
- role normalization;
- identity scoring;
- edition matching;
- work clustering;
- confidence calculations;
- classification rules;
- override precedence.

### 23.2 Adapter tests

Use saved fixtures and `respx`:

- successful response;
- pagination;
- empty result;
- malformed record;
- 429 rate limit;
- 500 retry;
- timeout;
- schema drift;
- duplicate source IDs;
- partial metadata.

### 23.3 Contract tests

Optional tests against live APIs, marked separately:

```bash
pytest -m contract
```

Contract tests should be few, rate-limited, and never required for normal CI.

### 23.4 Integration tests

Run an end-to-end pipeline on a small fixed laureate set using recorded responses.

Verify:

- deterministic database output;
- stable merge decisions;
- correct provenance;
- expected review flags;
- valid exports.

### 23.5 Golden tests

Compare generated Markdown/CSV fragments for regression laureates with reviewed fixtures. Normalize timestamps and run IDs before comparison.

### 23.6 Property-based tests

Consider Hypothesis for:

- ISBN transformations;
- normalization idempotence;
- merge symmetry;
- no data loss when candidate order changes;
- stable serialization.

### 23.7 CI

CI should run:

```bash
ruff check .
ruff format --check .
mypy src
pytest --cov=src/nobel_books --cov-report=term-missing
```

Do not make live API calls in ordinary CI.

---

## 24. Logging and observability

Use structured logs with:

- run ID;
- stage;
- laureate Nobel ID;
- adapter;
- request fingerprint;
- cache hit/miss;
- record counts;
- retry count;
- warning code;
- elapsed time.

Useful warning codes:

- `IDENTITY_AMBIGUOUS`
- `IDENTITY_UNRESOLVED`
- `SOURCE_RATE_LIMITED`
- `SOURCE_SCHEMA_CHANGED`
- `ZERO_BOOK_CANDIDATES`
- `ROLE_UNCLEAR`
- `POSSIBLE_BIOGRAPHY_FALSE_POSITIVE`
- `INVALID_ISBN`
- `EDITION_MERGE_AMBIGUOUS`
- `WORK_MERGE_AMBIGUOUS`
- `SOURCE_CONTRADICTION`
- `MANUAL_OVERRIDE_STALE`

Generate a machine-readable run summary.

---

## 25. Legal, licensing, and ethical constraints

- Follow every source’s terms of use and rate limits.
- Prefer APIs and data dumps over HTML scraping.
- Store bibliographic metadata and provenance, not copyrighted full text.
- Descriptions may be copyrighted; retain only what is necessary and record the source. Consider omitting long descriptions from public exports.
- Do not redistribute restricted WorldCat or proprietary metadata beyond permitted use.
- Preserve attribution required by each source.
- Wikidata structured data is available under CC0, but linked page text may have different terms.
- Wikipedia text is licensed separately and should be attributed when reproduced.
- API keys and contact details must not be committed.
- The system should make uncertain automated decisions visible rather than presenting them as facts.

---

## 26. Implementation milestones

Each milestone should end with passing tests, updated documentation, and a usable command.

### Milestone 0 — Repository scaffold

Implement:

- Python project with `uv`;
- CLI skeleton;
- configuration loader;
- structured logging;
- SQLAlchemy and Alembic;
- test and lint configuration;
- `AGENTS.md`;
- `.env.example`.

Acceptance criteria:

- `nobel-books --help` works;
- database migration creates an empty schema;
- lint, type checking, and unit tests pass;
- no live API dependency in tests.

### Milestone 1 — Nobel laureate ingestion

Implement:

- Nobel API adapter;
- raw-response cache;
- laureate and prize tables;
- target-category filtering;
- organization exclusion;
- pagination;
- rerun-safe upserts.

Acceptance criteria:

- all API-returned target laureates are imported;
- multi-prize laureates remain one person with multiple awards;
- a run summary reports counts by category and year;
- fixture tests cover pagination and duplicate prize records.

### Milestone 2 — Wikidata identity resolution

Implement:

- Nobel ID `P8024` lookup;
- Wikidata QID storage;
- identifier and name-variant ingestion;
- identity confidence;
- unresolved/ambiguous report.

Acceptance criteria:

- exact P8024 matches auto-verify;
- zero or multiple matches are reviewed rather than guessed;
- sample laureates resolve deterministically;
- raw SPARQL results are cached.

### Milestone 3 — Wikidata book discovery

Implement:

- authored and edited candidate queries;
- edition/work links;
- identifier extraction;
- broad instance-type retrieval;
- source records and assertions.

Acceptance criteria:

- candidates retain work-versus-edition distinctions;
- author and editor roles remain distinct;
- every parsed field has source provenance;
- no canonical merge occurs in the adapter.

### Milestone 4 — Open Library integration

Implement:

- author resolution;
- author-work pagination;
- work and edition retrieval;
- identifier enrichment;
- User-Agent and low-rate request policy.

Acceptance criteria:

- resolved author IDs are confidence-scored;
- editions link to Open Library works;
- API responses are cached;
- bulk behavior is avoided;
- false identity candidates appear in review output.

### Milestone 5 — Google Books integration

Implement:

- controlled author query variants;
- pagination with `startIndex`;
- maximum-results safeguards;
- book-only filtering;
- volume metadata parsing.

Acceptance criteria:

- query variants are logged;
- results are treated as candidates;
- duplicate volume IDs are idempotent;
- ambiguous contributor relationships are flagged.

### Milestone 6 — Normalization and edition reconciliation

Implement:

- title, date, language, identifier, and role normalization;
- ISBN validation;
- edition merge proposals;
- merge confidence and conflict blocking.

Acceptance criteria:

- exact ISBN matches merge;
- invalid ISBNs are flagged;
- fuzzy matches cannot override hard conflicts;
- merge decisions are deterministic regardless of input order.

### Milestone 7 — Canonical work clustering

Implement:

- explicit source work links;
- translation and edition grouping;
- multi-volume representation;
- work merge/split review queue.

Acceptance criteria:

- editions cluster into canonical works;
- translations remain visible;
- series and volumes can coexist;
- reviewed split/merge overrides persist.

### Milestone 8 — OpenAlex and Crossref enrichment

Implement:

- identifier-first OpenAlex author resolution;
- book-type works;
- optional XPAC mode;
- Crossref type discovery;
- DOI enrichment;
- polite-pool contact configuration.

Acceptance criteria:

- technical books can be added or corroborated;
- general books are not expected to come from these adapters;
- source-specific limitations are visible in audit reports.

### Milestone 9 — Wikipedia fallback parser

Implement:

- section discovery via MediaWiki Action API;
- configurable bibliography heading matching;
- section retrieval;
- citation/list parsing;
- page revision provenance.

Acceptance criteria:

- parsing failures do not stop the pipeline;
- candidates are low-confidence until corroborated;
- only relevant sections are fetched;
- revision IDs are stored.

### Milestone 10 — Classification and confidence

Implement:

- taxonomy;
- deterministic rules;
- technicality and audience scores;
- relationship and overall confidence;
- review thresholds.

Acceptance criteria:

- Feynman-like technical and memoir works separate correctly in golden tests;
- classification reasons are human-readable;
- low-confidence classifications enter review;
- manual classification wins.

### Milestone 11 — Review workflow and exports

Implement:

- review CSV export/import;
- manual override application;
- works, editions, and evidence CSVs;
- JSON export;
- Markdown bibliography;
- coverage report.

Acceptance criteria:

- accepted and rejected decisions survive reruns;
- every exported record has evidence;
- output separates technical and nontechnical classes;
- canonical works and editions are separately exportable.

### Milestone 12 — Audit hardening

Implement:

- regression bibliography suite;
- differential reports;
- suspicious-gap alerts;
- source contribution analysis;
- stale override detection.

Acceptance criteria:

- previously verified records cannot disappear silently;
- zero-book laureates are explicitly audited;
- the project reports what remains incomplete.

### Milestone 13 — Optional WorldCat and review UI

Implement only after the data model is stable.

Acceptance criteria:

- WorldCat adapter is disabled cleanly without credentials;
- no HTML scraping;
- UI writes standard manual overrides;
- CLI remains fully functional.

---

## 27. Definition of done

A first serious research release is complete when:

1. All current target-category Nobel laureates are imported from the official API.
2. At least 98% have a verified Wikidata identity or an explicit manual resolution.
3. Every laureate has been queried against all enabled MVP sources.
4. Every zero-candidate laureate has a documented audit disposition.
5. Canonical works and editions are separated.
6. Every default-included work has:
   - a verified laureate relationship;
   - a contribution role;
   - a work classification;
   - a confidence score;
   - at least one source record;
   - provenance.
7. All ambiguous candidates are in a review queue.
8. Manual decisions survive complete rebuilds.
9. CSV, JSON, Markdown, and coverage exports are reproducible from a pinned pipeline run.
10. Regression bibliographies pass.
11. A limitations section accompanies every public export.

A stronger “audited bibliography” release requires human review of every laureate, not merely every low-confidence candidate.

---

## 28. Suggested MVP profile

The MVP should enable:

- Nobel API
- Wikidata
- Open Library
- Google Books
- manual overrides
- deterministic normalization
- canonical work/edition separation
- CSV, JSON, and Markdown exports
- coverage and review reports

Defer:

- OpenAlex
- Crossref
- Wikipedia parsing
- WorldCat
- national libraries
- web UI
- LLM classification

This scope is large enough to test the central research method while remaining implementable in discrete Codex sessions.

---

## 29. Suggested first Codex prompt

Use the following after placing this file at `DESIGN.md` in a new repository:

```text
Read DESIGN.md in full.

Implement Milestone 0 only. Do not begin later milestones.

Requirements:
1. Create the repository structure described in DESIGN.md, simplifying only where a directory would otherwise be empty.
2. Use Python 3.12+, uv, Typer, SQLAlchemy 2.x, Alembic, Pydantic, httpx, pytest, respx, Ruff, and mypy.
3. Add a working `nobel-books --help` command and `nobel-books status` command.
4. Add configuration loading from YAML plus environment variables, with no secrets committed.
5. Add structured logging and a shared typed error hierarchy.
6. Create the initial database migration for `pipeline_run` and `source_fetch`; later domain tables may remain for later milestones unless needed now.
7. Add unit tests and ensure no test calls a live external service.
8. Add README setup and development instructions.
9. Add AGENTS.md that instructs future agents to implement one milestone at a time, preserve raw provenance, avoid HTML scraping when an API exists, and run all checks before completion.
10. Run formatting, linting, type checking, and tests. Fix all failures.
11. Summarize changed files, commands run, and any deviations from DESIGN.md.

Do not implement Nobel API ingestion yet.
```

Suggested second prompt:

```text
Read DESIGN.md and the current repository.

Implement Milestone 1 only: Nobel laureate ingestion.

Before coding, inspect the existing architecture and migrations. Preserve existing conventions. Use fixture-based tests; normal tests must not call the live Nobel API. Implement raw response caching, target-category filtering, organization exclusion, pagination, idempotent upserts, and a concise run summary. Add or update migrations and documentation. Run all checks and fix failures. Do not begin Wikidata integration.
```

---

## 30. Questions to resolve during implementation

These questions do not block Milestone 0 or 1, but the project should record decisions:

1. Should edited books appear in the same default list as authored books or in a separate default section?
2. Should independently published lecture notes count as books when they lack an ISBN?
3. At what point does a pamphlet become a monograph for project purposes?
4. Should translations be displayed under the original work only, or also as separate visible entries?
5. Should substantially revised textbooks remain one canonical work?
6. How should collected papers published by later editors be represented?
7. Should a laureate’s role as series editor count?
8. Should books written before the author became a scientist or outside the laureate’s research field receive special labels?
9. Should posthumous compilations assembled from the laureate’s writing count as authored books?
10. What manual-review standard is required before using the word “complete”?

Recommended defaults:

- separate authored and edited sections;
- include lecture notes only when cataloged and independently published;
- retain pamphlets as supplemental unless they are clearly treated as monographs;
- group translations under canonical works;
- keep revised textbooks together unless retitled or substantially reconceived;
- list posthumous compilations as supplemental and identify the compiler/editor;
- exclude series-editor-only relationships from the default list;
- classify by content, not career period;
- reserve “complete” for a human-audited release.

---

## 31. Known risks and mitigations

| Risk | Mitigation |
|---|---|
| Name collision produces books by another person | Identifier-first resolution, date/affiliation checks, review thresholds |
| Wikidata omits works | Multi-source discovery and fallback bibliography parsing |
| Google Books returns noisy matches | Candidate-only status, role verification, strict confidence |
| Old books lack ISBNs | Title/author/date/publisher reconciliation and library authority IDs |
| Editions inflate counts | Canonical work and edition separation |
| Translations appear as distinct works | Explicit translation/work clustering |
| Edited volumes appear authored | Role normalization and review |
| Technical classification is subjective | Taxonomy, score, reason, confidence, manual override |
| Source APIs change | Raw-response snapshots, parser versioning, contract tests |
| Rate limiting or blocking | User-Agent, caching, conservative concurrency, retries |
| Manual decisions become stale after merges | Stable override keys and stale-override audit |
| “Zero books” is mistaken for complete absence | Suspicious-gap audit and coverage tiers |
| Proprietary metadata is redistributed improperly | Source-specific export policy and restricted adapters |
| Project scope grows indefinitely | Milestone gates and MVP profile |

---

## 32. Documentation references

Official or primary documentation consulted for this design:

- Nobel Prize developer zone:  
  https://www.nobelprize.org/about/developer-zone-2/

- Nobel Prize API terms:  
  https://www.nobelprize.org/about/terms-of-use-for-api-nobelprize-org-and-data-nobelprize-org/

- Nobel Prize linked-data specification:  
  https://data.nobelprize.org/specification/

- Nobel Laureate API ID in Wikidata (`P8024`):  
  https://www.wikidata.org/wiki/Property:P8024

- Wikidata Query Service manual:  
  https://www.mediawiki.org/wiki/Wikidata_Query_Service/User_Manual

- Wikidata WikiProject Books data model:  
  https://www.wikidata.org/wiki/Wikidata:WikiProject_Books

- MediaWiki Action API:  
  https://www.mediawiki.org/wiki/API:Main_page

- MediaWiki parsing API:  
  https://www.mediawiki.org/wiki/API:Parsing_wikitext

- Open Library APIs:  
  https://openlibrary.org/developers/api

- Open Library Search API:  
  https://openlibrary.org/dev/docs/api/search

- Open Library data dumps:  
  https://openlibrary.org/developers/dumps

- Google Books API volume search:  
  https://developers.google.com/books/docs/v1/reference/volumes/list

- OpenAlex developer documentation:  
  https://developers.openalex.org/

- OpenAlex work types:  
  https://developers.openalex.org/api-reference/work-types

- Crossref REST API:  
  https://www.crossref.org/documentation/retrieve-metadata/rest-api/

- WorldCat Search API v2 documentation:  
  https://developer.api.oclc.org/wcv2

- OCLC API eligibility:  
  https://www.oclc.org/developer/support/eligibility.en.html

---

## 33. Final design principle

The database should never merely answer:

> “What titles did an API return for this name?”

It should answer:

> “What distinct books can be responsibly attributed to this Nobel laureate, what role did the laureate have, which editions represent each work, how technical is the work, what evidence supports each claim, and what remains uncertain?”

That distinction is what makes the result suitable as a serious bibliography rather than a scraped title list.
