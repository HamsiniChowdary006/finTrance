import hashlib
import io
import logging
import re
import shutil
import time
from functools import lru_cache
from html import unescape
from pathlib import Path

import pandas as pd
import yaml

from agent.extractor.pdf_parse import extract_target_pages
from agent.extractor.validators import (
    normalise_amount,
    parse_period,
    period_key,
    validate_quote_and_bounds,
    validate_value_context,
)

LOGGER = logging.getLogger(__name__)

METRICS = {
    "gross_advances": (["gross advances", "advances"], "INR crore"),
    "gross_npa": (["gross npa", "gross npas", "gross non-performing assets"], "INR crore"),
    "net_npa": (["net npa", "net npas", "net non-performing assets"], "INR crore"),
    "gnpa_pct": (["gnpa %", "gross npa %", "gross npa ratio",
                  "% of gross npas to gross advances"], "%"),
    "nnpa_pct": (["nnpa %", "net npa %", "net npa ratio",
                  "% of net npas to net advances"], "%"),
    "write_offs": (["write offs", "write-offs"], "INR crore"),
    "provisions_on_npa": (["provisions on npa", "npa provisions",
                            "provision coverage stock"], "INR crore"),
    "provisions_expense": (["provisions (other than tax) and contingencies",
                            "provisions other than tax"], "INR crore"),
    "stage2_assets": (["stage 2 assets", "stage 2"], "INR crore"),
    "stage3_assets": (["stage 3 assets", "stage 3"], "INR crore"),
    "casa_deposits": (["casa deposits", "casa"], "INR crore"),
    "total_deposits": (["total deposits", "deposits"], "INR crore"),
    "bank_loans": (["bank loans", "loans from banks"], "INR crore"),
    "term_deposits": (["term deposits", "fixed deposits"], "INR crore"),
    "borrowings": (["total borrowings", "borrowings"], "INR crore"),
    "ncd_bonds": (["ncds", "ncds/bonds", "bonds", "non-convertible debentures"], "INR crore"),
    "commercial_paper": (["commercial paper", "cp outstanding"], "INR crore"),
    "ecb": (["ecb", "external commercial borrowings"], "INR crore"),
    "deposits": (["public deposits", "deposits"], "INR crore"),
    "securitisation": (["securitisation", "securitization", "assigned loans"], "INR crore"),
    "total_borrowings": (["total borrowings", "borrowings"], "INR crore"),
    "top_lender_share": (["largest lender share", "top lender share"], "%"),
}


