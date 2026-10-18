import re
from dataclasses import dataclass


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
    factor = {"lakh": 0.01, "million": 0.1, "billion": 100.0,
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
