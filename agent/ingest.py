import hashlib
import re
from pathlib import Path

from agent.extractor.document import extract_facts, read_document_pages
from agent.security import safe_path
from schemas.models import Document, Event, Fact, PeriodType, SourceType
from store.dao import EvidenceStore

SUPPORTED = {".pdf", ".html", ".htm", ".xlsx"}
EVENT_TERMS = ("merger", "amalgamation", "faq", "scheme of arrangement")


def source_title_type(path: Path) -> SourceType:
    title = path.stem.casefold()
    if "rationale" in title:
        return SourceType.RATING_RATIONALE
    if "rating" in title or "credit" in title:
        return SourceType.RATING
    if "rbi" in title or "regulatory" in title:
        return SourceType.RBI
    if "announcement" in title or "disclosure" in title:
        return SourceType.EXCHANGE
    return SourceType.MANUAL


def ingest_company(company: str, root: str | Path = "store/manual_drop",
                   ticker: str | None = None, store: EvidenceStore | None = None,
                   reingest: bool = False, ocr_seconds: float = 20.0) -> dict:
    store = store or EvidenceStore()
    ticker = ticker or company
    root_path = Path(root).resolve()
    folder = safe_path(root_path / ticker, root_path)
    files = [path for path in sorted(folder.rglob("*"))
             if path.is_file() and path.suffix.casefold() in SUPPORTED]
    rejected: list[dict[str, str]] = []
    empty: list[str] = []
    inserted = 0
    diagnostics: list[dict[str, object]] = []
    events = 0
    for path in files:
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        doc_id = digest[:16]
        existing = store.connection.execute(
            "SELECT sha256 FROM documents WHERE ticker=? AND local_path=?",
            (ticker, str(path)),
        ).fetchone()
        if existing and existing["sha256"] == digest and not reingest:
            continue
        if existing:
            old_document = store.connection.execute(
                "SELECT doc_id FROM documents WHERE ticker=? AND local_path=?",
                (ticker, str(path)),
            ).fetchone()
            if old_document:
                store.delete_document_evidence(old_document["doc_id"])
            store.delete_document_evidence(doc_id)
        document = Document(doc_id=doc_id, ticker=ticker, source_type=source_title_type(path),
                            title=path.name, sha256=digest, local_path=str(path))
        store.insert_document(document)
        try:
            file_diagnostics: dict[str, object] = {"file": str(path), "pages": 0, "chars": 0,
                                                   "tables_found": 0}
            period_hint = next(iter(re.findall(
                r"Q[1-4]FY(?:20)?\d{2}|FY(?:20)?\d{2}(?:[-/]?(?:20)?\d{2})?",
                path.stem, re.IGNORECASE)), None)
            pages = read_document_pages(path, file_diagnostics, ocr_seconds=ocr_seconds)
            file_diagnostics["chars"] = sum(len(text) for _, text in pages)
            full_text = "\n".join(text for _, text in pages)
            if any(term in path.stem.casefold() for term in EVENT_TERMS):
                event_text = next((text for _, text in pages
                                   if any(term in text.casefold() for term in EVENT_TERMS)),
                                  full_text)
                event = Event(
                    event_id=hashlib.sha256(f"{doc_id}:event".encode()).hexdigest()[:16],
                    ticker=ticker, doc_id=doc_id, title=path.name, period=period_hint,
                    page=1, quote=event_text[:500] or path.name)
                store.insert_event(event)
                events += 1
                diagnostics.append(file_diagnostics)
                continue
            extracted = []
            for page_number, text in pages:
                extracted.extend(extract_facts(text, ticker, doc_id, period_hint,
                                                page_number, file_diagnostics))
            file_diagnostics["facts"] = len(extracted)
            diagnostics.append(file_diagnostics)
        except (OSError, ValueError, RuntimeError) as error:
            rejected.append({"file": str(path), "reason": str(error)})
            diagnostics.append({"file": str(path), "error": str(error)})
            continue
        if not extracted:
            empty.append(str(path))
        for item in extracted:
            item["period_type"] = PeriodType(item["period_type"])
            store.insert_fact(Fact.model_validate(item))
            inserted += 1
    return {"ticker": ticker, "documents": len(files), "facts": inserted,
            "rejected": rejected, "empty": empty, "diagnostics": diagnostics,
            "events": events}


