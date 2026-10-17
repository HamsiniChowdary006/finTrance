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

## P0-b calculator and scanner plan

1. Precheck SQLite facts and print company/metric/quarter coverage; use only real facts for
   live analysis and clearly labelled synthetic fixtures for offline tests.
2. Build provenance-carrying quarterly series and deterministic metric formulas, selecting
   metrics by company type from YAML.
3. Add runtime peer comparison, corporate/statistical break detection, and non-comparable
   windows.
4. Declare R1-R4 thresholds in YAML and implement generic rule evaluation and scoring.
5. Add `analyze` CLI output/JSON, then run the complete offline suite, Ruff, and the
   company-name guard. No real-data conclusion is valid when the facts table is empty.

## P0-c security and evidence pipeline plan

1. Harden repository hygiene, secret handling, network/file boundaries, logging, and CI;
   audit tracked files/history and commit this security slice before feature work.
2. Add provenance-first hypothesis, investigation, red-team, grading, orchestration, and
   rendering contracts with deterministic offline fallbacks and no investment advice.
3. Add a complete offline `run` path over clearly labelled SYNTHETIC fixtures, then validate
   tests, lint, name/secret scans, and tracked-artifact hygiene. Real findings remain absent
   when the evidence database is empty.

## P0-c completion

- [x] Add root-contained manual ingestion and quote-validated CSV fact import.
- [x] Wire stored facts through compute, scan, hypothesis, investigation, red-team, grading,
  and rendering with explicit stage counts and skip reasons.
- [x] Preserve deterministic no-LLM execution and honest empty-corpus output.
- [ ] P1: verified exchange/IR collection, richer event timeline, funding-mix and dependency
  angles, and dashboard visual polish.
