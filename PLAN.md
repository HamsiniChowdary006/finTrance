# P0-a Foundation Plan

1. Scaffold a Python 3.11+ package, configuration, storage, tests, and documentation layout.
2. Define typed domain schemas and an evidence-first SQLite DAO.
3. Implement deterministic period/unit/quote/bounds/alias validators before any LLM use.
4. Add a provider-neutral, cached structured-JSON LLM boundary with an explicit budget.
5. Add rate-limited, cached collectors. Start with only public endpoint patterns that can
   be verified; manual-drop ingestion remains available when a source is unavailable.
6. Add type-driven profiling and an honest extraction CLI that reports gaps and coverage.
7. Run offline tests, Ruff, and the company-name guard. Live company runs require names and
   network access supplied by the operator; no company-specific fixture or result is checked in.

## Risks and source order

Exchange-hosted filings are preferred, followed by company investor-relations pages, then
manual drops. Exchange APIs and PDF layouts can change, so every response is cached and source
gaps are recorded rather than hidden. No endpoint is treated as verified until an actual
request succeeds and its response shape is documented in `docs/DATA_SOURCES.md`.
