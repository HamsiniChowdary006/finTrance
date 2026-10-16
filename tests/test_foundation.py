from agent.extractor.validators import (
    find_aliases,
    normalise_amount,
    parse_period,
    validate_quote_and_bounds,
)
from schemas.models import CompanyType, Fact, PeriodType


def test_period_parser():
    assert parse_period("Q1 FY2025") == ("Q1FY2025", "quarter")
    assert parse_period("FY2023-24") == ("FY2024", "fy")


def test_units_and_validation():
    assert normalise_amount("1,000", "million") == 100
    assert validate_quote_and_bounds("gnpa_pct", 3.2, "GNPA 3.2%", "GNPA 3.2%").accepted
    assert not validate_quote_and_bounds("gnpa_pct", 42, "GNPA 42%", "GNPA 42%").accepted
    assert not validate_quote_and_bounds("gnpa_pct", 3.2, "NNPA", "GNPA 3.2%").accepted


def test_aliases_and_schema():
    assert find_aliases("Gross Advances and GNPA %", ["gross advances", "gnpa %"]) == [
        "gross advances", "gnpa %"
    ]
    fact = Fact(fact_id="f", ticker="T", metric="gnpa_pct", value=3, unit="%",
                period="Q1FY2025", period_type=PeriodType.QUARTER, doc_id="d", page=1,
                quote="GNPA 3%", extractor="test", confidence=.9)
    assert fact.period_type == PeriodType.QUARTER
    assert CompanyType.BANK.value == "bank"
