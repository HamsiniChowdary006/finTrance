from __future__ import annotations

import pandas as pd
import pytest

from agent.calc.metrics import credit_cost
from agent.calc.timeseries import Provenance
from agent.extractor.document import extract_facts
from agent.extractor.validators import normalise_amount, period_key, validate_value_context
from agent.ingest import coverage, ingest_company, validated_facts
from agent.orchestrator import Orchestrator
from schemas.models import Document, Fact, PeriodType, SourceType
from store.dao import EvidenceStore


def fact_result(text: str, metric: str = "gross_advances", max_period: str | None = None):
    return [item for item in extract_facts(text, "SYNTHETIC", "doc", max_period=max_period)
            if item["metric"] == metric]


def test_credit_cost_uses_series_and_merges_provenance():
    index = pd.Index(["Q1FY25", "Q2FY25"])
    result = credit_cost(
        Provenance(pd.Series([10.0, 20.0], index=index), {"Q1FY25": ["p1"], "Q2FY25": ["p2"]}),
        Provenance(pd.Series([2.0, 3.0], index=index), {"Q1FY25": ["w1"], "Q2FY25": ["w2"]}),
        Provenance(pd.Series([100.0, 110.0], index=index), {"Q1FY25": ["a1"], "Q2FY25": ["a2"]}),
    )
    assert pd.isna(result.values.iloc[0])
    assert result.values.iloc[1] == pytest.approx((20 + 3) * 4 / 105 * 100)
    assert result.fact_ids["Q2FY25"] == ["a2", "p2", "w2"]


def test_trillion_aum_is_not_gross_advances():
    assert fact_result("Q1FY25 AUM ₹2.8 trn") == []


def test_loan_book_alias_is_not_bank_gross_advances():
    assert fact_result("Q1FY25 Loan book 2,800 crore") == []


def test_yoy_growth_percentage_is_rejected_as_amount():
    assert fact_result("Q1FY25 Deposits YoY growth 15.1%") == []


def test_percentage_of_liabilities_is_rejected_as_borrowings():
    assert fact_result("Q1FY25 Borrowings as a % of Total Liabilities 8%",
                       "total_borrowings") == []


def test_note_number_advances_is_rejected():
    assert fact_result("Q1FY25 Note 9: Advances 9") == []


def test_forward_period_is_rejected():
    assert fact_result("FY2028 Gross Advances 100 crore", max_period="Q1FY27") == []


def test_amount_unit_normalisation():
    assert normalise_amount(2.8, "trn") == pytest.approx(280000)
    assert normalise_amount(2.8, "lakh crore") == pytest.approx(280000)
    assert normalise_amount(2.8, "bn") == pytest.approx(280)


@pytest.mark.parametrize("metric,unit,expected", [
    ("gross_advances", "%", False),
    ("gross_advances", "crore", True),
    ("gnpa_pct", "%", True),
    ("gnpa_pct", "crore", False),
])
def test_unit_context(metric, unit, expected):
    valid, _, _ = validate_value_context(metric, "12", f"Label 12{unit}", unit, "Label")
    assert valid is expected


def test_ratio_requires_label_adjacency():
    valid, statuses, _ = validate_value_context(
        "gnpa_pct", "2", "GNPA 2%", "%", "NNPA")
    assert not valid
    assert not statuses["label_adjacency"]


def test_comparative_column_fixture_uses_current_label():
    text = "Quarter ended 30 June 2025 31 March 2025 30 June 2024\nGross NPAs 100 90 80"
    facts = extract_facts(text, "SYNTHETIC", "doc", period_hint="Q1FY26")
    assert next(item for item in facts if item["metric"] == "gross_npa")["value"] == 100


def test_cumulative_column_is_not_used_for_quarterly_value():
    text = "Quarter ended 30 June 2025 Nine months ended 30 June 2025\nGross NPAs 100 300"
    facts = extract_facts(text, "SYNTHETIC", "doc", period_hint="Q1FY26")
    assert next(item for item in facts if item["metric"] == "gross_npa")["value"] == 100


def test_basis_is_carried_on_fact():
    fact = fact_result("Q1FY25 Gross Advances 100 crore")[0]
    assert fact["basis"] == "unknown"


def test_validator_status_is_carried_on_fact():
    fact = fact_result("Q1FY25 Gross Advances 100 crore")[0]
    assert fact["validator_status"]["value_in_quote"]
    assert fact["validator_status"]["unit_compatible"]