@lru_cache(maxsize=1)
def configured_metrics() -> dict[str, tuple[list[str], str]]:
    metrics = dict(METRICS)
    for path in (Path("config/metrics_bank.yaml"), Path("config/metrics_nbfc.yaml"),
                 Path("config/metrics_other.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for metric, definition in payload.get("metrics", {}).items():
            if metric not in metrics:
                metrics[metric] = (definition.get("aliases", []), definition["unit"])
    return metrics


def _ocr_page(path: Path, page_number: int, deadline: float) -> str:
    if time.monotonic() >= deadline:
        return ""
    try:
        import fitz
        import pytesseract
        image = fitz.open(path)[page_number - 1].get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
        from PIL import Image
        return pytesseract.image_to_string(Image.open(io.BytesIO(image.tobytes("png"))),
                                           timeout=max(1, deadline - time.monotonic()))
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        LOGGER.warning("OCR skipped for %s page %s: %s", path.name, page_number, error)
        return ""


def read_document_pages(path: str | Path, diagnostics: dict[str, object] | None = None,
                        aliases: list[str] | None = None, ocr_seconds: float = 20.0,
                        count_tables: bool = True
                        ) -> list[tuple[int, str]]:
    path = Path(path)
    limits = yaml.safe_load(Path("config/security.yaml").read_text(encoding="utf-8"))
    if path.stat().st_size > limits["max_document_bytes"]:
        raise ValueError("document exceeds configured size limit")
    diagnostics = diagnostics if diagnostics is not None else {}
    if path.suffix.casefold() == ".pdf":
        terms = aliases or [alias for values in configured_metrics().values() for alias in values[0]]
        pages = extract_target_pages(path, terms, limits["max_pdf_pages"], diagnostics)
        try:
            import pdfplumber
            selected_numbers = {number for number, _ in pages}
            if not count_tables:
                diagnostics["tables_found"] = "not_requested"
            elif len(selected_numbers) <= 10:
                with pdfplumber.open(path) as pdf:
                    sampled_numbers = sorted(selected_numbers)[:10]
                    diagnostics["tables_found"] = sum(
                        len(pdf.pages[number - 1].extract_tables() or [])
                        for number in sampled_numbers)
                    if len(selected_numbers) > len(sampled_numbers):
                        diagnostics["tables_found"] = (
                            f"{diagnostics['tables_found']} in first {len(sampled_numbers)} pages")
            else:
                diagnostics["tables_found"] = "skipped_large_selection"
        except (ImportError, OSError, ValueError):
            diagnostics["tables_found"] = 0
        deadline = time.monotonic() + ocr_seconds
        output = []
        ocr_pages = 0
        ocr_available = bool(shutil.which("tesseract"))
        if any(not text.strip() for _, text in pages) and not ocr_available:
            diagnostics["ocr_error"] = "tesseract executable unavailable"
        for number, text in pages:
            if not text.strip() and ocr_available:
                text = _ocr_page(path, number, deadline)
                ocr_pages += bool(text.strip())
            if text.strip():
                output.append((number, text))
        diagnostics["ocr_pages"] = ocr_pages
        diagnostics["chars_parsed"] = sum(len(text) for _, text in output)
        return output
    if path.suffix.casefold() in {".html", ".htm"}:
        raw = path.read_text(encoding="utf-8", errors="replace")
        return [(1, re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", raw))).strip())]
    if path.suffix.casefold() == ".xlsx":
        text = "\n".join(" ".join(map(str, row)) for frame in
                         pd.read_excel(path, sheet_name=None).values()
                         for row in frame.fillna("").values.tolist())
        return [(1, text)]
    raise ValueError(f"Unsupported manual document type: {path.suffix}")


def read_document(path: str | Path) -> str:
    return "\n".join(text for _, text in read_document_pages(path))


def _parse_number(numeric_text: str) -> float:
    numeric_text = numeric_text.strip()
    if not re.search(r"\d", numeric_text) or numeric_text.endswith((",", ".")):
        raise ValueError(f"non-numeric value: {numeric_text!r}")
    if "," in numeric_text and "." not in numeric_text and len(numeric_text.rsplit(",", 1)[1]) == 2:
        numeric_text = numeric_text.replace(",", ".")
    else:
        numeric_text = numeric_text.replace(",", "")
    return float(numeric_text)


def _alias_match(text: str, alias: str) -> re.Match[str] | None:
    pattern = re.escape(alias).replace(r"\ ", r"\s+")
    return re.search(pattern, text, re.IGNORECASE)


def extract_facts(text: str, ticker: str, doc_id: str = "manual",
                  period_hint: str | None = None, page: int = 1,
                  diagnostics: dict[str, object] | None = None,
                  max_period: str | None = None,
                  basis: str = "unknown") -> list[dict[str, object]]:
    facts: list[dict[str, object]] = []
    period_match = re.search(
        r"(Q[1-4]\s*FY\s*(?:20)?\d{2}|FY\s*(?:20)?\d{2}[-/]?(?:20)?\d{2})",
        text, re.IGNORECASE)
    period_match = (re.match(r".*", period_hint or "") if period_hint else period_match)
    if not period_match:
        return facts
    if basis == "unknown":
        lower_text = text.casefold()
        if re.search(r"\b(segment|subsidiary|associate)\b", lower_text):
            basis = "segment" if "segment" in lower_text else "subsidiary"
        elif re.search(r"\bstandalone\b", lower_text):
            basis = "standalone"
        elif re.search(r"\bconsolidated\b", lower_text):
            basis = "consolidated"
    period, period_type = parse_period(period_match.group() if period_match else period_hint or "")
    if max_period and period_key(period) > period_key(max_period):
        if diagnostics is not None:
            diagnostics.setdefault("rejected", []).append(f"{period}:after latest {max_period}")
        return facts
    alias_hits = set(diagnostics.get("aliases_matched", []) if diagnostics else [])
    skipped: list[str] = []
    for metric, (aliases, unit) in configured_metrics().items():
        alias_match = next(((a, _alias_match(text, a)) for a in aliases
                            if _alias_match(text, a)), None)
        if not alias_match:
            continue
        alias, matched = alias_match
        alias_hits.add(alias)
        start = matched.end()
        line_start = text.rfind("\n", 0, matched.start()) + 1
        line_end = text.find("\n", start)
        line_end = len(text) if line_end < 0 else line_end
        line = text[line_start:line_end]
        next_end = text.find("\n", line_end + 1)
        adjacent = text[line_end + 1:(len(text) if next_end < 0 else next_end)]
        window = line[line.find(matched.group(0)) + len(matched.group(0)):] + "\n" + adjacent
        if re.search(r"\b(?:growth|yoy|qoq|as a %|ratio|per share|eps)\b", line, re.IGNORECASE):
            if diagnostics is not None:
                diagnostics.setdefault("rejected", []).append(f"{metric}:context")
            continue
        candidate = None
        value = None
        for possible in re.finditer(r"(?<!\w)-?(?:\d[\d,.]*)(?!\w)", window):
            numeric_text = possible.group(0)
            context = window[max(0, possible.start() - 18):possible.start()].casefold()
            note_pos = context.rfind("note")
            newline_pos = context.rfind("\n")
            if (numeric_text.count(".") >= 2 or
                    (note_pos >= 0 and newline_pos < note_pos) or
                    (unit != "%" and re.match(r"\s*%", window[possible.end():]))):
                continue
            try:
                value = _parse_number(numeric_text)
                candidate = possible
                break
            except ValueError as error:
                skipped.append(f"{metric}:{numeric_text}:{error}")
                LOGGER.warning("Skipping non-numeric value for %s: %s", metric, numeric_text)
        if not candidate or value is None:
            skipped.append(f"{metric}:{alias}:no numeric token")
            continue
        unit_match = re.search(r"(lakh\s+crore|trn|tn|trillion|bn|mn|lakh|crore|million|billion|%)",
                               window[candidate.end():],
                               re.IGNORECASE)
        detected_unit = unit_match.group(1) if unit_match else ""
        raw_unit = detected_unit or unit
        if detected_unit != "%" and unit == "INR crore":
            value = normalise_amount(value, raw_unit)
        quote = (line + ("\n" + adjacent if candidate.end() > len(line) -
                         (line.find(matched.group(0)) + len(matched.group(0))) else "")).strip()
        quote = quote[:quote.find("\n") + 1 + candidate.end()] if "\n" in quote else quote
        valid, statuses, reason = validate_value_context(
            metric, candidate.group(0), quote, detected_unit, alias)
        if not valid:
            if diagnostics is not None:
                diagnostics.setdefault("rejected", []).append(f"{metric}:{reason}")
            continue
        result = validate_quote_and_bounds(metric, value, quote, text)
        if result.accepted:
            changed = bool(re.search(
                r"\b(restated|reclassified|presentation change|one[- ]time)\b", text, re.IGNORECASE))
            facts.append({"fact_id": hashlib.sha256(
                f"{doc_id}:{metric}:{period}:{page}".encode()).hexdigest()[:16],
                "ticker": ticker, "metric": metric, "value": value, "unit": unit,
                "period": period, "period_type": period_type, "doc_id": doc_id,
                "page": page, "quote": quote, "extractor": "deterministic",
                "confidence": 0.8, "restated": changed})
            facts[-1]["normalized_value"] = value
            facts[-1]["basis"] = basis
            facts[-1]["validator_status"] = statuses | {"bounds": True, "quote": True}
    if diagnostics is not None:
        diagnostics["aliases_matched"] = sorted(alias_hits)
        diagnostics["skipped_tokens"] = skipped
    return facts


def extract_dependency_passages(text: str, doc_id: str, page: int = 1) -> list[dict[str, object]]:
    patterns = (
        r"(?:top|largest)\s+(?:lender|funder)[^.]{0,180}",
        r"(?:co-lending|co lending|partnership|group dependence)[^.]{0,180}",
    )
    return [{"doc_id": doc_id, "page": page, "quote": match.group(0).strip(),
             "metric": "dependency_passage"}
            for pattern in patterns for match in re.finditer(pattern, text, re.IGNORECASE)]
