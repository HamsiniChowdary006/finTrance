from datetime import date

from schemas.models import Document, Fact, PeriodType, SourceType
from store.dao import EvidenceStore


def test_db_round_trip(tmp_path):
    store = EvidenceStore(tmp_path / "evidence.sqlite")
    store.insert_document(Document(doc_id="d", ticker="T", source_type=SourceType.MANUAL,
                                    title="fixture", sha256="abc", local_path="fixture.txt",
                                    published=date(2025, 1, 1)))
    store.insert_fact(Fact(fact_id="f", ticker="T", metric="gross_npa", value=2,
                           unit="INR crore", period="Q1FY2025",
                           period_type=PeriodType.QUARTER, doc_id="d", page=1,
                           quote="Gross NPA 2", extractor="fixture", confidence=.95))
    facts = store.facts_for("T", "gross_npa")
    assert len(facts) == 1
    assert facts[0].quote == "Gross NPA 2"
    assert store.flag_restatements("T", "gross_npa", "Q1FY2025") == 0
    store.close()