def test_provisions_expense_is_distinct_metric():
    facts = extract_facts(
        "Q1FY25 Provisions (other than tax) and Contingencies 100 crore",
        "SYNTHETIC", "doc")
    assert any(item["metric"] == "provisions_expense" for item in facts)


def test_orchestrator_continues_when_rule_fails(tmp_path, monkeypatch):
    import agent.orchestrator as module
    store = EvidenceStore(tmp_path / "run.sqlite")
    from schemas.models import Fact
    store.insert_fact(Fact(fact_id="a", ticker="SYNTHETIC", metric="gross_advances",
                           value=100, unit="INR crore", period="Q1FY25",
                           period_type=PeriodType.QUARTER, doc_id="d", page=1,
                           quote="Gross Advances 100 crore", extractor="test", confidence=1))
    monkeypatch.setattr(module, "evaluate_rules", lambda *_: (_ for _ in ()).throw(
        ValueError("bad configured rule")))
    result = Orchestrator(store=store).run("SYNTHETIC")
    assert result.report is not None
    assert any("rules skipped" in event["message"] for event in result.events)
    assert any("bad configured rule" in warning for warning in result.report.warnings)


def test_duplicate_sha_is_reported(tmp_path):
    root = tmp_path / "drop"
    folder = root / "SYNTHETIC"
    folder.mkdir(parents=True)
    (folder / "one.html").write_text("Q1FY25 Gross Advances 100 crore", encoding="utf-8")
    (folder / "two.html").write_text("Q1FY25 Gross Advances 100 crore", encoding="utf-8")
    result = ingest_company("SYNTHETIC", root, store=EvidenceStore(tmp_path / "db.sqlite"))
    assert result["duplicate_files"]


def test_fact_store_round_trip_validator_metadata(tmp_path):
    store = EvidenceStore(tmp_path / "db.sqlite")
    fact = Fact(fact_id="f", ticker="SYNTHETIC", metric="gross_advances", value=100,
                unit="INR crore", period="Q1FY25", period_type=PeriodType.QUARTER,
                doc_id="d", page=1, quote="Gross Advances 100 crore", extractor="test",
                confidence=1, normalized_value=100, basis="standalone",
                validator_status={"value_in_quote": True}, suspect=False)
    store.insert_fact(fact)
    assert store.facts_for("SYNTHETIC")[0].basis == "standalone"


def test_period_key_orders_quarters_before_fy():
    assert period_key("Q4FY25") < period_key("FY2025")


def test_amount_with_percent_context_rejected():
    assert fact_result("Q1FY25 Gross Advances 12%") == []


def test_ratio_without_percent_rejected():
    assert fact_result("Q1FY25 GNPA % 2", "gnpa_pct") == []


def test_empty_numeric_candidate_does_not_raise():
    assert extract_facts("Q1FY25 Gross Advances , crore", "SYNTHETIC", "doc") == []


def test_source_document_schema_remains_compatible():
    doc = Document(doc_id="d", ticker="SYNTHETIC", source_type=SourceType.MANUAL,
                   title="fixture", sha256="x", local_path="fixture")
    assert doc.title == "fixture"


def test_validated_fact_requires_quote():
    facts = fact_result("Q1FY25 Gross Advances 100 crore")
    assert facts[0]["quote"]


@pytest.mark.parametrize("text", [
    "Q4FY24 Write offs GNPA as on Dec'23",
    "Q4FY24 Write offs GNPA as on Mar'24",
    "Q4FY24 Write offs GNPA as on FY24",
])
def test_date_tokens_are_not_writeoff_values(text):
    assert fact_result(text, "write_offs") == []


def test_credit_cost_requires_same_line_percent():
    assert fact_result("Q1FY25 Credit cost 2.0%", "credit_cost")
    assert fact_result("Q1FY25 RoA was 2.0%", "credit_cost") == []
    assert fact_result("Q1FY25 Credit cost\nRoA was 2.0%", "credit_cost") == []


def test_credit_cost_rejects_other_percentage_sentence():
    assert fact_result("Q1FY25 Credit cost is discussed. RoA 2.0%", "credit_cost") == []


def test_transcript_numeric_facts_are_skipped(tmp_path):
    root = tmp_path / "drop"
    folder = root / "SYNTHETIC"
    folder.mkdir(parents=True)
    (folder / "SYNTHETIC_Q1FY25_transcript.html").write_text(
        "Q1FY25 Gross Advances 100 crore", encoding="utf-8")
    result = ingest_company("SYNTHETIC", root, store=EvidenceStore(tmp_path / "db.sqlite"))
    assert result["facts"] == 0


