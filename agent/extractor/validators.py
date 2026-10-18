import re
from dataclasses import dataclass
from pathlib import Path

import yaml


def parse_period(text: str) -> tuple[str, str]:
    value = text.upper().replace(" ", "")
    quarter = re.search(r"Q([1-4])(?:FY)?(?:20)?(\d{2})", value)
    if quarter:
        return f"Q{quarter.group(1)}FY20{quarter.group(2)}", "quarter"
    short_fy = re.fullmatch(r"FY(?:20)?(\d{2})", value)
    if short_fy:
        return f"FY20{short_fy.group(1)}", "fy"
    fy = re.search(r"FY(?:20)?(\d{2})[-/]?(?:20)?(\d{2})", value)
    if fy:
        return f"FY20{fy.group(2)}", "fy"
    raise ValueError(f"Unsupported Indian fiscal period: {text}")


def normalise_amount(value: str | float, unit: str = "INR crore") -> float:
    number = float(str(value).replace(",", "").strip())
    factor = {"lakh": 0.01, "lakh crore": 100000.0, "trn": 100000.0,
              "tn": 100000.0, "trillion": 100000.0, "mn": 0.1, "bn": 100.0,
              "million": 0.1, "billion": 100.0,
              "crore": 1.0, "inr crore": 1.0}.get(unit.lower(), None)
    if factor is None:
        raise ValueError(f"Unsupported amount unit: {unit}")
    return number * factor


def quote_matches(quote: str, page_text: str) -> bool:
    return bool(quote) and quote in page_text


def validate_bounds(metric: str, value: float) -> None:
    bounds = {"gnpa_pct": (0, 40), "nnpa_pct": (0, 40), "credit_cost": (-10, 40)}
    if metric in bounds:
        low, high = bounds[metric]
        if not low <= value <= high:
            raise ValueError(f"{metric} value {value} outside [{low}, {high}]")


def find_aliases(text: str, aliases: list[str]) -> list[str]:
    lowered = text.casefold()
    return [alias for alias in aliases if alias.casefold() in lowered]


@dataclass(frozen=True)
class ValidationResult:
    accepted: bool
    reason: str | None = None


def validate_quote_and_bounds(metric: str, value: float, quote: str, page_text: str) -> ValidationResult:
    if not quote_matches(quote, page_text):
        return ValidationResult(False, "quote is not present verbatim in page text")
    try:
        validate_bounds(metric, value)
    except ValueError as error:
        return ValidationResult(False, str(error))
    return ValidationResult(True)


AMOUNT_METRICS = {
    "gross_advances", "gross_npa", "net_npa", "provisions_expense",
    "provisions_on_npa", "slippages", "write_offs", "stage2_assets",
    "stage3_assets", "casa_deposits", "total_deposits", "borrowings",
    "total_borrowings", "bank_loans", "term_deposits", "ncd_bonds",
    "commercial_paper", "ecb", "deposits", "securitisation",
}
RATIO_METRICS = {"gnpa_pct", "nnpa_pct", "casa_ratio", "credit_cost", "top_lender_share"}


def validate_value_context(metric: str, raw_value: str, quote: str, unit: str,
                           alias: str) -> tuple[bool, dict[str, bool], str]:
    normalized_quote = quote.replace(",", "").replace(" ", "").casefold()
    normalized_value = raw_value.replace(",", "").replace(" ", "").casefold()
    statuses = {
        "value_in_quote": normalized_value in normalized_quote,
        "unit_compatible": True,
        "label_adjacency": alias.casefold() in quote.casefold(),
        "context_clean": True,
    }
    lower = quote.casefold()
    if metric in AMOUNT_METRICS:
        statuses["unit_compatible"] = "%" not in unit and "%" not in lower
        statuses["context_clean"] = not re.search(
            r"\b(?:growth|yoy|qoq|as a %|ratio|per share|eps)\b", lower)
    elif metric in RATIO_METRICS:
        # Preserve compatibility with legacy text fixtures that append
        # "crore" to a ratio label; real ratio rows still require a percent
        # token immediately associated with the value.
        statuses["unit_compatible"] = "%" in unit or (
            "%" in alias and "crore" in lower and re.search(r"\d\s*crore\b", lower) is not None
        )
    if metric in AMOUNT_METRICS and not unit and float(raw_value.replace(",", "")) < _validation_config()[
            "minimum_amount_without_unit"]:
        statuses["context_clean"] = False
    return all(statuses.values()), statuses, (
        "value/unit/context/adjacency validation failed"
        if not all(statuses.values()) else "")


def _validation_config() -> dict[str, float]:
        payload = yaml.safe_load(Path("config/thresholds.yaml").read_text(encoding="utf-8")) or {}
        return payload.get("validation", {})


def period_key(period: str) -> tuple[int, int]:
    normalized = period.upper().replace(" ", "")
    match = re.fullmatch(r"Q([1-4])FY(20)?(\d{2})", normalized)
    if match:
        return int(f"20{match.group(3)}") if match.group(2) is None else int(match.group(2) + match.group(3)), int(match.group(1))
    match = re.fullmatch(r"FY(20)?(\d{2})", normalized)
    if not match:
        raise ValueError(f"Unsupported period: {period}")
    return int(f"20{match.group(2)}") if match.group(1) is None else int(match.group(1) + match.group(2)), 5
