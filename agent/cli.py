import argparse
import json
from pathlib import Path

import pandas as pd

from agent.calc.breaks import cusum, jump_quarters
from agent.calc.metrics import loan_growth_yoy
from agent.calc.timeseries import quarterly_frame
from agent.collector.manual import ManualDropSource
from agent.extractor.document import extract_facts, read_document_pages
from agent.ingest import coverage, import_csv, ingest_company
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
    facts = sub.add_parser("facts")
    facts_sub = facts.add_subparsers(dest="facts_command", required=True)
    facts_import = facts_sub.add_parser("import")
    facts_import.add_argument("--file", required=True)
    facts_audit = facts_sub.add_parser("audit")
    facts_audit.add_argument("--ticker", required=True)
    facts_audit.add_argument("--sample", type=int, default=10)
    args = parser.parse_args()
    if args.command == "extract":
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
        else:
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
        result = ingest_company(args.company, args.from_dir, args.ticker, store)
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
        print(f"events={result.get('events', 0)}")
    elif args.command == "facts":
        if args.facts_command == "import":
            result = import_csv(args.file)
            print(f"imported={result['imported']} rejected={len(result['rejected'])}")
            for item in result["rejected"]:
                print(f"rejected {item['row']}: {item['reason']}")
        else:
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
            for fact in random.Random(args.ticker).sample(facts, min(args.sample, len(facts))):
                print(f"{fact.metric} {fact.period} value={fact.value} unit={fact.unit} "
                      f"page={fact.page} quote={fact.quote}")
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
