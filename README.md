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
