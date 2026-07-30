# Operations

## Routine offline validation

```bash
uv sync --locked --dev
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
```

Ordinary tests and CI use fixtures and do not call live APIs.

## Review and accepted snapshots

Export/import review CSVs with `nobel-books review export` and
`nobel-books review import`. To use the local interface:

```bash
uv run nobel-books review serve
```

The default bind address is `127.0.0.1`. The UI has no authentication; do not
bind it to a public or shared interface without adding an authenticated reverse
proxy. Both interfaces write the same durable `ManualOverride` rows.

Run `nobel-books audit run` after a full pipeline. Promote an audit JSON file to
an accepted baseline only after human review, then pass that file with
`--previous` on later runs. Exit status 2 means a verified record was removed or
destructively changed. The command never promotes its own output.

## WorldCat

WorldCat is disabled by default. Access requires an eligible OCLC subscription
and an OAuth access token authorized for WorldCat Search API 2.0. Set
`sources.worldcat.enabled: true` only when configured, and supply the token in
`WORLDCAT_ACCESS_TOKEN`. Never commit tokens or place them in command arguments.

The adapter uses the structured v2 endpoint, sends the token only in an
Authorization header, does not follow redirects, and never scrapes WorldCat
HTML. Respect OCLC terms and do not redistribute restricted metadata in public
exports.

## Recovery

Raw response caches and the SQLite database are local, ignored artifacts. Back
up the database and accepted audit snapshot before full rebuilds. Manual
overrides are stored in the database, so export the review CSV or copy the
database before replacing it.
