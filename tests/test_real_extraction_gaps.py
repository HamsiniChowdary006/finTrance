import fitz

from agent.extractor.document import extract_facts, read_document_pages
from agent.ingest import coverage, ingest_company
from store.dao import EvidenceStore


def test_comma_only_numeric_token_is_skipped_without_failing():
    facts = extract_facts(
        "Q1FY25 deposits of various tenors by some banks, 1,000 crore",
        "SYNTHETIC", "doc",
    )
    assert facts
    assert facts[0]["value"] == 1000


def test_comma_decimal_financial_number_is_normalised():
    facts = extract_facts("Q1FY25 Gross NPAs 37040,80", "SYNTHETIC", "doc")
    assert facts[0]["value"] == 37040.8


def test_long_pdf_targets_alias_pages_without_parsing_all_pages(tmp_path):
    path = tmp_path / "long.pdf"
    document = fitz.open()
    for _ in range(300):
        document.new_page()
    page = document.new_page()
    page.insert_text((72, 72), "FY2026 Borrowings 100 crore")
    document.save(path)
    diagnostics = {}
    pages = read_document_pages(path, diagnostics, aliases=["borrowings"])
    assert diagnostics["pages"] == 301
    assert diagnostics["pages_parsed"] == 1
    assert pages[0][0] == 301
    assert "Borrowings 100 crore" in pages[0][1]


def test_event_documents_are_registered_and_not_fact_extracted(tmp_path):
    root = tmp_path / "manual_drop"
    folder = root / "SYNTHETIC"
    folder.mkdir(parents=True)
    path = folder / "SYNTHETIC_merger_faq.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Merger FAQ Q1FY25 Gross Advances 100 crore")
    document.save(path)
    store = EvidenceStore(tmp_path / "evidence.sqlite")
    result = ingest_company("SYNTHETIC", root, store=store)
    assert result["events"] == 1
    assert not store.facts_for("SYNTHETIC")
    assert store.events_for("SYNTHETIC")[0].quote.startswith("Merger FAQ")


def test_coverage_marks_deterministic_percentage_derivations():
    from schemas.models import Fact, PeriodType

    store = EvidenceStore(":memory:")
    for metric, value in (("gross_advances", 1000), ("gross_npa", 20),
                           ("net_npa", 10), ("provisions_on_npa", 5),
                           ("write_offs", 2)):
        store.insert_fact(Fact(fact_id=f"{metric}-id", ticker="SYNTHETIC", metric=metric,
                               value=value, unit="INR crore", period="Q1FY25",
                               period_type=PeriodType.QUARTER, doc_id="doc", page=1,
                               quote=f"{metric} {value}", extractor="test", confidence=1.0))
    result = coverage(store, "SYNTHETIC")
    assert result["gnpa_pct"]["Q1FY25"]
    assert result["nnpa_pct"]["Q1FY25"]
    assert result["credit_cost"]["Q1FY25"]
