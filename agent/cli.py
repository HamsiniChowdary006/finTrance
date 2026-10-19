import argparse
import csv
import json
import re
from pathlib import Path

import pandas as pd

from agent.calc.breaks import cusum, jump_quarters
from agent.calc.metrics import loan_growth_yoy
from agent.calc.timeseries import quarterly_frame
from agent.collector.manual import ManualDropSource
from agent.extractor.document import extract_facts, read_document_pages
from agent.extractor.validators import period_key
from agent.ingest import coverage, import_csv, ingest_company, validated_facts, validation_summary
from agent.orchestrator import Orchestrator
from agent.profiler import profile_company
from agent.render.report import markdown
from agent.scan.rules import evaluate_rules, load_rules
from agent.scan.scoring import rank_anomalies
from schemas.models import Fact, PeriodType
from store.dao import EvidenceStore

CORE_METRICS = (
    "gross_advances", "gross_npa", "net_npa", "gnpa_pct", "nnpa_pct",
    "write_offs", "provisions_on_npa", "stage2_assets", "stage3_assets",
    "casa_deposits", "total_deposits",
)


def write_golden(args) -> None:
    store = EvidenceStore()
    start_key, end_key = period_key(args.from_period), period_key(args.to_period)
    facts = [fact for fact in validated_facts(store, args.ticker)
             if start_key <= period_key(fact.period) <= end_key and
             fact.period]
    wanted = [item.strip() for item in args.metrics.split(",") if item.strip()]
    valid_names = set(store_metric_names(store, args.ticker)) | {"casa ratio", "casa_ratio", "credit_cost"}
    unknown = [item for item in wanted if item.casefold() not in
               {name.casefold() for name in valid_names}]
    if unknown:
        raise ValueError(f"unknown metric name(s): {', '.join(unknown)}; "
                         f"valid names: {', '.join(sorted(valid_names))}")
    periods = []
    for year in range(start_key[0], end_key[0] + 1):
        for quarter in range(1, 5):
            period = f"Q{quarter}FY{year}"
            if start_key <= period_key(period) <= end_key:
                periods.append(period)
    documents = {doc.doc_id: doc for doc in store.documents_for(args.ticker)}
    priority = {"exchange": 0, "manual": 0, "company_site": 1, "rating": 1}
    output = Path(args.out)
    repo_out = Path("out").resolve()
    if repo_out not in output.resolve().parents:
        raise ValueError("golden output must be under out/")
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for metric in wanted:
        metric_name = ("casa_deposits" if metric.casefold() in {"casa ratio", "casa_ratio"}
                       else metric)
        for period in periods:
            if metric.casefold() in {"casa ratio", "casa_ratio"}:
                casa = next((item for item in facts if item.metric == "casa_deposits"
                             and item.period == period), None)
                deposits = next((item for item in facts if item.metric == "total_deposits"
                                 and item.period == period), None)
                if casa and deposits and deposits.value:
                    rows.append({"metric": metric, "period": period,
                                 "normalized_value": casa.value / deposits.value * 100,
                                 "unit": "%", "basis": casa.basis,
                                 "source_file": documents[casa.doc_id].local_path,
                                 "page": casa.page, "quote": casa.quote,
                                 "validators_passed": "derived", "conflict": False})
                    continue
                rows.append({"metric": metric, "period": period,
                             "normalized_value": "", "unit": "", "basis": "",
                             "source_file": "", "page": "", "quote": "MISSING",
                             "validators_passed": "MISSING", "conflict": False})
                continue
            candidates = [fact for fact in facts
                          if fact.metric == metric_name and fact.period == period]
            candidates.sort(key=lambda fact: priority.get(
                documents[fact.doc_id].source_type.value, 9))
            fact = candidates[0] if candidates else None
            if metric.casefold() == "credit_cost" and not fact:
                provisions = next((item for item in facts
                                   if item.metric == "provisions_expense" and item.period == period), None)
                writeoffs = next((item for item in facts
                                  if item.metric == "write_offs" and item.period == period), None)
                advances = next((item for item in facts
                                 if item.metric == "gross_advances" and item.period == period), None)
                if provisions and advances:
                    numerator = provisions.value + (writeoffs.value if writeoffs else 0)
                    rows.append({
                        "metric": metric, "period": period,
                        "normalized_value": numerator * 4 / advances.value * 100,
                        "unit": "%", "basis": provisions.basis,
                        "source_file": documents[provisions.doc_id].local_path,
                        "page": provisions.page,
                        "quote": provisions.quote + (f" | {writeoffs.quote}" if writeoffs else ""),
                        "validators_passed": "derived",
                        "conflict": False,
                    })
                    continue
            rows.append({"metric": metric, "period": period,
                         "normalized_value": fact.normalized_value if fact else "",
                         "unit": fact.unit if fact else "", "basis": fact.basis if fact else "",
                         "source_file": documents[fact.doc_id].local_path if fact else "",
                         "page": fact.page if fact else "", "quote": fact.quote if fact else "MISSING",
                         "validators_passed": ",".join(k for k, v in fact.validator_status.items()
                                                       if v) if fact else "MISSING",
                         "conflict": fact.conflict if fact else False})
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else
                                ["metric", "period", "normalized_value"])
        writer.writeheader()
        writer.writerows(rows)


