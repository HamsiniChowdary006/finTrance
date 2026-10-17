from pathlib import Path

import pytest

from agent.extractor.document import extract_facts
from agent.ingest import source_title_type
from agent.orchestrator import Orchestrator
from schemas.models import SourceType
from store.dao import EvidenceStore


@pytest.mark.parametrize("period", [f"Q{quarter}FY25" for quarter in range(1, 5)])
def test_extractor_accepts_short_quarter_labels(period):
    facts = extract_facts(f"{period} Gross Advances 1,000 crore", "SYNTHETIC", "doc")
    assert facts and facts[0]["period_type"] == "quarter"


@pytest.mark.parametrize("metric", [
    "Gross Advances", "Gross NPA", "Net NPA", "GNPA %", "NNPA %",
    "Write Offs", "Provisions on NPA", "Stage 3 assets",
])
def test_extractor_aliases_are_evidence_bound(metric):
    facts = extract_facts(f"Q1FY25 {metric} 2 crore", "SYNTHETIC", "doc")
    assert facts and facts[0]["quote"] in f"Q1FY25 {metric} 2 crore"


@pytest.mark.parametrize(("filename", "expected"), [
    ("rating_note.pdf", SourceType.RATING),
    ("rbi_disclosure.pdf", SourceType.RBI),
    ("exchange_announcement.pdf", SourceType.EXCHANGE),
    ("presentation.xlsx", SourceType.MANUAL),
])
def test_manual_source_type_is_conservative(filename, expected):
    assert source_title_type(Path(filename)) == expected


@pytest.mark.parametrize("ticker", ["SYNTHETIC", "OTHER_SYNTHETIC", "BANK_SYNTHETIC"])
def test_empty_run_reports_explicit_skip_reasons(tmp_path, ticker):
    result = Orchestrator(EvidenceStore(tmp_path / f"{ticker}.sqlite")).run(ticker)
    skipped = [event for event in result.events if event["status"] == "skipped"]
    assert skipped
    assert all(event["message"] for event in skipped)


@pytest.mark.parametrize("section", [
    "discovery", "why_it_matters", "evidence", "timeline", "numbers",
    "counterargument", "falsification_condition", "evidence_strength",
])
def test_empty_run_renders_all_report_sections(tmp_path, section):
    report = Orchestrator(EvidenceStore(tmp_path / "report.sqlite")).run("SYNTHETIC").report
    assert getattr(report, section) is not None
