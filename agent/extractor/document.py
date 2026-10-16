import hashlib
import re
from pathlib import Path

import pandas as pd
import yaml

from agent.extractor.pdf_parse import extract_pages
from agent.extractor.validators import normalise_amount, parse_period, validate_quote_and_bounds

METRICS = {
    "gross_advances": (["gross advances", "loan book", "aum", "assets under management"], "INR crore"),
    "gross_npa": (["gross npa", "gross non-performing assets"], "INR crore"),
    "net_npa": (["net npa", "net non-performing assets"], "INR crore"),
    "gnpa_pct": (["gnpa %", "gross npa %", "gross npa ratio"], "%"),
    "nnpa_pct": (["nnpa %", "net npa %", "net npa ratio"], "%"),
    "write_offs": (["write offs", "write-offs"], "INR crore"),
    "provisions_on_npa": (["provisions on npa", "npa provisions"], "INR crore"),
    "stage2_assets": (["stage 2 assets", "stage 2"], "INR crore"),
    "stage3_assets": (["stage 3 assets", "stage 3"], "INR crore"),
    "casa_deposits": (["casa deposits", "casa"], "INR crore"),
    "total_deposits": (["total deposits", "deposits"], "INR crore"),
}


def read_document(path: str | Path) -> str:
    path = Path(path)
    limits = yaml.safe_load(Path("config/security.yaml").read_text(encoding="utf-8"))
    if path.stat().st_size > limits["max_document_bytes"]:
        raise ValueError("document exceeds configured size limit")
    if path.suffix.casefold() == ".pdf":
        pages = extract_pages(path)
        if len(pages) > limits["max_pdf_pages"]:
            raise ValueError("PDF exceeds configured page limit")
        return "\n".join(pages)
    if path.suffix.casefold() in {".html", ".htm"}:
        frame = pd.read_html(path)[0].astype(str)
        return "\n".join(" ".join(row) for row in frame.to_numpy())
    if path.suffix.casefold() == ".xlsx":
        return "\n".join(" ".join(map(str, row)) for frame in pd.read_excel(path, sheet_name=None).values()
                         for row in frame.fillna("").values.tolist())
    raise ValueError(f"Unsupported manual document type: {path.suffix}")


def extract_facts(text: str, ticker: str, doc_id: str = "manual") -> list[dict[str, object]]:
    facts: list[dict[str, object]] = []
    period_match = re.search(r"(Q[1-4]\s*FY\s*20\d{2}|FY\s*20\d{2}[-/]20\d{2})", text, re.IGNORECASE)
    if not period_match:
        return facts
    period, period_type = parse_period(period_match.group())
    for metric, (aliases, unit) in METRICS.items():
        alias = next((a for a in aliases if a.casefold() in text.casefold()), None)
        if not alias:
            continue
        match = re.search(re.escape(alias) + r".{0,80}?(-?[\d,]+(?:\.\d+)?)\s*(lakh|crore|million|billion|%)?",
                          text, re.IGNORECASE | re.DOTALL)
        if not match:
            continue
        raw_unit = match.group(2) or unit
        value = float(match.group(1).replace(",", ""))
        if raw_unit != "%" and unit == "INR crore":
            value = normalise_amount(value, raw_unit)
        quote = match.group(0).strip()
        result = validate_quote_and_bounds(metric, value, quote, text)
        if result.accepted:
            facts.append({"fact_id": hashlib.sha256(f"{doc_id}:{metric}:{period}".encode()).hexdigest()[:16],
                          "ticker": ticker, "metric": metric, "value": value, "unit": unit,
                          "period": period, "period_type": period_type, "doc_id": doc_id,
                          "page": 1, "quote": quote, "extractor": "deterministic",
                          "confidence": 0.8, "restated": False})
    return facts