def store_metric_names(store: EvidenceStore, ticker: str) -> list[str]:
    return sorted({fact.metric for fact in store.facts_for(ticker)} |
                  {"gross_advances", "gross_npa", "net_npa", "gnpa_pct", "nnpa_pct",
                   "slippages", "write_offs", "provisions_expense", "provisions_on_npa",
                   "casa_deposits", "total_deposits"})


def doctor(ticker: str) -> None:
    store = EvidenceStore()
    facts = validated_facts(store, ticker)
    documents = store.documents_for(ticker)
    events = store.events_for(ticker)
    summary = validation_summary(store, ticker)
    print(f"doctor ticker={ticker}")
    print(f"documents={len(documents)} facts_validated={len(facts)} events={len(events)}")
    quarter_periods = sorted({fact.period for fact in store.facts_for(ticker)
                              if fact.period.startswith("Q")}, key=period_key)
    current_coverage = coverage(store, ticker)
    for metric, periods in current_coverage.items():
        quarter_values = {period: periods.get(period, False) for period in quarter_periods}
        filled = sum(quarter_values.values())
        print(f"{metric}: {filled}/{len(quarter_periods)} validated quarters")
    for metric, counts in sorted(summary.items()):
        print(f"validators {metric}: facts={counts['facts']} passed={counts['passed']} "
              f"rejected={counts['rejected']}")
    for document in documents:
        if "presentation" in document.title.casefold():
            pages = read_document_pages(document.local_path, count_tables=False)
            hits = [str(page) for page, text in pages
                    if any(alias in text.casefold() for alias in
                           ("gross advances", "gross loans", "advances (gross)", "total advances"))]
            if hits:
                print(f"gross_advances_alias_pages {document.title}: {','.join(hits)}")
    text_zero: list[str] = []
    image_only: list[str] = []
    rejection_reasons: dict[str, dict[str, int]] = {}
    for document in documents:
        if "results" not in document.title.casefold():
            continue
        diagnostic: dict[str, object] = {}
        try:
            pages = read_document_pages(document.local_path, diagnostic, ocr_seconds=0)
        except (OSError, ValueError, RuntimeError) as error:
            print(f"doctor_skip {document.title}: {error}")
            continue
        if not pages:
            image_only.append(document.title)
            continue
        period_hint = next(iter(re.findall(
            r"Q[1-4]FY(?:20)?\d{2}|FY(?:20)?\d{2}", document.title, re.IGNORECASE)), None)
        extracted = []
        for page, text in pages:
            extracted.extend(extract_facts(text, ticker, document.doc_id, period_hint,
                                            page, diagnostic))
        if not extracted:
            text_zero.append(document.title)
            if not diagnostic.get("aliases_matched"):
                all_metric_reasons = rejection_reasons.setdefault("all_metrics", {})
                all_metric_reasons["no aliases matched"] = (
                    all_metric_reasons.get("no aliases matched", 0) + 1)
        for reason in diagnostic.get("rejected", []):
            metric, detail = str(reason).split(":", 1)
            bucket = rejection_reasons.setdefault(metric, {})
            bucket[detail] = bucket.get(detail, 0) + 1
    if text_zero:
        print("text_with_zero_facts=" + ", ".join(text_zero))
    if image_only:
        print("image_only_files=" + ", ".join(image_only))
    for metric, reasons in sorted(rejection_reasons.items()):
        print(f"rejection_reasons {metric}: " +
              ", ".join(f"{reason}={count}" for reason, count in sorted(reasons.items())))
    duplicates = store.connection.execute(
        "SELECT sha256, COUNT(*) AS count FROM documents WHERE ticker=? GROUP BY sha256 HAVING COUNT(*) > 1",
        (ticker,)).fetchall()
    print("duplicates=" + str(sum(row["count"] - 1 for row in duplicates)))
    required = {
        "R1": {"gross_advances", "gnpa_pct"},
        "R2": {"gross_npa", "write_offs", "gross_advances"},
        "R3": {"gross_npa", "gross_advances", "provisions_on_npa"},
        "R4": {"gross_npa", "gross_advances", "provisions_on_npa"},
    }
    present = {fact.metric for fact in facts}
    for rule, metrics in required.items():
        missing = sorted(metrics - present)
        if not missing:
            print(f"{rule}: can run")
            continue
        details = []
        for metric in missing:
            missing_periods = [period for period in quarter_periods
                               if not current_coverage.get(metric, {}).get(period, False)]
            details.append(f"{metric} ({','.join(missing_periods) or 'all quarters'})")
        print(f"{rule}: blocked; missing " + "; ".join(details))