def test_validated_coverage_excludes_conflicts_and_suspects(tmp_path):
    store = EvidenceStore(tmp_path / "db.sqlite")
    base = {"ticker": "SYNTHETIC", "metric": "gross_advances", "value": 100,
            "unit": "INR crore", "period": "Q1FY25", "period_type": PeriodType.QUARTER,
            "doc_id": "d", "page": 1, "quote": "Gross Advances 100 crore",
            "extractor": "test", "confidence": 1, "validator_status": {"quote": True}}
    store.insert_fact(Fact(fact_id="bad", **base, conflict=True))
    assert coverage(store, "SYNTHETIC")["gross_advances"]["Q1FY25"] is False
    assert validated_facts(store, "SYNTHETIC") == []


def test_aliases_include_bank_appropriate_gross_advances():
    assert fact_result("Q1FY25 Gross loans 100 crore")
    assert fact_result("Q1FY25 Advances (gross) 100 crore")
    assert fact_result("Q1FY25 Total advances 100 crore")


def test_casa_ratio_alias_is_canonicalized_in_golden_parser():
    from agent.cli import store_metric_names
    store = EvidenceStore(":memory:")
    assert "casa_deposits" in store_metric_names(store, "SYNTHETIC")


def test_no_lookahead_period_is_rejected():
    assert fact_result("Q1FY25 Gross advances 100 crore", max_period="Q4FY24") == []


def test_credit_cost_line_does_not_use_adjacent_line():
    assert fact_result("Q1FY25 Credit cost\n2.0%", "credit_cost") == []


def test_writeoff_quote_is_same_line_only():
    assert fact_result("Q1FY25 Write offs\n100 crore", "write_offs") == []


def test_validator_marks_date_period_failure():
    valid, statuses, _ = validate_value_context(
        "write_offs", "23", "Write offs GNPA as on Dec'23", "", "write offs")
    assert not valid
    assert not statuses["date_or_period_free"]


def test_ratio_roa_context_is_rejected():
    valid, _, _ = validate_value_context(
        "credit_cost", "2.0", "Credit cost / RoA 2.0%", "%", "credit cost")
    assert not valid


def test_empty_validated_series_has_no_coverage():
    store = EvidenceStore(":memory:")
    assert validated_facts(store, "SYNTHETIC") == []


def test_duplicate_source_text_is_reported(tmp_path):
    root = tmp_path / "drop"
    folder = root / "SYNTHETIC"
    folder.mkdir(parents=True)
    content = "Q1FY25 Gross advances 100 crore"
    (folder / "presentation_a.html").write_text(content, encoding="utf-8")
    (folder / "presentation_b.html").write_text(content, encoding="utf-8")
    result = ingest_company("SYNTHETIC", root, store=EvidenceStore(tmp_path / "db.sqlite"))
    assert result["duplicate_files"]


def test_compute_warning_contains_missing_inputs(tmp_path):
    store = EvidenceStore(tmp_path / "db.sqlite")
    result = Orchestrator(store=store).run("SYNTHETIC")
    compute_events = [event for event in result.events if event["stage"] == "COMPUTE"]
    assert "missing metrics=" in compute_events[-1]["message"]


def test_novelty_marks_missing_context_as_na():
    from agent.scan.novelty import score_novelty
    from agent.scan.rules import Anomaly
    anomaly = Anomaly(rule_id="D1", angle="test", metrics=["gross_advances"],
                      window=["Q1FY25"], magnitude=1, persistence_quarters=1,
                      description="test")
    score_novelty(anomaly, "", "insufficient")
    assert anomaly.novelty_components["management"] == "n/a"
    assert anomaly.novelty_components["peer_uniqueness"] == "n/a"


def test_renderer_suppresses_evidence_free_discovery():
    from agent.reason.models import Grade
    from agent.render.report import render_report
    report = render_report("Unsafe discovery", [], [], "", "", Grade(
        total=8, label="Strong", points={}, rationale=[]), [])
    assert report.discovery == "No evidence-backed finding"
    assert report.evidence_strength.label == "Weak"


def test_open_ended_pct_change_has_no_fill_warning():
    from agent.calc.timeseries import Provenance
    from agent.scan.open_ended import robust_outliers
    config = {"detectors": {"D1": {"min_history": 2, "rolling_window": 2,
                                    "recent_quarters": 1, "mad_z": 2, "min_delta": 1}}}
    robust_outliers({"x": Provenance(pd.Series([1.0, None, 3.0]), {})}, config)
