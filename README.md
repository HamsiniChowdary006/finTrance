# finTrance

Evidence-first foundation for public Indian banking and NBFC research.

## Setup

Use Python 3.11+, create a virtual environment, and install `pip install -e ".[dev]"`.
Copy `.env.example` to `.env` and set provider credentials only through environment variables.

## Offline run

Place public filings in `store/manual_drop/`, then run:

```text
python -m agent.cli extract --company "a company" --no-llm
```

The current foundation deliberately reports missing coverage when no verified documents are
available. It does not fabricate exchange symbols, endpoint URLs, values, or evidence.

## One-command launcher

From a fresh checkout:

```text
python run_demo.py --dry-run
python run_demo.py --synthetic --no-app
python run_demo.py
```

The launcher installs the editable project only when required imports are missing,
loads `.env` without printing credentials, ingests each folder under
`store/manual_drop/<ticker>/`, writes `out/<ticker>/report.md`, `report.json`,
and `run_log.json`, and opens Streamlit on the first available port at or after
8501. Use `--no-app` in automation. `--reingest` processes unchanged files again,
`--ticker X` or `--company "Display name"` selects one company, and
`--peers A,B` overrides peer discovery.

`--synthetic` is an explicitly labelled offline demonstration only. It is
available when the manual-drop directory is empty and must not be interpreted
as a real company finding. Without real files, the launcher stops with an
actionable message rather than fabricating data. `--check` runs pytest, Ruff,
the company-name guard, secret scan, and artifact check in that order, stopping
at the first failure. `--dry-run` performs no installation, writes, or browser
launch.

## Checks

```text
pytest
ruff check .
python scripts/check_no_company_names.py
```

## P0-b calculator and scanner

`python -m agent.cli analyze --company "runtime name" --peers "runtime peer 1,runtime peer 2" --json out.json`
uses only facts already stored in SQLite. With an empty facts table it reports that only
synthetic validation was possible and does not manufacture findings.

Implemented deterministic formulas are: YoY loan growth; GNPA and NNPA percentages; PCR =
provisions on NPA / gross NPA; annualised slippage ratio; credit cost =
annualised (provisions + write-offs) / average advances; write-off-adjusted GNPA =
(GNPA + trailing-four-quarter write-offs) / (advances + trailing-four-quarter write-offs);
Stage 2/3 percentages; CASA ratio; and credit-deposit ratio. Missing inputs produce NaN
with a reason and every computed result carries source fact IDs.

R1-R4 thresholds are declared in `config/anomaly_rules.yaml`. Rules are generic and
synthetic tests are never presented as real findings.

## Security

See [SECURITY.md](SECURITY.md) for secret handling, SSRF/path protections, artifact policy,
and the five-command pre-push checklist. `python -m agent.cli run --company "runtime name"
--no-llm` uses deterministic mode and never requires a provider key. The renderer includes no
investment recommendation.

## From files to finding

1. Put public PDF, HTML, or XLSX filings under `store/manual_drop/<ticker>/`.
2. Run `python -m agent.cli ingest --company <ticker>` to register files and extract
   quote-validated facts.
3. Inspect the metric-by-quarter coverage and rejected or empty files.
4. Use the evidence-preserving CSV template in [docs/FACTS_CSV.md](docs/FACTS_CSV.md) with
   `python -m agent.cli facts import --file facts.csv` when manual entry is necessary.
5. Run `python -m agent.cli run --company <ticker> --peers P1,P2,P3 --no-llm`.
6. Export JSON or Markdown with `--format json` or `--format md`; missing evidence is
   reported honestly as a weak/no-finding result.

## Extraction diagnostics and audit

Ingestion prints one diagnostic line per file with page count, parsed-page count,
text characters, sampled table count, aliases matched, OCR pages, and extracted
fact count. Long PDFs are scanned page-by-page and only alias/section pages are
parsed, so the global PDF safety limit applies to parsed pages rather than the
file's total length. Image-only pages use a bounded `pytesseract` fallback when
the `tesseract` executable is installed; otherwise they are reported as an
honest extraction gap.

Inspect stored evidence with:

```text
python -m agent.cli facts audit --ticker HDFCBANK --sample 10
```

Use `--only-failing` and `--metric METRIC` to narrow the audit. It prints
normalized value, basis, source file, validator results, coverage, events, and
every quote that no longer matches its registered source page. Export a
human-verification table without interpolation with:

```text
python -m agent.cli facts golden --ticker HDFCBANK \
  --metrics gross_advances,gross_npa,gnpa_pct,net_npa,nnpa_pct,slippages,write_offs,credit_cost,"casa ratio",total_deposits \
  --from Q2FY24 --to Q1FY27 --out out/golden_HDFCBANK.csv
```

Rows without a validated fact are marked `MISSING`; conflicts and suspect
quarter-on-quarter jumps are excluded from the table.
Merger/FAQ documents are registered as events and are not fact-extracted.

OCR is optional. On Windows install Tesseract from the official UB Mannheim
build and ensure `tesseract.exe` is on `PATH`; on Debian/Ubuntu use
`sudo apt install tesseract-ocr`. The Python OCR adapter is only invoked for
image-only pages, is bounded by the ingest timeout, and never blocks the
remaining documents. When no executable is available, ingestion prints the
image-only filenames that were skipped.

## P1 angles and dashboard

Funding mix shares, HHI, CASA decline, concentration, and short-term-funding
reliance are declared in [config/anomaly_rules.yaml](config/anomaly_rules.yaml).
They run only when the required facts exist and retain the source `fact_id`s.
Configured collection reads [config/sources.yaml](config/sources.yaml), which is
intentionally empty until a public endpoint is captured and verified; see
[docs/CAPTURE_ENDPOINTS.md](docs/CAPTURE_ENDPOINTS.md). Run the dashboard with
`streamlit run app/main.py`. Synthetic fixtures are labelled and are not real
research findings.

## P2 discovery and robustness

Open-ended detectors D1-D6 cover robust outliers, relationship breaks,
peer-relative divergence, mix shifts, unexplained change-points, and disclosure
drift. Their thresholds are in [config/open_ended.yaml](config/open_ended.yaml)
and configured metric relationships are in
[config/metric_relations.yaml](config/metric_relations.yaml). Anomalies receive
deterministic novelty, stability, and detector-agreement metadata; the run keeps
runner-up hypotheses in the report. Run the labelled SYNTHETIC smoke evaluation
with `python scripts/eval_synthetic.py`.
