# Working agreement

Read `DESIGN.md` before changing architecture or research behavior.

- Implement one numbered milestone at a time; do not begin later milestones implicitly.
- Preserve raw responses and field-level provenance before normalization or reconciliation.
- Prefer documented APIs and downloadable datasets; do not scrape HTML when an API exists.
- Keep pipeline stages idempotent, resumable, and independently testable.
- Never commit credentials, tokens, local databases, caches, or generated exports.
- Tests must not depend on live external services.
- Before completion run formatting, linting, type checking, and the full test suite.
- Document material deviations from the design and update setup instructions when commands change.

