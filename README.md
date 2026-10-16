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