def import_csv(path: str | Path, store: EvidenceStore | None = None) -> dict:
    import csv

    store = store or EvidenceStore()
    path = Path(path)
    rows = list(csv.DictReader(path.read_text(encoding="utf-8-sig").splitlines()))
    required = {"ticker", "metric", "period", "value", "unit", "source_file", "page", "quote"}
    if rows and not required <= set(rows[0]):
        raise ValueError(f"facts CSV missing columns: {sorted(required - set(rows[0]))}")
    imported, rejected = 0, []
    for row in rows:
        source = Path(row["source_file"])
        matches = store.connection.execute(
            "SELECT doc_id, local_path FROM documents WHERE local_path = ? OR title = ?",
            (str(source), source.name),
        ).fetchone()
        confidence = 0.4
        doc_id = matches["doc_id"] if matches else hashlib.sha256(str(source).encode()).hexdigest()[:16]
        if not matches:
            if source.is_file() and source.suffix.casefold() in SUPPORTED:
                digest = hashlib.sha256(source.read_bytes()).hexdigest()
                doc_id = digest[:16]
                store.insert_document(Document(doc_id=doc_id, ticker=row["ticker"],
                                                source_type=SourceType.MANUAL,
                                                title=source.name, sha256=digest,
                                                local_path=str(source)))
                matches = {"doc_id": doc_id, "local_path": str(source)}
            else:
                rejected.append({"row": row["period"],
                                 "reason": "manual_unverified: source not registered"})
        else:
            try:
                text = "\n".join(text for _, text in
                                 read_document_pages(matches["local_path"]))
                if row["quote"] not in text:
                    rejected.append({"row": row["period"], "reason": "manual_unverified: quote not found"})
                    confidence = 0.4
                else:
                    confidence = 0.7
            except (OSError, ValueError, RuntimeError):
                rejected.append({"row": row["period"], "reason": "manual_unverified: source not parseable"})
                confidence = 0.4
        if matches:
            fact_id = hashlib.sha256(f"{row['ticker']}:{row['metric']}:{row['period']}:{row['quote']}".encode()).hexdigest()[:16]
            try:
                period_type = PeriodType.QUARTER if row["period"].upper().startswith("Q") else PeriodType.FY
                store.insert_fact(Fact(fact_id=fact_id, ticker=row["ticker"], metric=row["metric"],
                                       value=float(row["value"]), unit=row["unit"], period=row["period"],
                                       period_type=period_type, doc_id=doc_id, page=int(row["page"]),
                                       quote=row["quote"],
                                       extractor="csv_manual" if confidence >= 0.7
                                       else "csv_manual_unverified",
                                       confidence=confidence, restated=False))
                imported += 1
            except (ValueError, TypeError) as error:
                rejected.append({"row": row["period"], "reason": str(error)})
        elif not matches:
            fact_id = hashlib.sha256(
                f"{row['ticker']}:{row['metric']}:{row['period']}:{row['quote']}".encode()
            ).hexdigest()[:16]
            store.insert_fact(Fact(fact_id=fact_id, ticker=row["ticker"], metric=row["metric"],
                                   value=float(row["value"]), unit=row["unit"], period=row["period"],
                                   period_type=PeriodType.QUARTER if row["period"].upper().startswith("Q")
                                   else PeriodType.FY, doc_id=doc_id, page=int(row["page"]),
                                   quote=row["quote"], extractor="csv_manual",
                                   confidence=confidence, restated=False))
            imported += 1
    return {"imported": imported, "rejected": rejected}


def coverage(store: EvidenceStore, ticker: str) -> dict[str, dict[str, bool]]:
    facts = store.facts_for(ticker)
    periods = sorted({fact.period for fact in facts})
    metrics = sorted({fact.metric for fact in facts})
    available = {(fact.metric, fact.period) for fact in facts}
    derived = {
        "gnpa_pct": ("gross_npa",),
        "nnpa_pct": ("net_npa",),
        "credit_cost": ("provisions_on_npa", "write_offs"),
    }
    for metric, prerequisites in derived.items():
        if metric not in metrics:
            metrics.append(metric)
        for period in periods:
            if (all((prerequisite, period) in available for prerequisite in prerequisites) and
                    ("gross_advances", period) in available):
                available.add((metric, period))
    return {metric: {period: (metric, period) in available for period in periods}
            for metric in sorted(metrics)}