def main() -> int:
    if hasattr(__import__("sys").stdout, "reconfigure"):
        __import__("sys").stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    extract = sub.add_parser("extract")
    extract.add_argument("--company", required=True)
    extract.add_argument("--no-llm", action="store_true")
    analyze = sub.add_parser("analyze")
    analyze.add_argument("--company", required=True)
    analyze.add_argument("--peers", default="")
    analyze.add_argument("--json", dest="json_path")
    run = sub.add_parser("run")
    run.add_argument("--company", required=True)
    run.add_argument("--peers", default="")
    run.add_argument("--format", choices=("md", "json"), default="md")
    run.add_argument("--no-llm", action="store_true")
    ingest = sub.add_parser("ingest")
    ingest.add_argument("--company", required=True)
    ingest.add_argument("--ticker")
    ingest.add_argument("--from-dir", default="store/manual_drop")
    ingest.add_argument("--reingest", action="store_true")
    ingest.add_argument("--no-llm", action="store_true")
    ingest.add_argument("--ocr-timeout", type=float, default=90.0)
    doctor_parser = sub.add_parser("doctor")
    doctor_parser.add_argument("--ticker", required=True)
    facts = sub.add_parser("facts")
    facts_sub = facts.add_subparsers(dest="facts_command", required=True)
    facts_import = facts_sub.add_parser("import")
    facts_import.add_argument("--file", required=True)
    facts_audit = facts_sub.add_parser("audit")
    facts_audit.add_argument("--ticker", required=True)
    facts_audit.add_argument("--sample", type=int, default=10)
    facts_audit.add_argument("--only-failing", action="store_true")
    facts_audit.add_argument("--metric")
    facts_golden = facts_sub.add_parser("golden")
    facts_golden.add_argument("--ticker", required=True)
    facts_golden.add_argument("--metrics", required=True)
    facts_golden.add_argument("--from", dest="from_period", required=True)
    facts_golden.add_argument("--to", dest="to_period", required=True)
    facts_golden.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.command == "doctor":
        doctor(args.ticker)
    elif args.command == "extract":
        profile = profile_company(args.company)
        profile.symbol = args.company
        docs = ManualDropSource(Path("store/manual_drop")).search(profile)
        store = EvidenceStore()
        counts: dict[str, int] = {}
        rejected = 0
        for doc in docs:
            try:
                pages = read_document_pages(doc.local_path)
                facts = []
                for page, text in pages:
                    facts.extend(extract_facts(text, doc.ticker, doc.title, page=page))
            except (OSError, ValueError, ImportError) as error:
                print(f"rejected {doc.title}: {error}")
                rejected += 1
                continue
            for item in facts:
                item["period_type"] = PeriodType(item["period_type"])
                store.insert_fact(Fact.model_validate(item))
                counts[item["metric"]] = counts.get(item["metric"], 0) + 1
        print(f"company_type={profile.company_type.value} confidence={profile.confidence:.2f}")
        print("coverage matrix (metric x quarter):")
        for metric in CORE_METRICS:
            print(f"{metric}: {counts.get(metric, 0)} filled")
        print(f"documents={len(docs)} gaps=0 rejected_extractions={rejected}")
    elif args.command == "analyze":
        store = EvidenceStore()
        facts = store.facts_for(args.company)
        frame, provenance = quarterly_frame(facts)
        print(f"coverage for {args.company}:")
        if frame.empty:
            print("no real facts available; synthetic validation only")
            result = {"company": args.company, "quarters": [], "anomalies": [], "top3": []}
        elif args.facts_command == "audit":
            frame = frame.tail(12)
            print(frame.to_string())
            from agent.calc.timeseries import Provenance
            growth = loan_growth_yoy(
                Provenance(
                    frame.get("gross_advances", pd.Series(index=frame.index, dtype=float)),
                    {period: provenance.get(period, {}).get("gross_advances", [])
                     for period in frame.index},
                )
            )
            data = {"loan_growth_yoy": growth}
            anomalies = evaluate_rules(data, load_rules())
            top3 = rank_anomalies(anomalies)
            changes = jump_quarters(frame["gross_advances"]) if "gross_advances" in frame else []
            change_points = [point.quarter for point in cusum(frame["gross_advances"])] if "gross_advances" in frame else []
            print(f"jump_quarters={changes}")
            print(f"change_points={change_points}")
            print(f"anomalies={anomalies}")
            print(f"top3={top3}")
            result = {"company": args.company, "quarters": list(frame.index),
                      "anomalies": [item.model_dump() for item in anomalies],
                      "top3": [item.model_dump() for item in top3]}
        if args.json_path:
            Path(args.json_path).write_text(json.dumps(result, default=str, indent=2), encoding="utf-8")
    elif args.command == "run":
        peers = [item.strip() for item in args.peers.split(",") if item.strip()]
        result = Orchestrator(callback=lambda event: print(
            f"[{event['stage']}] {event['status']}: {event['message']}")).run(
                args.company, peers=peers)
        output = result.report.model_dump_json(indent=2) if args.format == "json" else markdown(result.report)
        print(output)
    elif args.command == "ingest":
        store = EvidenceStore()
        result = ingest_company(args.company, args.from_dir, args.ticker, store,
                                reingest=args.reingest, ocr_seconds=args.ocr_timeout)
        print(f"documents={result['documents']} facts={result['facts']} "
              f"rejected={len(result['rejected'])} empty={len(result['empty'])}")
        for metric, periods in coverage(store, result["ticker"]).items():
            print(f"{metric}: " + " ".join(f"{period}={'filled' if filled else 'missing'}"
                                           for period, filled in periods.items()))
        for item in result["rejected"]:
            print(f"rejected {item['file']}: {item['reason']}")
        for item in result["empty"]:
            print(f"no facts: {item}")
        for item in result.get("diagnostics", []):
            print("diagnostic "
                  f"{item.get('file')}: pages={item.get('pages', 0)} "
                  f"pages_parsed={item.get('pages_parsed', 0)} chars={item.get('chars', 0)} "
                  f"chars_parsed={item.get('chars_parsed', 0)} "
                  f"tables={item.get('tables_found', 0)} "
                  f"aliases={','.join(item.get('aliases_matched', [])) or '-'} "
                  f"ocr_pages={item.get('ocr_pages', 0)} facts={item.get('facts', 0)}")
            if item.get("text_zero_facts"):
                print(f"zero-facts-text-file {item.get('file')}: "
                      f"{item.get('candidate_rejections', [])}")
            if item.get("ocr_status"):
                print(f"{item.get('file')}: {item['ocr_status']} "
                      f"pages={item.get('ocr_incomplete_pages', [])}")
        print(f"events={result.get('events', 0)}")
        print(f"validator_rejections={result.get('validator_rejections', 0)}")
        for metric, count in sorted(result.get("validator_rejections_by_metric", {}).items()):
            print(f"validator_rejections[{metric}]={count}")
        for item in result.get("duplicate_files", []):
            print(f"duplicate: {item}")
        if result.get("image_only_files"):
            print("WARNING image-only files skipped (OCR unavailable): " +
                  ", ".join(result["image_only_files"]))
        if result.get("ocr_incomplete_files"):
            print("OCR summary: OCR incomplete for " +
                  ", ".join(result["ocr_incomplete_files"]))
    elif args.command == "facts":
        if args.facts_command == "import":
            result = import_csv(args.file)
            print(f"imported={result['imported']} rejected={len(result['rejected'])}")
            for item in result["rejected"]:
                print(f"rejected {item['row']}: {item['reason']}")
        elif args.facts_command == "golden":
            write_golden(args)
        elif args.facts_command == "audit":
            import random
            store = EvidenceStore()
            facts = store.facts_for(args.ticker)
            documents = {doc.doc_id: doc for doc in store.documents_for(args.ticker)}
            page_cache: dict[str, dict[int, str]] = {}
            print(f"coverage for {args.ticker}:")
            by_metric: dict[str, set[str]] = {}
            for fact in facts:
                by_metric.setdefault(fact.metric, set()).add(fact.period)
            for metric, periods in sorted(by_metric.items()):
                print(f"{metric}: {len(periods)} periods")
            print(f"facts={len(facts)} events={len(store.events_for(args.ticker))}")
            selected = [fact for fact in facts
                        if (not args.metric or fact.metric == args.metric) and
                        (not args.only_failing or not all(fact.validator_status.values()))]
            selected = random.Random(args.ticker).sample(selected, min(args.sample, len(selected)))
            for fact in selected:
                print(f"{fact.metric} {fact.period} value={fact.value} unit={fact.unit} "
                      f"normalized={fact.normalized_value} basis={fact.basis} page={fact.page} "
                      f"source={documents.get(fact.doc_id).local_path if fact.doc_id in documents else '-'} "
                      f"quote={fact.quote} validators={fact.validator_status}")
            mismatches = []
            for fact in facts:
                document = documents.get(fact.doc_id)
                if not document:
                    mismatches.append((fact.fact_id, "document not registered"))
                    continue
                try:
                    if fact.doc_id not in page_cache:
                        page_cache[fact.doc_id] = dict(
                            read_document_pages(document.local_path, count_tables=False))
                    page_text = page_cache[fact.doc_id].get(fact.page, "")
                    if fact.quote not in page_text:
                        mismatches.append((fact.fact_id, "quote not found on source page"))
                except (OSError, ValueError, RuntimeError) as error:
                    mismatches.append((fact.fact_id, str(error)))
            print(f"quote_validation={len(facts) - len(mismatches)}/{len(facts)}")
            for fact_id, reason in mismatches:
                print(f"quote_mismatch {fact_id}: {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
