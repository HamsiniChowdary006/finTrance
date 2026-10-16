import pytest

from agent.extractor.document import extract_facts
from agent.extractor.validators import find_aliases, normalise_amount, parse_period, quote_matches


@pytest.mark.parametrize("value,expected", [
    ("Q1 FY2025", "Q1FY2025"), ("Q2FY25", "Q2FY2025"), ("Q3 FY 2024", "Q3FY2024"),
    ("Q4 FY2024", "Q4FY2024"), ("Q4 FY2023-24", "Q4FY2023"),
])
def test_period_variants(value, expected):
    assert parse_period(value)[0] == expected


@pytest.mark.parametrize("unit,value,expected", [
    ("lakh", 100, 1), ("crore", 100, 100), ("million", 100, 10),
    ("billion", 1, 100), ("INR crore", 2.5, 2.5),
])
def test_unit_variants(unit, value, expected):
    assert normalise_amount(value, unit) == expected


@pytest.mark.parametrize("alias", ["gross advances", "loan book", "AUM", "GNPA %"])
def test_alias_variants(alias):
    assert find_aliases(alias, [alias.casefold()]) == [alias.casefold()]


def test_alias_matching_is_case_insensitive():
    assert find_aliases("Gross Advances", ["gross advances"]) == ["gross advances"]


@pytest.mark.parametrize("quote,text,expected", [
    ("Gross NPA 2%", "Gross NPA 2%", True), ("NPA 2", "Gross NPA 2%", True),
    ("", "Gross NPA 2%", False), ("Gross NPA 3%", "Gross NPA 2%", False),
])
def test_quote_variants(quote, text, expected):
    assert quote_matches(quote, text) is expected


def test_deterministic_extraction_has_verbatim_quote():
    facts = extract_facts("Q4 FY2024 Gross Advances 1,000 crore; Gross NPA 20 crore", "T", "d")
    assert {fact["metric"] for fact in facts} == {"gross_advances", "gross_npa"}
    assert all(fact["quote"] in "Q4 FY2024 Gross Advances 1,000 crore; Gross NPA 20 crore"
               for fact in facts)


def test_missing_period_is_reported_as_no_facts():
    assert extract_facts("Gross Advances 1,000 crore", "T", "d") == []
